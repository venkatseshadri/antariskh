"""QA Tester Crew — validation and quality gates.

Single agent validating CTO-approved, Dev-implemented changes.
Runs test suites, checks for regressions, tests specific scenarios,
and produces signed QA reports. Nothing deploys without QA PASS.

Reports to CTO.
"""

import os
import sys

from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config_loader import load_agent_config
from tools.qa_tools import (
    run_test_suite as _run_test_suite,
    validate_no_regression as _validate_no_regression,
    run_scenario as _run_scenario,
    compare_outputs as _compare_outputs,
    generate_qa_report as _generate_qa_report,
)

DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
qa_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=DEEPSEEK_BASE,
    temperature=0.1,  # QA should be deterministic
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)


@tool
def run_test_suite(
    test_pattern: str = "", max_failures: int = 5, timeout_seconds: int = 120
) -> dict:
    """Run pytest with optional pattern filter. Returns structured pass/fail."""
    return _run_test_suite(test_pattern, max_failures, timeout_seconds)


@tool
def validate_no_regression(baseline_file: str = "tests/baseline_results.json") -> dict:
    """Compare current test results against baseline. Fails on regression."""
    return _validate_no_regression(baseline_file)


@tool
def run_scenario(scenario_id: str) -> dict:
    """Run a single scenario test (e.g., 'HP-01', 'RM-02'). Returns detailed result."""
    return _run_scenario(scenario_id)


@tool
def compare_outputs(before_command: str, after_command: str) -> dict:
    """Diff output of two commands to verify no behavioral change."""
    return _compare_outputs(before_command, after_command)


@tool
def generate_qa_report(
    change_id: str, tests_result: dict, regression_result: dict, scenarios_run: list
) -> str:
    """Generate structured QA report with PASS/FAIL verdict."""
    return _generate_qa_report(
        change_id, tests_result, regression_result, scenarios_run
    )


qa_tester = Agent(
    **load_agent_config("qa", "qa_tester"),
    tools=[
        run_test_suite,
        validate_no_regression,
        run_scenario,
        compare_outputs,
        generate_qa_report,
    ],
    allow_delegation=False,
    verbose=True,
)


validate_task = Task(
    description=(
        "Validate a CTO-approved, Dev-implemented change:\n"
        "1. Run the full test suite — any failures are blocking\n"
        "2. Check for regressions against baseline\n"
        "3. Run the specific scenarios the change affects\n"
        "4. If applicable, diff before/after output of key functions\n"
        "5. Generate signed QA report with PASS/FAIL verdict\n\n"
        "Rules:\n"
        "- FAIL if ANY test fails (even previously failing)\n"
        "- FAIL if regression check shows new failures\n"
        "- FAIL if any scenario in the test_plan is broken\n"
        "- Include concrete evidence in the report (test names, error messages)"
    ),
    expected_output="QA report with PASS/FAIL verdict and concrete evidence",
    agent=qa_tester,
)


def build_qa_crew() -> Crew:
    """Build QA Tester crew — single agent, direct validation."""
    return Crew(
        agents=[qa_tester],
        tasks=[validate_task],
        process=Process.sequential,
        verbose=True,
    )


if __name__ == "__main__":
    crew = build_qa_crew()
    print(f"QA Crew: {len(crew.agents)} agents, {len(crew.tasks)} tasks")
