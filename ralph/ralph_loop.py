#!/usr/bin/env python3
"""
Ralph Loop — Autonomous verify-retry meta-layer for Antariksh.
Wraps CrewAI agents in PRD-driven verification loops with scheduled execution.

Origin: Geoffrey Huntley, Vercel Labs — "Ralph is a Bash loop."
Core pattern: while not done: run → verify → feedback → repeat

Antariksh Integration:
    Ralph Loop = Strategic oversight meta-layer
    CrewAI    = Tactical execution layer

Usage:
    python -m ralph.ralph_loop          # Run once (current cycle)
    crontab antariksh/crontab          # For ongoing scheduling
"""

from dataclasses import dataclass, field
from typing import Callable, Any, Optional, List, Dict, Tuple
from datetime import datetime
import logging
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "python-trader"))

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

try:
    from croniter import croniter

    _CRONITER_AVAILABLE = True
except ImportError:
    _CRONITER_AVAILABLE = False

logger = logging.getLogger("Antariksh-RalphLoop")

# ============================================================
# 1. VerificationResult
# ============================================================


@dataclass
class VerificationResult:
    """Result of verifying an agent's output against completion criteria."""

    complete: bool
    reason: str = ""


# ============================================================
# 2. RalphLoop — Generic Verify-Retry Loop
# ============================================================


class RalphLoop:
    """
    Generic Ralph Loop — wraps any agent function in verify-retry logic.

    Each iteration:
        1. Run agent_fn on the prompt
        2. Call verify_fn on the result
        3. If complete -> return success
        4. If not -> inject feedback into prompt and retry
        5. Exit after max_iterations regardless
    """

    def __init__(
        self,
        agent_fn: Callable[[str], Any],
        verify_fn: Callable[[Any], VerificationResult],
        max_iterations: int = 10,
        on_iteration_start: Optional[Callable[[int], None]] = None,
        on_iteration_end: Optional[Callable[[int, VerificationResult], None]] = None,
    ):
        self.agent_fn = agent_fn
        self.verify_fn = verify_fn
        self.max_iterations = max_iterations
        self.on_iteration_start = on_iteration_start
        self.on_iteration_end = on_iteration_end

    def run(self, prompt: str) -> dict:
        """
        Run the verify-retry loop until verified or max_iterations reached.

        Args:
            prompt: The task description for the agent.

        Returns:
            {
                "result": final agent output,
                "iterations": N,
                "completion_reason": "verified" | "max_iterations",
                "reason": explanation string,
                "all_results": [result from each iteration],
            }
        """
        all_results: List[Any] = []
        current_prompt = prompt
        final_result = None

        for i in range(self.max_iterations):
            iteration_num = i + 1

            if self.on_iteration_start:
                self.on_iteration_start(iteration_num)

            final_result = self.agent_fn(current_prompt)
            all_results.append(final_result)

            verified = self.verify_fn(final_result)

            if self.on_iteration_end:
                self.on_iteration_end(iteration_num, verified)

            if verified.complete:
                logger.info(f"RalphLoop: verified after {iteration_num} iteration(s)")
                return {
                    "result": final_result,
                    "iterations": iteration_num,
                    "completion_reason": "verified",
                    "reason": verified.reason,
                    "all_results": all_results,
                }

            current_prompt += (
                f"\n\n[ITERATION {iteration_num} FEEDBACK]: {verified.reason}\n"
                f"Please address this and try again."
            )
            logger.warning(
                f"RalphLoop: iteration {iteration_num} failed — {verified.reason}"
            )

        logger.error(
            f"RalphLoop: failed to verify after {self.max_iterations} iterations"
        )
        return {
            "result": final_result,
            "iterations": self.max_iterations,
            "completion_reason": "max_iterations",
            "reason": f"Failed to verify after {self.max_iterations} iterations",
            "all_results": all_results,
        }


# ============================================================
# 3. CrewAIRalphLoop — Wraps a CrewAI Crew
# ============================================================


class CrewAIRalphLoop(RalphLoop):
    """
    Ralph Loop specialized for CrewAI — wraps crew.kickoff() as the agent function.

    Each iteration calls crew.kickoff() with the (possibly augmented) prompt,
    sets the first task's description to the current prompt string.
    """

    def __init__(
        self,
        crew,  # crewai.Crew (not imported at module level to avoid import-time LLM connections)
        verify_fn: Callable[[str], VerificationResult],
        max_iterations: int = 10,
        **kwargs,
    ):
        def crew_agent(prompt: str) -> str:
            if crew.tasks:
                crew.tasks[0].description = prompt
            result = crew.kickoff()
            return str(result)

        super().__init__(
            agent_fn=crew_agent,
            verify_fn=verify_fn,
            max_iterations=max_iterations,
            **kwargs,
        )


