"""CTO-Dev-QA Pipeline — orchestrated change management.

Single hierarchical crew: CTO is manager, Dev Engineer and QA Tester are workers.
Flow: Change Request → CTO evaluates risk → delegates to Dev → delegates to QA → final signoff.

Also provides a deterministic `process_change_request()` for programmatic use.
"""

import json
import os
import sys
from datetime import datetime as _dt
from pathlib import Path
from typing import Dict, List, Optional

from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PROJECT_ROOT = Path(__file__).parent

from config_loader import load_agent_config

DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
manager_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=DEEPSEEK_BASE,
    temperature=0.2,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)

# ============================================================
# Deterministic pipeline functions (no LLM needed)
# ============================================================


def process_change_request(change_spec: Dict) -> Dict:
    """Deterministic pipeline: evaluate → implement → validate → signoff.

    This is the PAUL Apply step: Plan's change spec gets applied through
    CTO risk assessment, Dev implementation, and QA validation — all without
    requiring LLM for the deterministic steps. Only Q3-Q4 (judgment calls)
    use LLM delegates.

    Args:
        change_spec: Dict with change_id, title, requester, files_to_modify,
                     specific_edit, rollback_plan, test_plan

    Returns:
        {change_id, status: APPROVED|REJECTED|DEPLOYED|FAILED_QA,
         steps: [{step, status, details}], final_report}
    """
    from tools.cto_tools import (
        validate_change_spec,
        assess_change_risk,
        cto_signoff,
        generate_cto_brief,
    )
    from tools.dev_tools import preview_edit, apply_edit, commit_change, read_source
    from tools.qa_tools import (
        run_test_suite,
        validate_no_regression,
        run_scenario,
        generate_qa_report,
    )

    steps = []
    cid = change_spec.get("change_id", "UNKNOWN")

    # ── Step 1: Validate change spec ──
    validation = validate_change_spec(change_spec)
    steps.append(
        {
            "step": "validate_spec",
            "status": "PASS" if validation["valid"] else "FAIL",
            "details": validation,
        }
    )
    if not validation["valid"]:
        return {
            "change_id": cid,
            "status": "REJECTED",
            "reason": validation["reason"],
            "steps": steps,
        }

    # ── Step 2: CTO Risk Assessment ──
    risk = assess_change_risk(change_spec)
    steps.append({"step": "assess_risk", "status": "PASS", "details": risk})

    # ── Step 3: Preview diffs ──
    from tools.cto_tools import preview_diff

    diffs = preview_diff(change_spec)
    steps.append({"step": "preview_diff", "status": "PASS", "details": diffs})

    # ── Step 4: CTO Signoff ──
    signoff = cto_signoff(change_spec, risk)
    steps.append(
        {"step": "cto_signoff", "status": signoff["decision"], "details": signoff}
    )

    if signoff["decision"] != "YES":
        brief = generate_cto_brief(change_spec, risk, signoff)
        return {
            "change_id": cid,
            "status": "REJECTED"
            if signoff["decision"] == "NO"
            else "NEEDS_CLARIFICATION",
            "reason": signoff["reason"],
            "cto_brief": brief,
            "steps": steps,
        }

    # ── Step 5: Dev Implementation ──
    applied_files = []
    for f in change_spec.get("files_to_modify", []):
        old_str = change_spec.get("old_string")  # exact string to replace
        new_str = change_spec.get("new_string")  # replacement
        if not old_str or not new_str:
            steps.append(
                {
                    "step": "dev_implement",
                    "status": "SKIP",
                    "details": f"No old/new strings for {f} — requires manual edit",
                }
            )
            continue

        # Preview first
        preview = preview_edit(f, old_str, new_str)
        if not preview["match_found"]:
            steps.append(
                {
                    "step": "dev_implement",
                    "status": "FAIL",
                    "details": f"String not found in {f}: {old_str[:80]}...",
                }
            )
            return {
                "change_id": cid,
                "status": "FAILED_DEV",
                "reason": f"Edit not applicable to {f}",
                "steps": steps,
            }

        if preview.get("will_modify_protected"):
            steps.append(
                {
                    "step": "dev_implement",
                    "status": "BLOCKED",
                    "details": f"{f} is PROTECTED — cannot modify",
                }
            )
            return {
                "change_id": cid,
                "status": "REJECTED",
                "reason": f"Protected file: {f}",
                "steps": steps,
            }

        # Apply
        result = apply_edit(
            f, old_str, new_str, reason=f"{cid}: {change_spec.get('title', '')}"
        )
        applied_files.append(f)
        steps.append(
            {
                "step": f"dev_edit_{Path(f).name}",
                "status": "PASS" if result["applied"] else "FAIL",
                "details": result,
            }
        )
        if not result["applied"]:
            return {
                "change_id": cid,
                "status": "FAILED_DEV",
                "reason": result.get("error", "Edit failed"),
                "steps": steps,
            }

    # Commit
    if applied_files:
        commit_result = commit_change(
            cid, applied_files, f"{cid}: {change_spec.get('title', 'no title')}"
        )
        steps.append(
            {
                "step": "dev_commit",
                "status": "PASS" if commit_result["committed"] else "FAIL",
                "details": commit_result,
            }
        )
        if not commit_result["committed"]:
            return {
                "change_id": cid,
                "status": "FAILED_DEV",
                "reason": commit_result.get("error", "Commit failed"),
                "steps": steps,
            }
    else:
        steps.append(
            {"step": "dev_commit", "status": "SKIP", "details": "No files modified"}
        )

    # ── Step 6: QA Validation ──
    test_pattern = change_spec.get("test_pattern", "")
    suite_result = run_test_suite(test_pattern)
    steps.append(
        {
            "step": "qa_test_suite",
            "status": "PASS" if suite_result["passed"] else "FAIL",
            "details": suite_result,
        }
    )

    regression = validate_no_regression()
    steps.append(
        {
            "step": "qa_regression",
            "status": "PASS" if regression["regression_free"] else "FAIL",
            "details": regression,
        }
    )

    # Run specified scenarios
    scenarios = change_spec.get("test_scenarios", [])
    scenario_results = []
    for sc in scenarios:
        sr = run_scenario(sc)
        scenario_results.append(sr)
        steps.append(
            {
                "step": f"qa_scenario_{sc}",
                "status": "PASS" if sr["passed"] else "FAIL",
                "details": sr,
            }
        )

    # Generate QA report
    report = generate_qa_report(cid, suite_result, regression, scenario_results)
    overall_pass = (
        suite_result["passed"]
        and regression["regression_free"]
        and all(s["passed"] for s in scenario_results)
    )

    steps.append(
        {
            "step": "qa_report",
            "status": "PASS" if overall_pass else "FAIL",
            "details": report[:500],
        }
    )

    if not overall_pass:
        return {
            "change_id": cid,
            "status": "FAILED_QA",
            "qa_report": report,
            "steps": steps,
        }

    # ── Step 7: Final Signoff ──
    return {
        "change_id": cid,
        "status": "DEPLOYED",
        "qa_report": report,
        "commit_hash": commit_result.get("hash", "unknown")
        if "commit_result" in dir()
        else "no_commit",
        "steps": steps,
    }


