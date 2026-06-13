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
    # runtime output, not source — never review these
    "logs", "recordings", "exec_reports", "harvested", "locks", "backups",
}
# Review EVERY project file, not just Python: code, config, and docs.
TARGET_EXTS = {".py", ".md", ".json", ".yaml", ".yml", ".sh",
               ".toml", ".cfg", ".ini", ".sql"}
SPEC_PATH = HOME / "TRADING_SYSTEM.md"
FINDINGS_MD = HOME / "antariksh" / "docs" / "REVIEW_FINDINGS.md"
LEDGER_JSONL = HOME / "antariksh" / "data" / "code_audit.jsonl"
STATE_PATH = HOME / "antariksh" / "data" / "code_audit_state.json"
# Per-file review manifest: path -> {hash, last_reviewed, verdict, severity}. This is what
# makes the audit a continuous ralph loop — each file is tracked as reviewed, and only
# re-reviewed when its content changes or its review goes stale.
MANIFEST_PATH = HOME / "antariksh" / "data" / "code_audit_manifest.json"
STALE_DAYS = 14       # re-review a file if last reviewed longer ago than this
REVIEW_BATCH = 60     # files reviewed per incremental run (chips through the backlog)


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
def _is_cronish(p: Path) -> bool:
    """Cron tables have no standard extension — match by name/parent."""
    n = p.name.lower()
    return ("crontab" in n or n.endswith(".cron")
            or (p.parent.name == "cron.d") or n.startswith("antariksh-")
            or n.startswith("penguin-"))


def _is_target(p: Path) -> bool:
    if EXCLUDE_PARTS & set(p.parts):
        return False
    if p.name.startswith("code_audit") or p.name == "REVIEW_FINDINGS.md":
        return False  # never review the audit loop's own output artifacts
    return p.suffix.lower() in TARGET_EXTS or _is_cronish(p)


def iter_target_files() -> list[Path]:
    """Every reviewable project file: code, config, docs, shell, and cron tables."""
    files: list[Path] = []
    for repo in REPOS:
        root = HOME / repo
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and _is_target(p):
                files.append(p)
    return sorted(set(files))


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
            if not name:
                continue
            fp = root / name
            if fp.exists() and _is_target(fp):
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
        if p.suffix != ".py":
            continue
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
import re

_REF_RE = re.compile(r'(/home/trading_ceo/[\w./-]+|(?<![\w/])[\w][\w./-]*\.(?:sh|py|service|timer|json|yaml|yml|md))')


def find_dead_refs(text: str, p: Path) -> list[str]:
    """File paths referenced by this file that do not exist on disk (stale/dead links)."""
    dead: list[str] = []
    for raw in {m.rstrip('.:,)') for m in _REF_RE.findall(text)}:
        if '$' in raw or '*' in raw or raw.startswith('http') or '{' in raw:
            continue
        cand = Path(raw) if raw.startswith('/') else (p.parent / raw)
        if cand.suffix and not cand.exists():
            dead.append(raw)
    return sorted(dead)[:8]


def _review_python(p, text, loc, imported, test_corpus, dims, reasons, bump) -> bool:
    """Python-specific rubric. Returns remove_candidate."""
    stem = p.stem
    is_test = "/tests/" in str(p) or stem.startswith("test_")
    remove = False
    meta = analyze_ast(text)
    if not (stem in imported) and not is_entrypoint(p, text) and not is_test and stem != "__init__":
        reasons.append("orphan: stem never imported and no __main__/cron reference")
        dims["purpose"] = "flag: orphan, no caller/entrypoint"; remove = True; bump("medium")
    if not is_test and stem != "__init__" and test_corpus and stem not in test_corpus:
        reasons.append("no test references this module")
        dims["test_coverage"] = "flag: no test_*.py mentions this module"; bump("low")
    if meta["ok"]:
        dp = []
        if not meta["module_doc"]:
            dp.append("no module docstring")
        if meta["undocumented_pub"]:
            dp.append(f"{meta['undocumented_pub']} public defs lack docstrings")
        if dp:
            dims["documentation"] = "warn: " + "; ".join(dp)
            if meta["undocumented_pub"] >= 5:
                reasons.append(dp[-1]); bump("low")
    if meta["max_func_loc"] > 60:
        reasons.append(f"long function: {meta['max_func_loc']} LOC (>60) — hard to follow")
        dims["complexity"] = f"flag: function spans {meta['max_func_loc']} lines"; bump("medium")
    if loc > 500:
        reasons.append(f"god-file: {loc} LOC (>500) — split candidate")
        dims["srp_modularity"] = f"flag: {loc} LOC"; bump("medium")
    elif meta["n_classes"] >= 3:
        dims["srp_modularity"] = f"warn: {meta['n_classes']} classes in one module — SRP smell"
    if meta["weak_names"]:
        reasons.append("weak identifiers: " + ", ".join(meta["weak_names"][:6]))
        dims["naming"] = "warn: " + ", ".join(meta["weak_names"][:6]); bump("low")
    dims["performance"] = "n/a (heuristic)"
    return remove


