#!/usr/bin/env python3
"""Auto-update CONTEXT.md from current project state.

Run at end of every session. Reads git log, file sizes, test results,
and rewrites CONTEXT.md with fresh data. Keeps the "read on demand"
section with file links — heavy detail stays in ARCHITECTURE.md etc.

Usage:
    python3 tools/update_context.py
    python3 tools/update_context.py --last-task "Wired broker execution API"
    python3 tools/update_context.py --priority "Phase A: broker WS feed"
"""

import os, sys, subprocess, json
from pathlib import Path
from datetime import datetime

PROJECT = Path("/home/trading_ceo/antariksh")
CONTEXT = PROJECT / "CONTEXT.md"


def run(cmd):
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=str(PROJECT)
    ).stdout.strip()


def get_last_commits(n=3):
    return run(f"git log --oneline -{n}")


def get_branch():
    return run("git rev-parse --abbrev-ref HEAD")


def get_file_stats(files):
    lines = []
    for f in files:
        p = PROJECT / f
        if p.exists():
            n = len(p.read_text().splitlines())
            lines.append(f"  `{f}` ({n} lines)")
    return "\n".join(lines)


def get_test_summary():
    """Run integration test quickly, capture result."""
    try:
        out = run("python3 tests/test_integration_end_to_end.py 2>&1")
        for line in out.splitlines():
            if "PASSED" in line and "FAILED" in line:
                return line.strip()
    except:
        pass
    return "Tests: run manually (`python3 tests/test_integration_end_to_end.py`)"


def get_live_data():
    """Quick DuckDB check."""
    try:
        import os as _os

        _os.environ.pop("ANTARIKSH_MOCK_MODE", None)
        sys.path.insert(0, str(PROJECT))
        from trading_desk import engine_scout_regime

        r = engine_scout_regime()
        return f"VIX={r.vix}, NIFTY={r.nifty_spot}, Regime={r.regime}"
    except:
        return "DuckDB: check manually"


def build_context(last_task=None, priority=None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    commits = get_last_commits(5)
    branch = get_branch()
    key_files = get_file_stats(
        [
            "trading_desk.py",
            "tests/test_integration_end_to_end.py",
            "ARCHITECTURE.md",
            "GAPS_AND_ROADMAP.md",
            "TRADING_DESK_VALIDATION.md",
            "crews/ta_crew.py",
            "crews/pm_crew.py",
            "tools/risk_tools.py",
            "tools/execution_tools.py",
            "tools/contract_tools.py",
        ]
    )
    tests = get_test_summary()
    live = get_live_data()

    last_task_line = f"## Last Built\n{last_task}\n\n" if last_task else ""
    priority_line = f"## Priority Queue\n{priority}\n\n" if priority else ""

    content = f"""# SESSION CONTEXT — Updated {now}

Project: Antariksh — CrewAI options trading desk (NIFTY Iron Butterfly)
Branch: `{branch}` | Live data: {live}

## Locations
```
/home/trading_ceo/antariksh/              ← Antariksh
/home/trading_ceo/python-trader/varaha/   ← Varaha (DuckDB capture)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/  ← Shoonya API
```
GitHub: `github.com/venkatseshadri/antariskh`

{last_task_line}{priority_line}## What's Where (read on demand)
{key_files}

## Verify State
```bash
cd {PROJECT}
git log --oneline -3
python3 tests/test_integration_end_to_end.py   # integration suite
python3 trading_desk.py --test-triggers        # 4 trigger tests
python3 -c "import os; os.environ.pop('ANTARIKSH_MOCK_MODE',''); from trading_desk import engine_scout_regime; r=engine_scout_regime(); print(f'Live: VIX={{r.vix}} Regime={{r.regime}}')"
```

## Recent Commits
```
{commits}
```
"""
    return content


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Auto-update CONTEXT.md")
    p.add_argument(
        "--last-task", type=str, help="One-line description of last thing built"
    )
    p.add_argument("--priority", type=str, help="Current priority task")
    args = p.parse_args()

    content = build_context(last_task=args.last_task, priority=args.priority)
    CONTEXT.write_text(content)
    print(f"CONTEXT.md updated ({len(content.splitlines())} lines)")
    print("Last task:", args.last_task or "(none)")
    print("Priority:", args.priority or "(none)")