# ============================================================
# CTO Pipeline Crew (hierarchical — CTO manages Dev + QA)
# ============================================================

from tools.cto_tools import (
    assess_change_risk,
    preview_diff,
    cto_signoff,
    validate_change_spec,
    scout_technology,
    evaluate_architecture,
    design_poc_plan,
    generate_cto_brief,
)
from tools.dev_tools import (
    read_source,
    preview_edit,
    apply_edit,
    commit_change,
    rollback_change,
    run_smoke_test,
)
from tools.qa_tools import (
    run_test_suite,
    validate_no_regression,
    run_scenario,
    compare_outputs,
    generate_qa_report,
)

from crewai.tools import tool as crew_tool


# CTO tools
@crew_tool
def cto_assess_risk(change_spec: dict) -> dict:
    """[CTO] Evaluate blast radius and risk of a code change."""
    return assess_change_risk(change_spec)


@crew_tool
def cto_preview_diff(change_spec: dict) -> dict:
    """[CTO] Preview what the diff will look like."""
    return preview_diff(change_spec)


@crew_tool
def cto_signoff_tool(
    change_spec: dict, risk_assessment: dict, override: str = None
) -> dict:
    """[CTO] Approve or reject a change. Delegates to Dev if YES."""
    return cto_signoff(change_spec, risk_assessment, override)


@crew_tool
def cto_validate_spec(change_spec: dict) -> dict:
    """[CTO] Check change request validity."""
    return validate_change_spec(change_spec)


@crew_tool
def cto_scout(category: str) -> dict:
    """[CTO] Research cheaper/better tools."""
    return scout_technology(category)


@crew_tool
def cto_evaluate_arch(component: str = "all") -> dict:
    """[CTO] Evaluate architecture improvements."""
    return evaluate_architecture(component)


@crew_tool
def cto_poc_plan(vision: str) -> dict:
    """[CTO] Design POC for CEO vision."""
    return design_poc_plan(vision)