def _review_shell_cron(p, text, dims, reasons, bump) -> None:
    """Shell scripts + cron tables: shebang, dead path refs, stale jobs, disabled units."""
    for d in ("test_coverage", "complexity", "performance", "naming"):
        dims[d] = "n/a (shell/cron)"
    if p.suffix.lower() == ".sh" and not text.lstrip().startswith("#!"):
        reasons.append("shell script missing shebang")
        dims["design"] = "warn: no shebang"; bump("low")
    dead = find_dead_refs(text, p)
    if dead:
        reasons.append("dead path refs (stale job?): " + ", ".join(dead[:5]))
        dims["purpose"] = "flag: references files that don't exist"; bump("medium")
    if _is_cronish(p):
        if ".disabled" in text:
            reasons.append("cron references a .disabled unit — stale job")
            dims["simplification"] = "warn: disabled-unit reference"; bump("low")
        # cron line sanity: each non-comment line should have >=6 fields (5 time + cmd)
        for ln in text.splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" not in s.split()[0] and len(s.split()) < 6:
                reasons.append(f"cron line looks malformed: '{s[:40]}'")
                dims["design"] = "flag: malformed cron line"; bump("medium"); break


def _review_config_doc(p, text, dims, reasons, bump) -> None:
    """JSON/YAML validity + markdown dead links."""
    for d in ("test_coverage", "complexity", "performance", "naming", "srp_modularity"):
        dims[d] = "n/a (non-code)"
    suf = p.suffix.lower()
    if suf == ".json":
        try:
            json.loads(text)
        except Exception as e:
            reasons.append(f"invalid JSON: {str(e)[:60]}")
            dims["design"] = "flag: does not parse"; bump("high")
    elif suf in (".yaml", ".yml"):
        try:
            import yaml
            yaml.safe_load(text)
        except ImportError:
            pass
        except Exception as e:
            reasons.append(f"invalid YAML: {str(e)[:60]}")
            dims["design"] = "flag: does not parse"; bump("high")
    elif suf == ".md":
        dead = find_dead_refs(text, p)
        if dead:
            reasons.append("dead doc links: " + ", ".join(dead[:5]))
            dims["purpose"] = "flag: links to missing files"; bump("low")


def review_heuristic(p: Path, imported: set[str], test_corpus: str = "") -> Finding:
    ts = datetime.now(timezone.utc).isoformat()
    text = p.read_text(errors="ignore")
    loc = text.count("\n") + 1
    reasons: list[str] = []
    dims: dict = {k: "ok" for k in RUBRIC}
    remove = False
    conformance = "unclear"
    severity = "info"
    is_test = "/tests/" in str(p) or p.stem.startswith("test_")

    def bump(level: str) -> None:
        nonlocal severity
        rank = {"info": 0, "low": 1, "medium": 2, "high": 3}
        if rank[level] > rank[severity]:
            severity = level

    # type-specific review
    if p.suffix.lower() == ".py":
        remove = _review_python(p, text, loc, imported, test_corpus, dims, reasons, bump)
    elif p.suffix.lower() == ".sh" or _is_cronish(p):
        _review_shell_cron(p, text, dims, reasons, bump)
    else:
        _review_config_doc(p, text, dims, reasons, bump)

    # common: TODO/FIXME density → simplification
    todos = text.count("TODO") + text.count("FIXME") + text.count("XXX")
    if todos >= 5:
        reasons.append(f"{todos} TODO/FIXME/XXX markers — unfinished/refactor pending")
        dims["simplification"] = f"warn: {todos} TODO/FIXME markers"; bump("low")

    # common: dir-in-spec (design/conformance)
    try:
        rel = p.relative_to(HOME)
        top = rel.parts[1] if len(rel.parts) > 2 else rel.parts[-1]
        spec = SPEC_PATH.read_text(errors="ignore")
        if top not in spec and not is_test and top not in ("config", "data", "logs"):
            reasons.append(f"dir '{top}' not in TRADING_SYSTEM.md repo map")
            if dims["design"] == "ok":
                dims["design"] = f"warn: dir '{top}' not in spec map"
    except Exception:
        pass

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
    "You are a PROPOSE-ONLY senior reviewer. You never edit; you only judge. Review this file "
    "(Python, shell, cron, JSON/YAML config, or markdown doc) against the trading-system spec "
    "AND these rubric dimensions (mark n/a where a dimension doesn't apply), scoring each "
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
import hashlib


def file_hash(p: Path) -> str:
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except Exception:
            pass
    return {}


def _age_days(iso_ts: str) -> float:
    try:
        then = datetime.fromisoformat(iso_ts)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - then).total_seconds() / 86400.0
    except Exception:
        return 1e9