# ============================================================
# 4. RolePRD — Role Performance Requirements Document
# ============================================================


def _parse_metric_value(raw: Any) -> Any:
    """Parse metric values from YAML strings into float, bool, or percentage.

    Handles:
        - Numeric: 0.60, 3500 → float
        - Currency: '₹3,00,000' → 300000.0
        - Percentage: '100%', '99%' → 100.0, 99.0
        - With operator: '≤80%', '≥1.5', '≤₹15,000' → 80.0, 1.5, 15000.0
        - Boolean: 'True', 'False' → python True, False
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip()

    # Boolean
    if s.lower() in ("true", "false"):
        return s.lower() == "true"

    # Strip comparison operators from the beginning
    operators = ["≤", "≥", "<", ">"]
    for op in operators:
        if s.startswith(op):
            s = s[len(op) :]
            break

    # Strip currency symbols, commas, and trailing %
    s = s.replace("₹", "").replace(",", "")
    s = s.removesuffix("%")

    # If the string still has text after the number, extract leading float
    # e.g., "2 profit per 100 deployed" → 2.0
    try:
        return float(s)
    except ValueError:
        import re

        match = re.match(r"([\d.]+)", s)
        if match:
            return float(match.group(1))
        # Qualitative target — return as string for manual evaluation
        return str(raw).strip()

    return float(s)


@dataclass
class RolePRD:
    """
    A Role's Performance Requirements Document — measurable goals with
    target, floor, and minimum sample thresholds.

    Attributes:
        name: Role name.
        mission: Role mission statement.
        metrics: List of metric dicts, each with:
            name, target (float), floor (float), min_samples (int),
            and optional before_min (str, default "TRACKING").
        authority_can: Actions this role can take.
        authority_cannot: Actions this role cannot take.
    """

    name: str
    mission: str
    metrics: List[Dict]
    authority_can: List[str] = field(default_factory=list)
    authority_cannot: List[str] = field(default_factory=list)

    def check_metric(self, name: str, actual: float, samples: int) -> Tuple[str, str]:
        """
        Check one metric against its PRD thresholds.

        Args:
            name: Metric name (must match a PRD metric).
            actual: Current measured value.
            samples: Number of data points collected.

        Returns:
            (status, reason) where status is one of:
                "PASS"          — actual >= target
                "WARNING"       — floor <= actual < target
                "FAIL"          — actual < floor
                "DATA_IMMATURE" — samples < min_samples
        """
        metric = None
        for m in self.metrics:
            if m.get("name") == name:
                metric = m
                break
        if metric is None:
            return ("PASS", f"Unknown metric '{name}' — no PRD entry")

        target = metric.get("target", 0.0)
        floor = metric.get("floor", 0.0)
        min_samples = metric.get("min_samples", 1)
        before_min = metric.get("before_min", "TRACKING")

        if samples < min_samples:
            return ("DATA_IMMATURE", before_min)

        if actual >= target:
            return ("PASS", f"{name}: {actual} >= target {target}")

        if actual >= floor:
            return ("WARNING", f"{name}: {actual} below target {target}, floor {floor}")

        return ("FAIL", f"{name}: {actual} < floor {floor} (target {target})")


# ============================================================
# 5. PRDRalphLoop — PRD-Driven Ralph Loop
# ============================================================


class PRDRalphLoop(RalphLoop):
    """
    Ralph Loop that evaluates an agent's PRD after each run.

    The verify_fn:
        1. Calls metric_evaluator on agent output to get current metric values.
        2. Calls sample_counter (if provided) to get sample counts.
        3. For each metric in the PRD, calls prd.check_metric().
        4. Returns VerificationResult with status and feedback.
    """

    def __init__(
        self,
        agent_fn: Callable[[str], Any],
        prd: RolePRD,
        metric_evaluator: Callable[[Any], Dict[str, float]],
        max_iterations: int = 5,
        sample_counter: Optional[Callable[[Any], Dict[str, int]]] = None,
        **kwargs,
    ):
        self.prd = prd
        self.metric_evaluator = metric_evaluator
        self.sample_counter = sample_counter

        def verify_fn(output: Any) -> VerificationResult:
            current_metrics = metric_evaluator(output)

            sample_counts: Dict[str, int] = {}
            if sample_counter is not None:
                sample_counts = sample_counter(output)
            else:
                for m in prd.metrics:
                    name = m.get("name", "")
                    sample_counts[name] = m.get("min_samples", 999999)

            failures: List[str] = []
            warnings: List[str] = []
            tracking: List[str] = []

            for metric_def in prd.metrics:
                name = metric_def.get("name", "")
                actual = current_metrics.get(name, 0.0)
                samples = sample_counts.get(name, metric_def.get("min_samples", 1))

                status, reason = prd.check_metric(name, actual, samples)

                if status == "FAIL":
                    failures.append(reason)
                elif status == "WARNING":
                    warnings.append(reason)
                elif status == "DATA_IMMATURE":
                    tracking.append(reason)

            if failures:
                return VerificationResult(
                    complete=False,
                    reason=(
                        f"PRD for {prd.name} violated: {'; '.join(failures)}"
                        + (f" | Warnings: {'; '.join(warnings)}" if warnings else "")
                        + (f" | Tracking: {'; '.join(tracking)}" if tracking else "")
                    ),
                )

            feedback_parts: List[str] = []
            if warnings:
                feedback_parts.append(f"Below target: {'; '.join(warnings)}")
            if tracking:
                feedback_parts.append(f"Data immature: {'; '.join(tracking)}")

            return VerificationResult(
                complete=True,
                reason=(
                    "; ".join(feedback_parts)
                    if feedback_parts
                    else f"All {prd.name} PRD metrics met"
                ),
            )

        super().__init__(
            agent_fn=agent_fn,
            verify_fn=verify_fn,
            max_iterations=max_iterations,
            **kwargs,
        )


# ============================================================
# 6. RalphScheduler — Schedule-Based PRD Loop Runner
# ============================================================


class RalphScheduler:
    """
    Schedules multiple PRD-driven Ralph Loops.

    Each role is a (PRDRalphLoop, schedule_string) pair. On run_due_roles(),
    only the roles whose schedule matches the current time are executed.

    schedule_string formats supported:
        - Cron expression (5 fields: minute hour day month weekday) if croniter installed
        - Simple "HH:MM" format (24-hour) — matches within ±2 minutes of current time
    """

    _CRON_RE = re.compile(r"^\S+\s+\S+\s+\S+\s+\S+\s+\S+$")
    _TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")

    def __init__(self, roles: List[Tuple[PRDRalphLoop, str]]):
        self.roles = roles

    def run_due_roles(self) -> List[Dict]:
        """
        Run all roles whose schedule matches the current time.

        Returns:
            List of result dicts from each executed role.
        """
        results: List[Dict] = []
        now = datetime.now()

        for loop, schedule_str in self.roles:
            if self._schedule_matches(schedule_str, now):
                role_name = loop.prd.name
                logger.info(f"[{now}] Running scheduled PRD check for {role_name}")
                try:
                    result = loop.run(
                        f"Execute your mission as {role_name}. "
                        f"Mission: {loop.prd.mission}. Review your PRD metrics."
                    )
                    result["role"] = role_name
                    result["schedule"] = schedule_str
                    result["run_at"] = now.isoformat()
                    results.append(result)
                    logger.info(
                        f"[{now}] {role_name}: {result['completion_reason']} "
                        f"in {result['iterations']} iteration(s)"
                    )
                except Exception as e:
                    logger.error(f"[{now}] {role_name} failed: {e}", exc_info=True)
                    results.append(
                        {
                            "role": role_name,
                            "error": str(e),
                            "run_at": now.isoformat(),
                        }
                    )

        if not results:
            logger.info(f"[{now}] No roles due at this time")

        return results

    def _schedule_matches(self, schedule_str: str, now: datetime) -> bool:
        """
        Check if a schedule string matches the current time.

        Tries croniter first, falls back to simple HH:MM matching.
        """
        if _CRONITER_AVAILABLE and self._CRON_RE.match(schedule_str):
            try:
                cron = croniter(schedule_str, now)
                prev_time = cron.get_prev(datetime)
                return prev_time == cron.get_current(datetime)
            except (ValueError, KeyError):
                pass

        return self._simple_time_match(schedule_str, now)

    @staticmethod
    def _simple_time_match(
        schedule_str: str, now: datetime, window_minutes: int = 2
    ) -> bool:
        """
        Simple time-window match for 'HH:MM' format strings.

        Returns True if current time is within ±window_minutes of the scheduled time.
        Handles midnight wrapping (e.g. 23:58 matches schedule 00:00).
        """
        m = RalphScheduler._TIME_RE.match(schedule_str)
        if not m:
            logger.warning(f"Unrecognized schedule format: '{schedule_str}'")
            return False

        schedule_hour = int(m.group(1))
        schedule_minute = int(m.group(2))

        schedule_mins = schedule_hour * 60 + schedule_minute
        now_mins = now.hour * 60 + now.minute + now.second / 60.0

        raw_diff = abs(now_mins - schedule_mins)
        wrapped_diff = 1440.0 - raw_diff
        diff = min(raw_diff, wrapped_diff)

        return diff <= window_minutes


# ============================================================
# 7. load_prd_yaml — Load PRD from YAML File
# ============================================================


def load_prd_yaml(path: str) -> RolePRD:
    """
    Load a RolePRD definition from a YAML file.

    Args:
        path: Path to the YAML file.

    Returns:
        RolePRD object with parsed metric values.

    Raises:
        ImportError: If PyYAML is not installed.
        FileNotFoundError: If the path does not exist.
    """
    if not _YAML_AVAILABLE:
        raise ImportError(
            "PyYAML is required to load PRD YAML files. "
            "Install it with: pip install pyyaml"
        )

    path = os.path.expanduser(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"PRD file not found: {path}")

    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    role_name = raw.get("role", raw.get("name", "Unnamed Role"))
    mission = raw.get("mission", "")

    raw_metrics = raw.get("metrics", [])
    metrics: List[Dict] = []
    for rm in raw_metrics:
        parsed = {
            "name": rm.get("name", ""),
            "target": _parse_metric_value(rm.get("target", 0)),
            "floor": _parse_metric_value(rm.get("floor", 0)),
            "min_samples": int(rm.get("min_samples", 1)),
            "before_min": str(rm.get("before_min", "TRACKING")),
        }
        if "description" in rm:
            parsed["description"] = rm["description"]
        metrics.append(parsed)

    authority = raw.get("authority", {})
    authority_can = authority.get("can", [])
    authority_cannot = authority.get("cannot", [])

    logger.info(
        f"Loaded PRD: {role_name} — {len(metrics)} metric(s), "
        f"can={len(authority_can)}, cannot={len(authority_cannot)}"
    )
    return RolePRD(
        name=role_name,
        mission=mission,
        metrics=metrics,
        authority_can=list(authority_can),
        authority_cannot=list(authority_cannot),
    )


# ============================================================
# 8. run_ralph_cycle — Entry Point
# ============================================================


def _load_all_prds(prd_dir: str) -> Dict[str, RolePRD]:
    """Load all YAML PRD files from a directory. Returns {role_key: RolePRD} dict."""
    prds: Dict[str, RolePRD] = {}
    dir_path = Path(prd_dir)

    if not dir_path.exists():
        logger.warning(f"PRD directory not found: {dir_path}")
        return prds

    for yaml_file in sorted(dir_path.glob("*.yaml")):
        try:
            prd = load_prd_yaml(str(yaml_file))
            key = yaml_file.stem
            prds[key] = prd
        except Exception as e:
            logger.error(f"Failed to load PRD from {yaml_file}: {e}")

    return prds


def _extract_schedule_from_prd(
    prd: RolePRD, raw_yaml: Dict, role_key: str
) -> Optional[str]:
    """
    Extract a schedule string from a PRD's YAML data.

    Priority:
        1. Explicit 'schedule' field (cron or HH:MM)
        2. frequency.pre_market (sample frequency): maps to a simple HH:MM
        3. Default based on role_key conventions
    """
    if "schedule" in raw_yaml:
        return str(raw_yaml["schedule"])

    frequency = raw_yaml.get("frequency", {})
    if frequency:
        for key, time_str in frequency.items():
            time_str = str(time_str).replace(" IST", "").replace(" IST", "").strip()
            m = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
            if m:
                return time_str

    return None


def _default_crew_factory():
    """
    Create the default Antariksh crew for PRD evaluation.
    Uses the crew from crew_structure module.
    """
    try:
        from crew_structure import _build_crew

        return _build_crew()
    except ImportError:
        logger.error("Cannot import crew_structure._build_crew")
        return None


def _default_metric_evaluator(output: Any) -> Dict[str, float]:
    """
    Default metric evaluator — tries to extract metrics from crew output/market_state.

    In production, replace with role-specific evaluators that parse the crew's
    actual output format. This stub returns zero-values for all known metrics.
    """
    metrics: Dict[str, float] = {}

    try:
        from crew_structure import market_state

        metrics["mtd_pnl"] = float(market_state.get("mtd_pnl", 0.0))
        metrics["session_pnl"] = float(market_state.get("session_pnl", 0.0))
    except ImportError:
        pass

    output_str = str(output).lower() if output else ""
    try:
        data = json.loads(str(output)) if output else {}
    except (json.JSONDecodeError, TypeError):
        data = {}

    known_metrics = [
        "win_rate",
        "monthly_pnl_goal",
        "crew_uptime",
        "alignment_violations",
        "board_report_on_time",
        "profit_factor",
        "max_drawdown_30d",
        "capital_floor",
    ]

    for name in known_metrics:
        if name in metrics:
            continue
        if name in data:
            try:
                metrics[name] = _parse_metric_value(data[name])
            except (ValueError, TypeError):
                metrics[name] = 0.0
        else:
            metrics[name] = 0.0

    return metrics


def run_ralph_cycle(
    prd_dir: Optional[str] = None,
    max_iterations: int = 5,
) -> Dict:
    """
    Main entry point for the Ralph Loop cycle.

    Steps:
        1. Load all PRD YAML files from ralph/prds/
        2. Create a PRDRalphLoop for each role using the default crew
        3. Create a RalphScheduler with (loop, schedule) tuples
        4. Run due roles and collect results
        5. Return summary dict

    Args:
        prd_dir: Directory containing PRD YAML files.
                 Defaults to ralph/prds/ relative to this file.
        max_iterations: Maximum Ralph Loop iterations per role.

    Returns:
        Summary dict:
        {
            "ran_at": ISO timestamp,
            "roles_loaded": N,
            "roles_run": M,
            "results": [per-role result dicts],
            "summary": brief summary string,
        }
    """
    if prd_dir is None:
        prd_dir = str(Path(__file__).parent / "prds")

    logger.info("=" * 60)
    logger.info("RALPH LOOP CYCLE — START")
    logger.info(f"PRD dir: {prd_dir}")
    logger.info("=" * 60)

    prds = _load_all_prds(prd_dir)
    if not prds:
        logger.warning("No PRDs loaded — nothing to schedule")
        return {
            "ran_at": datetime.now().isoformat(),
            "roles_loaded": 0,
            "roles_run": 0,
            "results": [],
            "summary": "No PRDs found",
        }

    crew = _default_crew_factory()
    if crew is None:
        logger.error("Cannot create crew — aborting cycle")
        return {
            "ran_at": datetime.now().isoformat(),
            "roles_loaded": len(prds),
            "roles_run": 0,
            "results": [],
            "summary": "Crew factory unavailable",
        }

    roles_with_schedules: List[Tuple[PRDRalphLoop, str]] = []

    for role_key, prd in prds.items():
        yaml_path = Path(prd_dir) / f"{role_key}.yaml"
        raw_yaml = {}
        if _YAML_AVAILABLE and yaml_path.exists():
            try:
                with open(yaml_path, "r") as f:
                    raw_yaml = yaml.safe_load(f)
            except Exception:
                pass

        schedule_str = _extract_schedule_from_prd(prd, raw_yaml, role_key)
        if schedule_str is None:
            logger.warning(f"No schedule found for {prd.name} ({role_key}) — skipping")
            continue

        def make_agent_fn(role_name, role_mission):
            def agent_fn(prompt: str) -> str:
                if crew.tasks:
                    crew.tasks[0].description = prompt
                result = crew.kickoff()
                return str(result)

            return agent_fn

        ralph_loop = PRDRalphLoop(
            agent_fn=make_agent_fn(prd.name, prd.mission),
            prd=prd,
            metric_evaluator=_default_metric_evaluator,
            max_iterations=max_iterations,
        )

        roles_with_schedules.append((ralph_loop, schedule_str))
        logger.info(f"Scheduled: {prd.name} at '{schedule_str}'")

    if not roles_with_schedules:
        logger.warning("No roles with valid schedules")
        return {
            "ran_at": datetime.now().isoformat(),
            "roles_loaded": len(prds),
            "roles_run": 0,
            "results": [],
            "summary": "No roles with valid schedules",
        }

    scheduler = RalphScheduler(roles_with_schedules)
    results = scheduler.run_due_roles()

    summary_parts = []
    for r in results:
        role = r.get("role", "unknown")
        if "error" in r:
            summary_parts.append(f"{role}: ERROR ({r['error']})")
        else:
            summary_parts.append(
                f"{role}: {r.get('completion_reason', '?')} "
                f"({r.get('iterations', 0)} iter)"
            )

    summary_str = (
        "; ".join(summary_parts) if summary_parts else "No roles due at this time"
    )

    logger.info("=" * 60)
    logger.info("RALPH LOOP CYCLE — COMPLETE")
    logger.info(f"Summary: {summary_str}")
    logger.info("=" * 60)

    return {
        "ran_at": datetime.now().isoformat(),
        "roles_loaded": len(prds),
        "roles_run": len(results),
        "results": results,
        "summary": summary_str,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    result = run_ralph_cycle()
    print(f"\nRalph Cycle Result: {result['summary']}")