# Dev tools
@crew_tool
def dev_read_source(filepath: str) -> dict:
    """[Dev] Read a source file."""
    return read_source(filepath)


@crew_tool
def dev_preview_edit(filepath: str, old_string: str, new_string: str) -> dict:
    """[Dev] Preview an edit before applying."""
    return preview_edit(filepath, old_string, new_string)


@crew_tool
def dev_apply_edit(
    filepath: str, old_string: str, new_string: str, reason: str = ""
) -> dict:
    """[Dev] Apply edit. Auto-rollback on syntax error."""
    return apply_edit(filepath, old_string, new_string, reason)


@crew_tool
def dev_commit(change_id: str, files: list, message: str) -> dict:
    """[Dev] Commit changes atomically."""
    return commit_change(change_id, files, message)


@crew_tool
def dev_rollback(change_id: str = None) -> dict:
    """[Dev] Rollback last commit."""
    return rollback_change(change_id)


@crew_tool
def dev_smoke_test(command: str) -> dict:
    """[Dev] Run a quick smoke test."""
    return run_smoke_test(command)


# QA tools
@crew_tool
def qa_run_suite(pattern: str = "") -> dict:
    """[QA] Run pytest suite."""
    return run_test_suite(pattern)


@crew_tool
def qa_regression_check() -> dict:
    """[QA] Check for regressions vs baseline."""
    return validate_no_regression()


@crew_tool
def qa_run_scenario(scenario_id: str) -> dict:
    """[QA] Run a single scenario test."""
    return run_scenario(scenario_id)


@crew_tool
def qa_diff_outputs(before_cmd: str, after_cmd: str) -> dict:
    """[QA] Diff outputs of two commands."""
    return compare_outputs(before_cmd, after_cmd)


@crew_tool
def qa_generate_report(
    change_id: str, tests: dict, regression: dict, scenarios: list
) -> str:
    """[QA] Generate signed QA report."""
    return generate_qa_report(change_id, tests, regression, scenarios)


# ============================================================
# Agents
# ============================================================

cto_agent = Agent(
    **load_agent_config("cto", "cto"),
    tools=[
        cto_assess_risk,
        cto_preview_diff,
        cto_signoff_tool,
        cto_validate_spec,
        cto_scout,
        cto_evaluate_arch,
        cto_poc_plan,
    ],
    allow_delegation=True,
    verbose=True,
)

dev_agent = Agent(
    **load_agent_config("dev", "dev_engineer"),
    tools=[
        dev_read_source,
        dev_preview_edit,
        dev_apply_edit,
        dev_commit,
        dev_rollback,
        dev_smoke_test,
    ],
    allow_delegation=False,
    verbose=True,
)

qa_agent = Agent(
    **load_agent_config("qa", "qa_tester"),
    tools=[
        qa_run_suite,
        qa_regression_check,
        qa_run_scenario,
        qa_diff_outputs,
        qa_generate_report,
    ],
    allow_delegation=False,
    verbose=True,
)


# ============================================================
# Tasks
# ============================================================

gatekeeping_task = Task(
    description=(
        "A change request has arrived. Process it:\n"
        "1. Validate the change spec\n"
        "2. Assess risk (blast radius, critical files, dependencies)\n"
        "3. Preview the diff\n"
        "4. Make a decision: YES (delegate to Dev+QA), NO, or NEEDS_CLARIFICATION\n"
        "5. If YES: tell Dev Engineer to implement the changes\n"
        "6. After Dev commits: tell QA Tester to validate\n"
        "7. If QA passes: final signoff. If QA fails: tell Dev to fix and retry.\n\n"
        "The change spec is in the task context."
    ),
    expected_output="Full audit trail: risk assessment, Dev commits, QA report, final signoff",
    agent=cto_agent,
)


# ============================================================
# Crew Builder
# ============================================================


def build_pipeline_crew() -> Crew:
    """Build the full CTO→Dev→QA pipeline crew.

    Hierarchical: CTO is manager, Dev and QA are worker agents.
    CTO receives the change request, evaluates, then delegates
    implementation to Dev and validation to QA in sequence.
    """
    return Crew(
        agents=[cto_agent, dev_agent, qa_agent],
        tasks=[gatekeeping_task],
        process=Process.hierarchical,
        manager_llm=manager_llm,
        verbose=True,
    )


if __name__ == "__main__":
    crew = build_pipeline_crew()
    print(
        f"Pipeline Crew: {len(crew.agents)} agents (CTO manager + Dev + QA), "
        f"{len(crew.tasks)} tasks, process={crew.process}"
    )
