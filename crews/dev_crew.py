"""Dev Engineer Crew — source code implementation.

Single agent implementing CTO-approved changes. Reads source, previews edits,
applies changes with auto-rollback on syntax error, commits atomically.

Reports to CTO. Never works on changes without CTO signoff.
"""

import os
import sys

from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config_loader import load_agent_config
from tools.dev_tools import (
    read_source as _read_source,
    preview_edit as _preview_edit,
    apply_edit as _apply_edit,
    commit_change as _commit_change,
    rollback_change as _rollback_change,
    run_smoke_test as _run_smoke_test,
)

DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
dev_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=DEEPSEEK_BASE,
    temperature=0.1,  # very low — implementation should be deterministic
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)


@tool
def read_source(filepath: str) -> dict:
    """Read a source file. Returns content, line count, language."""
    return _read_source(filepath)


@tool
def preview_edit(filepath: str, old_string: str, new_string: str) -> dict:
    """Preview what a string replacement will do. Shows unified diff."""
    return _preview_edit(filepath, old_string, new_string)


@tool
def apply_edit(
    filepath: str, old_string: str, new_string: str, reason: str = ""
) -> dict:
    """Apply a string replacement edit. Auto-rollback on syntax error."""
    return _apply_edit(filepath, old_string, new_string, reason)


@tool
def commit_change(change_id: str, files: list, message: str) -> dict:
    """Stage and commit files with structured message. Returns commit hash."""
    return _commit_change(change_id, files, message)


@tool
def rollback_change(change_id: str = None) -> dict:
    """Revert most recent commit. Must match change_id if provided."""
    return _rollback_change(change_id)


@tool
def run_smoke_test(test_command: str) -> dict:
    """Run a quick test. Returns pass/fail with output."""
    return _run_smoke_test(test_command)


dev_engineer = Agent(
    **load_agent_config("dev", "dev_engineer"),
    tools=[
        read_source,
        preview_edit,
        apply_edit,
        commit_change,
        rollback_change,
        run_smoke_test,
    ],
    allow_delegation=False,
    verbose=True,
)


implement_task = Task(
    description=(
        "Implement a CTO-approved change:\n"
        "1. Read the source files that need modification\n"
        "2. Preview every edit before applying\n"
        "3. Apply edits one at a time (old_string → new_string)\n"
        "4. If syntax error, read the rollback message and fix\n"
        "5. Run a smoke test (e.g., import the modified module)\n"
        "6. Commit with change_id in message\n\n"
        "Safety rules:\n"
        "- Never edit protected files (antariksh_rules.yaml, config/event_calendar.json)\n"
        "- Never edit files outside the project root\n"
        "- If preview shows multiple matches, provide more context\n"
        "- If apply_edit fails with syntax error, FIX the error — don't skip"
    ),
    expected_output="Commit hash with list of modified files and smoke test results",
    agent=dev_engineer,
)


def build_dev_crew() -> Crew:
    """Build Dev Engineer crew — single agent, direct implementation."""
    return Crew(
        agents=[dev_engineer],
        tasks=[implement_task],
        process=Process.sequential,
        verbose=True,
    )


if __name__ == "__main__":
    crew = build_dev_crew()
    print(f"Dev Crew: {len(crew.agents)} agents, {len(crew.tasks)} tasks")
