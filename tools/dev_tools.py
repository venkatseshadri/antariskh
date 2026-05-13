"""Dev Engineer tools — source code implementation.

The Dev Engineer receives CTO-approved change specs and implements them.
Deterministic, safe-by-default: previews all changes, commits atomically,
supports rollback. Only edits files within the project boundary.
"""

import difflib
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime as _dt

PROJECT_ROOT = Path(__file__).parent.parent

# Safety: Dev Engineer can ONLY modify files under PROJECT_ROOT
# and must never touch these protected paths
PROTECTED_PATHS = {
    "antariksh_rules.yaml",  # L3 immutable rules
    "config/event_calendar.json",  # manually curated
    ".planning/",  # GSD artifacts, not source
}


def _is_protected(filepath: str) -> bool:
    """Check if a file is protected from modification."""
    for p in PROTECTED_PATHS:
        if filepath == p or filepath.startswith(p):
            return True
    return False


def _resolve_path(filepath: str) -> Path:
    """Resolve relative path to absolute within project root."""
    p = Path(filepath)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def read_source(filepath: str) -> Dict:
    """Read a source file and return its contents.

    Args:
        filepath: Path relative to project root or absolute.

    Returns:
        {filepath, exists, size, lines, content (first 2000 chars), language}
    """
    full = _resolve_path(filepath)
    if not full.exists():
        return {"filepath": filepath, "exists": False, "error": "File not found"}

    content = full.read_text()
    lines = content.split("\n")
    ext = full.suffix

    lang_map = {
        ".py": "python",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".md": "markdown",
        ".sh": "bash",
        ".txt": "text",
    }

    return {
        "filepath": filepath,
        "exists": True,
        "size_bytes": len(content),
        "line_count": len(lines),
        "language": lang_map.get(ext, ext.lstrip(".")),
        "content": content[:2000],
        "content_truncated": len(content) > 2000,
        "first_10_lines": "\n".join(lines[:10]),
        "last_10_lines": "\n".join(lines[-10:]),
    }


def preview_edit(filepath: str, old_string: str, new_string: str) -> Dict:
    """Preview what a string replacement edit would look like without applying it.

    Returns:
        {filepath, match_found, match_count, diff_preview, will_modify_protected}
    """
    full = _resolve_path(filepath)
    if not full.exists():
        return {"filepath": filepath, "match_found": False, "error": "File not found"}

    if _is_protected(filepath):
        return {
            "filepath": filepath,
            "match_found": True,
            "match_count": 0,
            "diff_preview": "BLOCKED: Protected file",
            "will_modify_protected": True,
        }

    content = full.read_text()
    count = content.count(old_string)

    if count == 0:
        return {
            "filepath": filepath,
            "match_found": False,
            "match_count": 0,
            "diff_preview": f"String not found in {filepath}. First 80 chars: {old_string[:80]}...",
            "will_modify_protected": False,
        }

    new_content = content.replace(old_string, new_string)
    diff = "\n".join(
        difflib.unified_diff(
            content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{filepath}",
            tofile=f"b/{filepath}",
            n=2,
        )
    )

    return {
        "filepath": filepath,
        "match_found": True,
        "match_count": count,
        "diff_preview": diff[:1500] + ("\n... (truncated)" if len(diff) > 1500 else ""),
        "will_modify_protected": False,
        "lines_changed": len(diff.split("\n")),
    }


