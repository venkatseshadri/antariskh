#!/usr/bin/env python3
"""
Code Conformance Audit Loop — the scheduled, PROPOSE-ONLY file reviewer.

Walks every project Python file and judges it against TRADING_SYSTEM.md:
  - Does the file still have a purpose? (orphan / dead-code candidate)
  - Does it conform to the architecture in the spec?
  - Is it a god-file / TODO-laden / stale?

It NEVER edits or deletes anything. It writes two artifacts:
  - docs/REVIEW_FINDINGS.md   (human-readable, latest sweep)
  - data/code_audit.jsonl     (append-only ledger, one record per reviewed file)

Findings feed the E5 backlog via ralph/triage_findings.py. Every removal stays
human/Chairman-gated (PRD §E4, Board rule: Claude/audit raises, DeepSeek implements).

Backends:
  heuristic (default) — deterministic signals, zero deps, runnable today.
  llm                 — shells out to $CODE_AUDIT_LLM_CMD (prompt on stdin → JSON on
                        stdout) for a semantic conformance verdict. Wired in S4.1.

Usage:
  python -m ralph.code_audit_loop --mode incremental      # changed files + rolling window
  python -m ralph.code_audit_loop --mode full             # whole tree
  python -m ralph.code_audit_loop --backend llm --mode full
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import warnings

# Scanning third-party / legacy files with ast.parse surfaces their own
# SyntaxWarnings (invalid escapes etc.). Silence them — not our concern.
warnings.filterwarnings("ignore", category=SyntaxWarning)
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Repos to audit and where to write artifacts. Roots are resolved relative to
# this file's grandparent (the trading_ceo home).
HOME = Path(__file__).resolve().parents[2]
REPOS = ["antariksh", "brahmand", "python-trader"]
EXCLUDE_PARTS = {
    ".git", "__pycache__", "site-packages", "venv", ".venv",
    "node_modules", "archives", "graphify-out", ".opencode",
}
SPEC_PATH = HOME / "TRADING_SYSTEM.md"
FINDINGS_MD = HOME / "antariksh" / "docs" / "REVIEW_FINDINGS.md"
LEDGER_JSONL = HOME / "antariksh" / "data" / "code_audit.jsonl"
STATE_PATH = HOME / "antariksh" / "data" / "code_audit_state.json"
ROLLING_WINDOW = 25  # stale files reviewed per incremental run so the tree gets covered


# The review rubric — every reviewed file is judged on these dimensions. The heuristic
# backend fills the ones detectable from structure; the llm backend fills all of them
# semantically. Goal: scalable, readable, maintainable, well-designed code that any human
# or system can understand with little effort.
RUBRIC = [
    "purpose",        # does the file still have a clear, single reason to exist?
    "test_coverage",  # is there a test exercising it?
    "simplification", # can it be optimized / redefined / refactored / simplified?
    "documentation",  # module/function docstrings, comments where non-obvious
    "complexity",     # readable, low cyclomatic complexity, short functions
    "performance",    # any obvious poor-performance pattern
    "srp_modularity", # single responsibility, modular, not a god-file
    "naming",         # clear module/class/method/variable names
    "design",         # follows the system's design philosophy (code-enforces, fail-closed)
]


@dataclass
class Finding:
    path: str
    sweep_ts: str
    verdict: str            # KEEP | REVIEW | REMOVE_CANDIDATE
    severity: str           # info | low | medium | high
    conformance: str        # conforms | unclear | violates
    remove_candidate: bool
    reasons: list = field(default_factory=list)
    dimensions: dict = field(default_factory=dict)  # rubric -> "ok|warn|flag: note"
    loc: int = 0
    backend: str = "heuristic"


# --------------------------------------------------------------------------- #
# File enumeration
# --------------------------------------------------------------------------- #
def iter_py_files() -> list[Path]:
    files: list[Path] = []
    for repo in REPOS:
        root = HOME / repo
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if EXCLUDE_PARTS & set(p.parts):
                continue
            files.append(p)
    return sorted(files)


def git_changed_since(state: dict) -> set[Path]:
    """Files changed (per-repo) since the last recorded commit, plus uncommitted."""
    changed: set[Path] = set()
    for repo in REPOS:
        root = HOME / repo
        if not (root / ".git").exists():
            continue
        last = state.get("last_commit", {}).get(repo)
        try:
            if last:
                out = subprocess.run(
                    ["git", "-C", str(root), "diff", "--name-only", f"{last}..HEAD"],
                    capture_output=True, text=True, timeout=30,
                ).stdout
            else:
                out = ""
            dirty = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=30,
            ).stdout
        except Exception:
            continue
        for line in (out + "\n" + dirty).splitlines():
            name = line[3:].strip() if line[:3] in (" M ", "?? ", " A ", "MM ") else line.strip()
            name = name.split(" -> ")[-1].strip()
            if name.endswith(".py"):
                fp = root / name
                if fp.exists() and not (EXCLUDE_PARTS & set(fp.parts)):
                    changed.add(fp)
    return changed


def current_commits() -> dict:
    out = {}
    for repo in REPOS:
        root = HOME / repo
        try:
            sha = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=15,
            ).stdout.strip()
            if sha:
                out[repo] = sha
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------- #
# Import map (orphan detection) — built once per sweep
# --------------------------------------------------------------------------- #
def build_imported_stems(files: list[Path]) -> set[str]:
    """Set of module stems referenced by an import anywhere in the tree."""
    imported: set[str] = set()
    for p in files:
        try:
            tree = ast.parse(p.read_text(errors="ignore"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imported.add(n.name.split(".")[-1])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[-1])
                for n in node.names:
                    imported.add(n.name)
    return imported


def is_entrypoint(p: Path, text: str) -> bool:
    if '__main__' in text and 'if __name__' in text:
        return True
    # referenced by a shell/cron wrapper?
    stem = p.stem
    for repo in REPOS:
        cron = HOME / repo / "cron"
        if cron.exists():
            for sh in cron.glob("*.sh"):
                try:
                    if stem in sh.read_text(errors="ignore"):
                        return True
                except Exception:
                    pass
    return False


# --------------------------------------------------------------------------- #
# AST analysis (structural rubric signals)
# --------------------------------------------------------------------------- #
def build_test_corpus(files: list[Path]) -> str:
    """Concatenated text of every test file — a module is 'tested' if named here."""
    parts = []
    for p in files:
        if "/tests/" in str(p) or p.stem.startswith("test_"):
            try:
                parts.append(p.read_text(errors="ignore"))
            except Exception:
                pass
    return "\n".join(parts)


_BAD_NAMES = {"l", "I", "O", "ll", "tmp", "tmp2", "foo", "bar", "data2", "x1", "x2"}


def analyze_ast(text: str) -> dict:
    """Structural metrics: docstrings, function lengths, class/def counts, weak names."""
    out = {"ok": True, "module_doc": False, "n_classes": 0, "n_defs": 0,
           "max_func_loc": 0, "undocumented_pub": 0, "deep_nesting": 0, "weak_names": []}
    try:
        tree = ast.parse(text)
    except Exception:
        out["ok"] = False
        return out
    out["module_doc"] = ast.get_docstring(tree) is not None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            out["n_classes"] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["n_defs"] += 1
            if node.end_lineno and node.lineno:
                out["max_func_loc"] = max(out["max_func_loc"], node.end_lineno - node.lineno)
            if not node.name.startswith("_") and ast.get_docstring(node) is None:
                out["undocumented_pub"] += 1
        elif isinstance(node, (ast.Name, ast.arg)):
            nm = getattr(node, "id", None) or getattr(node, "arg", "")
            if nm in _BAD_NAMES and nm not in out["weak_names"]:
                out["weak_names"].append(nm)
    return out


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
def review_heuristic(p: Path, imported: set[str], test_corpus: str = "") -> Finding:
    ts = datetime.now(timezone.utc).isoformat()
    text = p.read_text(errors="ignore")
    loc = text.count("\n") + 1
    reasons: list[str] = []
    dims: dict = {k: "ok" for k in RUBRIC}
    remove = False
    conformance = "unclear"
    severity = "info"

    def bump(level: str) -> None:
        nonlocal severity
        rank = {"info": 0, "low": 1, "medium": 2, "high": 3}
        if rank[level] > rank[severity]:
            severity = level

    stem = p.stem
    entry = is_entrypoint(p, text)
    is_test = "/tests/" in str(p) or stem.startswith("test_")
    referenced = stem in imported
    meta = analyze_ast(text)

    # purpose / orphan
    if not referenced and not entry and not is_test and stem != "__init__":
        reasons.append("orphan: stem never imported and no __main__/cron reference")
        dims["purpose"] = "flag: orphan, no caller/entrypoint"
        remove = True
        bump("medium")

    # test_coverage
    if not is_test and stem != "__init__" and test_corpus and stem not in test_corpus:
        reasons.append("no test references this module")
        dims["test_coverage"] = "flag: no test_*.py mentions this module"
        bump("low")

    # documentation
    if meta["ok"]:
        doc_problems = []
        if not meta["module_doc"]:
            doc_problems.append("no module docstring")
        if meta["undocumented_pub"]:
            doc_problems.append(f"{meta['undocumented_pub']} public defs lack docstrings")
        if doc_problems:
            dims["documentation"] = "warn: " + "; ".join(doc_problems)
            if meta["undocumented_pub"] >= 5:
                reasons.append(doc_problems[-1]); bump("low")

    # complexity
    if meta["max_func_loc"] > 60:
        reasons.append(f"long function: {meta['max_func_loc']} LOC (>60) — hard to follow")
        dims["complexity"] = f"flag: function spans {meta['max_func_loc']} lines"
        bump("medium")

    # srp_modularity / god-file
    if loc > 500:
        reasons.append(f"god-file: {loc} LOC (>500) — split candidate")
        dims["srp_modularity"] = f"flag: {loc} LOC"
        bump("medium")
    if meta["n_classes"] + (meta["n_defs"] > 15) and meta["n_classes"] >= 3:
        dims["srp_modularity"] = f"warn: {meta['n_classes']} classes in one module — SRP smell"

    # naming
    if meta["weak_names"]:
        reasons.append("weak identifiers: " + ", ".join(meta["weak_names"][:6]))
        dims["naming"] = "warn: " + ", ".join(meta["weak_names"][:6])
        bump("low")

    # simplification (TODO/FIXME density is the cheap proxy)
    todos = text.count("TODO") + text.count("FIXME") + text.count("XXX")
    if todos >= 5:
        reasons.append(f"{todos} TODO/FIXME/XXX markers — unfinished/refactor pending")
        dims["simplification"] = f"warn: {todos} TODO/FIXME markers"
        bump("low")

    # design / conformance: dir-in-spec check
    try:
        rel = p.relative_to(HOME)
        top = rel.parts[1] if len(rel.parts) > 2 else rel.parts[-1]
        spec = SPEC_PATH.read_text(errors="ignore")
        if top not in spec and not is_test and top not in ("config", "data", "logs"):
            reasons.append(f"dir '{top}' not in TRADING_SYSTEM.md repo map")
            dims["design"] = f"warn: dir '{top}' not in spec map"
    except Exception:
        pass

    # performance is left to the llm backend (no cheap reliable structural proxy)
    dims["performance"] = "n/a (heuristic)"

    verdict = "REMOVE_CANDIDATE" if remove else ("REVIEW" if reasons else "KEEP")
    if not reasons:
        reasons.append("no heuristic flags")
        conformance = "conforms"
    return Finding(
        path=str(p.relative_to(HOME)), sweep_ts=ts, verdict=verdict,
        severity=severity, conformance=conformance, remove_candidate=remove,
        reasons=reasons, dimensions=dims, loc=loc, backend="heuristic",
    )


_LLM_RUBRIC_PROMPT = (
    "You are a PROPOSE-ONLY senior code reviewer. You never edit; you only judge. Review the "
    "Python file against the trading-system spec AND these rubric dimensions, scoring each "
    "ok|warn|flag with a one-line note:\n"
    "  purpose         — clear single reason to exist? redundant/dead?\n"
    "  test_coverage   — exercised by a test? critical paths covered?\n"
    "  simplification  — can it be optimized/redefined/refactored/simplified?\n"
    "  documentation   — module/function docstrings; comments where non-obvious?\n"
    "  complexity      — readable, low cyclomatic complexity, short functions?\n"
    "  performance     — any obvious poor-performance pattern (O(n^2), per-tick rescans, "
    "repeated I/O, missing caching)?\n"
    "  srp_modularity  — single responsibility, modular, not a god-file?\n"
    "  naming          — clear module/class/method/variable names?\n"
    "  design          — follows the system's philosophy: code-enforces-risk, fail-closed, "
    "deterministic-over-LLM for risk/execution?\n"
    "Goal: highly scalable, readable, maintainable, well-designed code any human/system can "
    "understand with little effort. Return ONLY JSON:\n"
    '{"verdict":"KEEP|REVIEW|REMOVE_CANDIDATE","severity":"info|low|medium|high",'
    '"conformance":"conforms|unclear|violates","remove_candidate":bool,'
    '"reasons":["..."],"dimensions":{"purpose":"ok|warn|flag: note", ...all 9...}}'
)


def review_llm(p: Path, imported: set[str], test_corpus: str = "") -> Finding:
    cmd = os.environ.get("CODE_AUDIT_LLM_CMD")
    if not cmd:
        f = review_heuristic(p, imported, test_corpus)
        f.reasons.insert(0, "LLM backend requested but $CODE_AUDIT_LLM_CMD unset — heuristic fallback")
        return f
    spec = SPEC_PATH.read_text(errors="ignore")[:6000]
    content = p.read_text(errors="ignore")[:12000]
    tested = "yes" if (test_corpus and p.stem in test_corpus) else "no test mentions it"
    prompt = (
        f"{_LLM_RUBRIC_PROMPT}\n\n"
        f"(structural hint — test references this module: {tested})\n\n"
        f"=== SPEC (TRADING_SYSTEM.md excerpt) ===\n{spec}\n\n"
        f"=== FILE {p.relative_to(HOME)} ===\n{content}\n"
    )
    ts = datetime.now(timezone.utc).isoformat()
    loc = content.count("\n") + 1
    try:
        proc = subprocess.run(cmd, shell=True, input=prompt, capture_output=True,
                              text=True, timeout=120)
        data = json.loads(proc.stdout[proc.stdout.find("{"): proc.stdout.rfind("}") + 1])
        return Finding(
            path=str(p.relative_to(HOME)), sweep_ts=ts,
            verdict=data.get("verdict", "REVIEW"), severity=data.get("severity", "info"),
            conformance=data.get("conformance", "unclear"),
            remove_candidate=bool(data.get("remove_candidate", False)),
            reasons=data.get("reasons", []), dimensions=data.get("dimensions", {}),
            loc=loc, backend="llm",
        )
    except Exception as e:
        f = review_heuristic(p, imported, test_corpus)
        f.reasons.insert(0, f"LLM review failed ({e}) — heuristic fallback")
        return f


# --------------------------------------------------------------------------- #
# Sweep
# --------------------------------------------------------------------------- #
def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {}


def pick_targets(mode: str, all_files: list[Path], state: dict) -> list[Path]:
    if mode == "full":
        return all_files
    changed = git_changed_since(state)
    seen = state.get("seen_order", [])
    seen_set = set(seen)
    stale = [f for f in all_files if str(f) not in seen_set]
    if not stale:  # full cycle covered — reset rolling cursor
        stale = all_files
    targets = list(changed) + stale[:ROLLING_WINDOW]
    # de-dup preserving order
    out, s = [], set()
    for f in targets:
        if f not in s:
            out.append(f); s.add(f)
    return out


def render_markdown(findings: list[Finding], mode: str) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings = sorted(findings, key=lambda f: (order.get(f.severity, 9), f.path))
    removes = [f for f in findings if f.remove_candidate]
    lines = [
        "# Code Conformance Audit — Findings (PROPOSE ONLY)",
        "",
        f"> Sweep: **{mode}** · {ts} · {len(findings)} files reviewed · "
        f"**{len(removes)} removal candidates**. This reviewer never edits or deletes — "
        "every action is human/Chairman-gated via `triage_findings.py` → E5 stories.",
        "",
        "| Severity | File | Verdict | Conformance | Reasons |",
        "|---|---|---|---|---|",
    ]
    for f in findings:
        if f.verdict == "KEEP":
            continue
        reasons = "; ".join(f.reasons)[:160].replace("|", "\\|")
        lines.append(
            f"| {f.severity} | `{f.path}` | {f.verdict} | {f.conformance} | {reasons} |"
        )
    lines += ["", f"_KEEP (no flags): {sum(1 for f in findings if f.verdict=='KEEP')} files not listed._", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    ap.add_argument("--backend", choices=["heuristic", "llm"], default="heuristic")
    args = ap.parse_args()

    state = load_state()
    all_files = iter_py_files()
    if not all_files:
        print("No Python files found to audit.", file=sys.stderr)
        return 1
    imported = build_imported_stems(all_files)
    test_corpus = build_test_corpus(all_files)
    targets = pick_targets(args.mode, all_files, state)
    reviewer = review_llm if args.backend == "llm" else review_heuristic

    findings = [reviewer(p, imported, test_corpus) for p in targets]

    LEDGER_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_JSONL.open("a") as fh:
        for f in findings:
            fh.write(json.dumps(asdict(f)) + "\n")
    FINDINGS_MD.parent.mkdir(parents=True, exist_ok=True)
    FINDINGS_MD.write_text(render_markdown(findings, args.mode))

    seen = state.get("seen_order", [])
    seen = (seen + [str(p) for p in targets]) if args.mode == "incremental" else []
    # keep cursor bounded
    if len(seen) > len(all_files):
        seen = seen[-len(all_files):]
    state.update({
        "last_run": datetime.now(timezone.utc).isoformat(),
        "last_commit": current_commits(),
        "seen_order": seen,
    })
    STATE_PATH.write_text(json.dumps(state, indent=2))

    removes = sum(1 for f in findings if f.remove_candidate)
    print(f"Audit {args.mode}/{args.backend}: {len(findings)} reviewed, "
          f"{removes} removal candidates. → {FINDINGS_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
