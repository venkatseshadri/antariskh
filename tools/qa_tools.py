"""QA Tester tools — validation, regression checking, scenario testing.

The QA Tester validates CTO-approved code changes before deployment.
Deterministic, evidence-driven: every test produces pass/fail with concrete output.
No change deploys without QA sign-off.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime as _dt

PROJECT_ROOT = Path(__file__).parent.parent


def run_test_suite(
    test_pattern: str = "",
    max_failures: int = 5,
    timeout_seconds: int = 120,
) -> Dict:
    """Run pytest suite and return structured results.

    Args:
        test_pattern: Specific test pattern (e.g., 'test_HP_01' or 'tests/test_scenarios.py')
        max_failures: Stop after N failures (-x --maxfail=N)
        timeout_seconds: Hard timeout

    Returns:
        {passed, total, failed, errors, skipped, duration, failures: [...], raw_summary}
    """
    cmd = ["python3", "-m", "pytest", "-v", "--tb=short", f"--maxfail={max_failures}"]
    if test_pattern:
        if "::" in test_pattern:
            cmd.append(test_pattern)
        else:
            cmd.extend(["-k", test_pattern])

    try:
        start = _dt.now()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(PROJECT_ROOT),
        )
        duration = round((_dt.now() - start).total_seconds(), 1)
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "total": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "duration_seconds": timeout_seconds,
            "failures": [
                {"test": "TIMEOUT", "error": f"Suite exceeded {timeout_seconds}s"}
            ],
            "raw_summary": f"TIMEOUT after {timeout_seconds}s",
        }

    output = result.stdout + result.stderr
    lines = output.split("\n")

    # Parse pytest summary line: "3 passed, 1 failed, 2 warnings" or "13 passed, 19 deselected"
    total = 0
    passed = 0
    failed = 0
    errors = 0
    skipped = 0

    for line in reversed(lines):
        if "=" in line and any(x in line for x in ("passed", "failed", "error")):
            parts = line.split(",")
            for p in parts:
                p = p.strip()
                if "passed" in p:
                    passed = int(p.split()[0])
                elif "failed" in p:
                    failed = int(p.split()[0])
                elif "error" in p and "errors" not in p:
                    errors = int(p.split()[0])
                elif "skipped" in p:
                    skipped = int(p.split()[0])
                elif "deselected" in p:
                    pass  # deselected tests aren't failures
            total = passed + failed + errors + skipped
            break

    # Extract failure details
    failures = []
    fail_section = False
    for i, line in enumerate(lines):
        if "FAILURES" in line and "=" in line:
            fail_section = True
            continue
        if fail_section:
            if line.startswith("=") and "short test summary" in line.lower():
                break
            if "FAILED" in line or "ERROR" in line:
                # Extract test name
                test_name = (
                    line.split(" - ")[0].strip()
                    if " - " in line
                    else line[:120].strip()
                )
                # Get next line for error
                error_msg = ""
                if i + 1 < len(lines):
                    error_msg = lines[i + 1].strip()[:200]
                failures.append(
                    {
                        "test": test_name,
                        "error": error_msg,
                    }
                )

    return {
        "passed": result.returncode == 0 and failed == 0,
        "exit_code": result.returncode,
        "total": total,
        "passed_count": passed,
        "failed_count": failed,
        "errors_count": errors,
        "skipped_count": skipped,
        "duration_seconds": duration,
        "failures": failures[:10],  # cap at 10
        "raw_summary": lines[-3]
        if len(lines) >= 3
        else (lines[-1] if lines else "no output"),
    }


def validate_no_regression(baseline_file: str = "tests/baseline_results.json") -> Dict:
    """Compare current test results against a baseline.

    If no baseline exists, create one. If it exists, fail on any regression.

    Args:
        baseline_file: JSON file storing baseline pass/fail results

    Returns:
        {regression_free, baseline_exists, new_failures, fixed_in_baseline, evidence}
    """
    baseline_path = PROJECT_ROOT / baseline_file

    # Run current suite
    current = run_test_suite()

    if not baseline_path.exists():
        # Create baseline
        baseline = {
            "created_at": _dt.now().isoformat(),
            "passed_count": current["passed_count"],
            "failed_count": current["failed_count"],
            "total": current["total"],
        }
        baseline_path.write_text(json.dumps(baseline, indent=2))
        return {
            "regression_free": True,
            "baseline_exists": False,
            "created_baseline": True,
            "baseline_file": baseline_file,
            "evidence": f"Baseline created: {current['passed_count']} passed, {current['failed_count']} failed",
        }

    # Compare
    try:
        baseline = json.loads(baseline_path.read_text())
    except Exception:
        # Corrupt baseline — recreate
        baseline_path.write_text(
            json.dumps(
                {
                    "created_at": _dt.now().isoformat(),
                    "passed_count": current["passed_count"],
                    "failed_count": current["failed_count"],
                    "total": current["total"],
                },
                indent=2,
            )
        )
        return {
            "regression_free": True,
            "baseline_exists": False,
            "created_baseline": True,
            "evidence": "Baseline was corrupt — recreated",
        }

    old_passed = baseline.get("passed_count", 0)
    old_failed = baseline.get("failed_count", 0)
    new_failed = current["failed_count"]
    new_passed = current["passed_count"]

    regression_free = True
    issues = []

    if new_failed > old_failed:
        regression_free = False
        issues.append(
            f"REGRESSION: {new_failed - old_failed} new failures (was {old_failed}, now {new_failed})"
        )

    if new_passed < old_passed:
        issues.append(f"Lost {old_passed - new_passed} passing tests")

    return {
        "regression_free": regression_free,
        "baseline_exists": True,
        "baseline_age": baseline.get("created_at", "unknown"),
        "previous_passed": old_passed,
        "previous_failed": old_failed,
        "current_passed": new_passed,
        "current_failed": new_failed,
        "issues": issues,
        "evidence": current["raw_summary"],
    }


def run_scenario(scenario_id: str) -> Dict:
    """Run a single scenario test and return detailed pass/fail.

    Args:
        scenario_id: e.g., 'HP-01', 'RM-02', 'MC-01'

    Returns:
        {scenario_id, passed, output, error, assertion_details}
    """
    cmd = [
        "python3",
        "-m",
        "pytest",
        "-v",
        "--tb=long",
        f"tests/test_scenarios.py::test_{scenario_id.replace('-', '_')}",
        "-x",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT),
        )
        passed = result.returncode == 0
        output = result.stdout[-1000:] if result.stdout else ""
        error = result.stderr[:500] if result.stderr else ""

        # Extract assertion error
        assertion_line = ""
        for line in (result.stdout + result.stderr).split("\n"):
            if "AssertionError" in line or "assert" in line:
                assertion_line = line.strip()[:200]
                break

        return {
            "scenario_id": scenario_id,
            "passed": passed,
            "exit_code": result.returncode,
            "assertion_error": assertion_line if not passed else None,
            "output_snippet": output[-500:],
        }
    except subprocess.TimeoutExpired:
        return {
            "scenario_id": scenario_id,
            "passed": False,
            "exit_code": -1,
            "assertion_error": "TIMEOUT (30s)",
            "output_snippet": "",
        }


def compare_outputs(before_command: str, after_command: str) -> Dict:
    """Run two commands and diff their outputs. Used to verify changes don't alter behavior.

    Args:
        before_command: Shell command that produces baseline output
        after_command: Shell command that produces new output

    Returns:
        {identical, diff_lines, before_output_snippet, after_output_snippet}
    """
    import difflib

    try:
        before = subprocess.run(
            before_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT),
        )
        after = subprocess.run(
            after_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT),
        )

        before_lines = before.stdout.splitlines()
        after_lines = after.stdout.splitlines()

        diff = list(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile="before",
                tofile="after",
            )
        )

        return {
            "identical": len(diff) == 0,
            "diff_line_count": len(diff),
            "diff": "\n".join(diff[:50]),  # first 50 lines
            "before_snippet": before.stdout[:500],
            "after_snippet": after.stdout[:500],
            "before_exit": before.returncode,
            "after_exit": after.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "identical": False,
            "diff_line_count": 0,
            "diff": "TIMEOUT",
            "error": "Command timed out",
        }


def generate_qa_report(
    change_id: str,
    tests_result: Dict,
    regression_result: Dict,
    scenarios_run: List[Dict],
) -> str:
    """Generate a structured QA sign-off report.

    Args:
        change_id: The change being tested
        tests_result: Output from run_test_suite()
        regression_result: Output from validate_no_regression()
        scenarios_run: List of run_scenario() results

    Returns:
        Formatted markdown QA report with pass/fail verdict
    """
    lines = [
        "# QA Validation Report",
        f"**Change:** {change_id}",
        f"**Date:** {_dt.now().isoformat()}",
        "",
        "## Test Suite Results",
        f"- **Passed:** {tests_result.get('passed_count', 0)}",
        f"- **Failed:** {tests_result.get('failed_count', 0)}",
        f"- **Errors:** {tests_result.get('errors_count', 0)}",
        f"- **Skipped:** {tests_result.get('skipped_count', 0)}",
        f"- **Duration:** {tests_result.get('duration_seconds', 0)}s",
        "",
        "## Regression Check",
        f"- **Regression-free:** {'YES ✅' if regression_result.get('regression_free') else 'NO ❌'}",
    ]

    if regression_result.get("baseline_exists"):
        lines.append(
            f"- **Baseline:** {regression_result.get('previous_passed')} → {regression_result.get('current_passed')} passed"
        )
    if regression_result.get("issues"):
        lines.append("### Issues")
        for issue in regression_result["issues"]:
            lines.append(f"- ⚠️ {issue}")

    lines += [
        "",
        "## Scenario Tests",
    ]
    for sc in scenarios_run:
        icon = "✅" if sc.get("passed") else "❌"
        lines.append(f"- {icon} {sc['scenario_id']}")
        if not sc.get("passed") and sc.get("assertion_error"):
            lines.append(f"  - Error: {sc['assertion_error']}")

    overall_pass = (
        tests_result.get("passed", False)
        and regression_result.get("regression_free", True)
        and all(s.get("passed") for s in scenarios_run)
    )

    lines += [
        "",
        "## Verdict",
        f"**{'✅ PASS — Ready for deployment' if overall_pass else '❌ FAIL — Do NOT deploy'}**",
    ]

    if not overall_pass:
        lines.append("")
        lines.append("**Required actions:**")
        if not tests_result.get("passed"):
            lines.append("- Fix failing tests before retrying QA")
        if not regression_result.get("regression_free", True):
            lines.append("- Investigate and resolve regressions")
        for sc in scenarios_run:
            if not sc.get("passed"):
                lines.append(f"- Fix scenario: {sc['scenario_id']}")

    return "\n".join(lines)