def apply_edit(
    filepath: str, old_string: str, new_string: str, reason: str = ""
) -> Dict:
    """Apply a string replacement edit to a source file. NOT reversible via undo-tool.

    Must pass preview_edit() first. Protected files are rejected.
    After applying, runs syntax check on .py files.

    Returns:
        {filepath, applied, match_count, error?, syntax_ok?}
    """
    full = _resolve_path(filepath)

    if _is_protected(filepath):
        return {
            "filepath": filepath,
            "applied": False,
            "error": "BLOCKED: Cannot modify protected file",
        }

    if not full.exists():
        return {
            "filepath": filepath,
            "applied": False,
            "error": "File not found",
        }

    content = full.read_text()
    count = content.count(old_string)

    if count == 0:
        return {
            "filepath": filepath,
            "applied": False,
            "error": f"Target string not found in {filepath}",
            "match_count": 0,
        }

    if count > 1:
        return {
            "filepath": filepath,
            "applied": False,
            "error": f"Ambiguous: found {count} matches. Provide more context to disambiguate.",
            "match_count": count,
        }

    new_content = content.replace(old_string, new_string, 1)
    full.write_text(new_content)

    # Syntax check for Python files
    syntax_ok = True
    syntax_error = None
    if full.suffix == ".py":
        try:
            subprocess.run(
                [
                    "python3",
                    "-c",
                    f"import py_compile; py_compile.compile('{full}', doraise=True)",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            syntax_ok = True
        except subprocess.CalledProcessError as e:
            syntax_ok = False
            syntax_error = e.stderr[:300] if e.stderr else str(e)
            full.write_text(content)  # ROLLBACK on syntax error
            return {
                "filepath": filepath,
                "applied": False,
                "rollback_applied": True,
                "error": f"Syntax error — rolled back. {syntax_error}",
                "syntax_ok": False,
            }

    return {
        "filepath": filepath,
        "applied": True,
        "match_count": 1,
        "reason": reason,
        "syntax_ok": syntax_ok,
        "new_size_bytes": len(new_content),
    }


def commit_change(change_id: str, files: List[str], message: str) -> Dict:
    """Stage and commit specified files with a structured commit message.

    Returns:
        {committed, hash, message, files_staged, error?}
    """
    try:
        for f in files:
            full = _resolve_path(f)
            if not full.exists():
                return {"committed": False, "error": f"File not found: {f}"}

        result = subprocess.run(
            ["git", "add"] + files,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            return {"committed": False, "error": f"git add failed: {result.stderr}"}

        full_msg = f"[{change_id}] {message}"
        result = subprocess.run(
            ["git", "commit", "-m", full_msg],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            return {"committed": False, "error": f"git commit failed: {result.stderr}"}

        hash_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(PROJECT_ROOT),
        )

        return {
            "committed": True,
            "hash": hash_result.stdout.strip()
            if hash_result.returncode == 0
            else "unknown",
            "message": full_msg,
            "files_staged": files,
            "change_id": change_id,
        }
    except Exception as e:
        return {"committed": False, "error": str(e)[:200]}


def rollback_change(change_id: Optional[str] = None) -> Dict:
    """Revert the most recent commit. If change_id is provided, only reverts if it matches.

    Returns:
        {rolled_back, previous_hash, new_hash, message}
    """
    try:
        # Check last commit message
        log = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(PROJECT_ROOT),
        )
        last_msg = log.stdout.strip()

        if change_id and change_id not in last_msg:
            return {
                "rolled_back": False,
                "error": f"Last commit ({last_msg[:60]}) does not match change_id={change_id}",
            }

        prev = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(PROJECT_ROOT),
        )
        prev_hash = prev.stdout.strip()

        result = subprocess.run(
            ["git", "revert", "--no-edit", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            return {
                "rolled_back": False,
                "error": f"git revert failed: {result.stderr}",
            }

        new = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(PROJECT_ROOT),
        )

        return {
            "rolled_back": True,
            "previous_hash": prev_hash,
            "new_hash": new.stdout.strip(),
            "message": f"Reverted: {last_msg[:100]}",
        }
    except Exception as e:
        return {"rolled_back": False, "error": str(e)[:200]}


def run_smoke_test(test_command: str) -> Dict:
    """Run a quick smoke test command. Returns pass/fail with output.

    Args:
        test_command: Shell command to execute (e.g., 'python3 -m pytest tests/test_scenarios.py::test_HP_01 -x')

    Returns:
        {passed, exit_code, stdout, stderr, duration_seconds}
    """
    try:
        start = _dt.now()
        result = subprocess.run(
            test_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
        )
        duration = (_dt.now() - start).total_seconds()
        return {
            "passed": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "(no output)",
            "stderr": result.stderr[-500:] if result.stderr else "",
            "duration_seconds": round(duration, 1),
        }
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": "TIMEOUT (60s)",
            "duration_seconds": 60.0,
        }
    except Exception as e:
        return {
            "passed": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)[:200],
            "duration_seconds": 0,
        }