def review_status(all_files: list[Path], manifest: dict) -> dict:
    """Classify every file as reviewed / changed / stale / new against the manifest."""
    rel = lambda p: str(p.relative_to(HOME))  # noqa: E731
    new, changed, stale, reviewed = [], [], [], []
    for p in all_files:
        key = rel(p)
        rec = manifest.get(key)
        if rec is None:
            new.append(p)
        elif rec.get("hash") != file_hash(p):
            changed.append(p)
        elif _age_days(rec.get("last_reviewed", "")) > STALE_DAYS:
            stale.append(p)
        else:
            reviewed.append(p)
    return {"new": new, "changed": changed, "stale": stale, "reviewed": reviewed}


def pick_targets(mode: str, all_files: list[Path], manifest: dict) -> list[Path]:
    """Files needing review: new + changed first, then stale, capped per run (incremental).
    full mode reviews everything that needs it (new+changed+stale)."""
    st = review_status(all_files, manifest)
    needs = st["new"] + st["changed"] + st["stale"]
    if mode == "full":
        return needs
    return needs[:REVIEW_BATCH]


def render_markdown(findings: list[Finding], mode: str, coverage: dict) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings = sorted(findings, key=lambda f: (order.get(f.severity, 9), f.path))
    removes = [f for f in findings if f.remove_candidate]
    total = coverage["total"]
    done = coverage["reviewed_up_to_date"]
    pct = (100.0 * done / total) if total else 0.0
    lines = [
        "# Code Conformance Audit — Findings (PROPOSE ONLY)",
        "",
        f"> Sweep: **{mode}** · {ts} · {len(findings)} files reviewed this run · "
        f"**{len(removes)} removal candidates**. Never edits or deletes — every action is "
        "human/Chairman-gated via `triage_findings.py` → E5 stories.",
        "",
        "## Review coverage (continuous loop state)",
        f"- **{done}/{total} files up-to-date reviewed ({pct:.1f}%)**",
        f"- pending new: {coverage['new']} · changed since review: {coverage['changed']} · "
        f"stale (>{STALE_DAYS}d): {coverage['stale']}",
        f"- backlog needing review: **{coverage['new'] + coverage['changed'] + coverage['stale']}** "
        f"(loop clears {REVIEW_BATCH}/run incremental)",
        "",
        "## Findings this run",
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
    lines += ["", f"_KEEP (no flags) this run: {sum(1 for f in findings if f.verdict=='KEEP')}._", ""]
    return "\n".join(lines)


def _coverage_counts(all_files, manifest) -> dict:
    st = review_status(all_files, manifest)
    return {"total": len(all_files), "reviewed_up_to_date": len(st["reviewed"]),
            "new": len(st["new"]), "changed": len(st["changed"]), "stale": len(st["stale"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    ap.add_argument("--backend", choices=["heuristic", "llm"], default="heuristic")
    ap.add_argument("--status", action="store_true",
                    help="print review coverage and exit (no review)")
    ap.add_argument("--force", action="store_true",
                    help="re-review every file, ignoring the manifest")
    args = ap.parse_args()

    all_files = iter_target_files()
    if not all_files:
        print("No files found to audit.", file=sys.stderr)
        return 1
    manifest = {} if args.force else load_manifest()

    if args.status:
        c = _coverage_counts(all_files, manifest)
        backlog = c["new"] + c["changed"] + c["stale"]
        print(f"Review coverage: {c['reviewed_up_to_date']}/{c['total']} up-to-date "
              f"({100.0*c['reviewed_up_to_date']/c['total']:.1f}%). "
              f"Backlog {backlog} (new {c['new']}, changed {c['changed']}, stale {c['stale']}).")
        return 0

    imported = build_imported_stems(all_files)
    test_corpus = build_test_corpus(all_files)
    targets = pick_targets(args.mode, all_files, manifest)
    reviewer = review_llm if args.backend == "llm" else review_heuristic

    now = datetime.now(timezone.utc).isoformat()
    findings = [reviewer(p, imported, test_corpus) for p in targets]

    # append to ledger
    LEDGER_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_JSONL.open("a") as fh:
        for f in findings:
            fh.write(json.dumps(asdict(f)) + "\n")

    # mark each reviewed file in the manifest (hash + ts + verdict)
    for p, f in zip(targets, findings):
        manifest[str(p.relative_to(HOME))] = {
            "hash": file_hash(p), "last_reviewed": now,
            "verdict": f.verdict, "severity": f.severity,
        }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=0, sort_keys=True))

    coverage = _coverage_counts(all_files, manifest)
    FINDINGS_MD.parent.mkdir(parents=True, exist_ok=True)
    FINDINGS_MD.write_text(render_markdown(findings, args.mode, coverage))
    STATE_PATH.write_text(json.dumps(
        {"last_run": now, "last_commit": current_commits()}, indent=2))

    removes = sum(1 for f in findings if f.remove_candidate)
    backlog = coverage["new"] + coverage["changed"] + coverage["stale"]
    print(f"Audit {args.mode}/{args.backend}: reviewed {len(findings)} this run, "
          f"{removes} removal candidates. Coverage "
          f"{coverage['reviewed_up_to_date']}/{coverage['total']} up-to-date; "
          f"backlog {backlog}. → {FINDINGS_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
