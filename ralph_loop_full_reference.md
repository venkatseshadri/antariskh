# Ralph Loop — Full Reference for Antariksh

## 1. What Is the Ralph Loop (General Concept)

The **Ralph Loop** (aka the "Ralph Wiggum technique") is an AI agent autonomy pattern created by Geoffrey Huntley at Vercel Labs. Named after the persistently clueless but good-natured Ralph Wiggum from *The Simpsons*, the core idea is:

> **Keep feeding an AI agent a task until it's actually done — verified, not assumed.**

Geoffrey Huntley's summary: **"Ralph is a Bash loop."**

### Why It Exists

Standard AI agent workflows stop when the LLM finishes calling tools, even if the task isn't truly complete. Complex work requires:
- **Verification** — Did the agent actually accomplish what was asked?
- **Persistence** — Retry on failure instead of giving up
- **Feedback loops** — Guide the agent based on real-world checks
- **Long-horizon execution** — Migrations, refactors, multi-file changes, multi-day tasks

### Architecture

```
┌──────────────────────────────────────────────────────┐
│                   Ralph Loop (outer)                 │
│  ┌────────────────────────────────────────────────┐  │
│  │  AI Tool Loop (inner)                          │  │
│  │  LLM ↔ tools ↔ LLM ↔ tools ... until done      │  │
│  └────────────────────────────────────────────────┘  │
│                         ↓                            │
│  verifyCompletion: "Is the TASK actually complete?"  │
│                         ↓                            │
│       No? → Inject feedback → Run another iteration  │
│       Yes? → Return final result                     │
└──────────────────────────────────────────────────────┘
```

It wraps an inner AI agent loop with an outer verification loop. Each iteration:
1. Runs the agent on the task
2. Checks if the result meets completion criteria
3. If not, injects feedback into the next attempt
4. Repeats until verified or a safety limit is hit

---

## 2. The Original npm Package

**Repository:** `github.com/vercel-labs/ralph-loop-agent`
**Language:** TypeScript (for the Vercel AI SDK)

### Installation

```bash
npm install ralph-loop-agent ai zod
```

### Basic Usage

```typescript
import { RalphLoopAgent, iterationCountIs } from 'ralph-loop-agent';

const agent = new RalphLoopAgent({
  model: 'anthropic/claude-opus-4.5',
  instructions: 'You are a helpful coding assistant.',
  stopWhen: iterationCountIs(10),
  verifyCompletion: async ({ result }) => ({
    complete: result.text.includes('DONE'),
    reason: 'Task completed successfully',
  }),
});

const { text, iterations, completionReason } = await agent.loop({
  prompt: 'Create a function that calculates fibonacci numbers',
});
```

### Stop Conditions

| Condition | Description |
|-----------|-------------|
| `iterationCountIs(n)` | Stop after N iterations |
| `tokenCountIs(n)` | Stop when total tokens exceed N |
| `costIs(maxCost)` | Stop when estimated cost exceeds threshold |
| `[cond1, cond2]` | Combine — stop when any condition is met |

### Verification Function

```typescript
verifyCompletion: async ({ result, iteration, allResults, originalPrompt }) => ({
  complete: boolean,
  reason?: string, // Feedback for next iteration
})
```

---

## 3. The Pattern Is Language-Agnostic

The npm package is TypeScript-specific, but the **pattern** works with any language or framework. At its core, it's pseudocode:

```python
while not done and iteration < max_iterations:
    result = agent.run(task_description)
    done, feedback = verify(result)
    if not done:
        task_description += f"\n\nPrevious attempt failed: {feedback}"
```

This works with:
- Python (any framework)
- CrewAI
- LangChain
- Bash scripts
- Any CLI tool

---

## 4. Generic Python Implementation

### 4.1 Minimal Version (Any Agent)

```python
from dataclasses import dataclass
from typing import Callable, Any, Optional

@dataclass
class VerificationResult:
    complete: bool
    reason: str = ""

class RalphLoop:
    """Generic Ralph Loop — wraps any agent/function in verify-retry logic."""
    
    def __init__(
        self,
        agent_fn: Callable[[str], Any],
        verify_fn: Callable[[Any], VerificationResult],
        max_iterations: int = 10,
        on_iteration_start: Optional[Callable] = None,
        on_iteration_end: Optional[Callable] = None,
    ):
        self.agent_fn = agent_fn
        self.verify_fn = verify_fn
        self.max_iterations = max_iterations
        self.on_iteration_start = on_iteration_start
        self.on_iteration_end = on_iteration_end
    
    def run(self, prompt: str) -> dict:
        """Run until verified or max iterations reached."""
        results = []
        
        for i in range(self.max_iterations):
            if self.on_iteration_start:
                self.on_iteration_start(i + 1)
            
            result = self.agent_fn(prompt)
            results.append(result)
            
            verified = self.verify_fn(result)
            
            if self.on_iteration_end:
                self.on_iteration_end(i + 1, verified)
            
            if verified.complete:
                return {
                    "result": result,
                    "iterations": i + 1,
                    "completion_reason": "verified",
                    "reason": verified.reason,
                    "all_results": results,
                }
            
            # Inject feedback for next iteration
            prompt += f"\n\n[ITERATION {i+1} FEEDBACK]: {verified.reason}\nPlease address this and try again."
        
        return {
            "result": result,
            "iterations": self.max_iterations,
            "completion_reason": "max_iterations",
            "reason": f"Failed to verify after {self.max_iterations} iterations",
            "all_results": results,
        }
```

### 4.2 Usage Example

```python
def my_agent(task: str) -> str:
    """Replace with your actual agent (CrewAI, LangChain, GPT call, etc.)"""
    # ... agent logic ...
    return response

def verify_output(text: str) -> VerificationResult:
    has_done = "DONE" in text
    return VerificationResult(
        complete=has_done,
        reason="Task complete" if has_done else "No DONE marker found"
    )

loop = RalphLoop(
    agent_fn=my_agent,
    verify_fn=verify_output,
    max_iterations=5,
    on_iteration_start=lambda n: print(f"--- Iteration {n} ---"),
)

response = loop.run("Build a Fibonacci function. Signal DONE when complete.")
print(f"Completed in {response['iterations']} iterations")
```

---

## 5. CrewAI-Specific Implementation

### 5.1 Wrapping a Crew as a Ralph Agent

```python
from crewai import Crew, Agent, Task, Process

class CrewAIRalphLoop(RalphLoop):
    """Ralph Loop specialized for CrewAI."""
    
    def __init__(
        self,
        crew: Crew,
        verify_fn: Callable[[str], VerificationResult],
        max_iterations: int = 10,
        **kwargs
    ):
        def crew_agent(prompt: str) -> str:
            # Set the task description dynamically
            crew.tasks[0].description = prompt
            result = crew.kickoff()
            return str(result)
        
        super().__init__(
            agent_fn=crew_agent,
            verify_fn=verify_fn,
            max_iterations=max_iterations,
            **kwargs
        )
```

### 5.2 Concrete Example with Multiple Verification Checks

```python
def verify_trade_output(output: str) -> VerificationResult:
    """Verify CrewAI trading output meets all criteria."""
    checks = []

    # Check 1: Must have entry signal or skip reason
    if "ENTRY" in output or "SKIP" in output:
        checks.append(("Entry/Skip decision", True))
    else:
        checks.append(("Entry/Skip decision", False))

    # Check 2: If entry, must have stop-loss
    if "ENTRY" in output and "SL" not in output:
        checks.append(("Stop-loss present", False))
    else:
        checks.append(("Stop-loss present", True))

    # Check 3: Must not exceed position size
    if "POSITION_SIZE" in output and "300000" in output:
        checks.append(("Position size within limit", False))
    else:
        checks.append(("Position size within limit", True))

    failures = [c[0] for c in checks if not c[1]]

    if failures:
        return VerificationResult(
            complete=False,
            reason=f"Failed checks: {', '.join(failures)}. Fix these before proceeding."
        )

    return VerificationResult(complete=True, reason="All checks passed")


# Assuming an existing crew
trading_crew = Crew(
    agents=[scanner, strategist, executor],
    tasks=[main_task],
    process=Process.sequential,
)

ralph_crew = CrewAIRalphLoop(
    crew=trading_crew,
    verify_fn=verify_trade_output,
    max_iterations=3,
    on_iteration_start=lambda n: print(f"Ralph iteration {n} running..."),
    on_iteration_end=lambda n, v: print(f"  → {'PASSED' if v.complete else 'FAILED'}: {v.reason}")
)

result = ralph_crew.run(
    "Analyze market conditions for NIFTY 09-May-2026. "
    "Execute Iron Fly if conditions are favorable, otherwise SKIP."
)
```

---

## 6. PRD-Driven Ralph Loop for Antariksh

Your vision (from `ralph_loop.md`): each role has a measurable PRD. Ralph checks if the role is meeting its PRD, and self-corrects if not.

### 6.1 Role PRD Example

```python
@dataclass
class RolePRD:
    name: str
    metrics: dict[str, tuple[float, float]]  # metric_name -> (target, acceptable_min)
    check_schedule: str                         # cron expression
    authority_level: str                        # "auto", "ceo_approval", "chairman_approval"

cfo_prd = RolePRD(
    name="CFO",
    metrics={
        "monthly_pnl": (300000, 200000),       # INR target, acceptable
        "win_rate": (0.60, 0.55),
        "profit_factor": (1.5, 1.3),
        "max_drawdown_30d": (15000, 30000),
        "capital_floor": (11000, 11000),        # hard floor, no acceptable range
    },
    check_schedule="0 15 * * 1-5",             # 15:00 IST every weekday
    authority_level="auto",                      # can auto-approve ±10% tweaks
)
```

### 6.2 PRD-Aware Ralph Loop

```python
class PRDRalphLoop(RalphLoop):
    """Ralph Loop that evaluates an agent's PRD after each run."""

    def __init__(
        self,
        agent_fn: Callable[[str], Any],
        prd: RolePRD,
        metric_evaluator: Callable[[dict], dict[str, float]],
        max_iterations: int = 5,
        **kwargs
    ):
        self.prd = prd
        self.metric_evaluator = metric_evaluator

        def verify_fn(output: Any) -> VerificationResult:
            current_metrics = metric_evaluator(output)

            failures = []
            for metric_name, (target, floor) in prd.metrics.items():
                actual = current_metrics.get(metric_name, 0)
                if actual < floor:
                    failures.append(
                        f"{metric_name}: {actual} (floor: {floor}, target: {target})"
                    )

            if failures:
                return VerificationResult(
                    complete=False,
                    reason=f"PRD for {prd.name} violated: {'; '.join(failures)}"
                )

            # Check if stretching to target needed
            suggestions = []
            for metric_name, (target, floor) in prd.metrics.items():
                actual = current_metrics.get(metric_name, 0)
                if actual < target and actual >= floor:
                    suggestions.append(
                        f"{metric_name}: {actual} below target {target}"
                    )

            feedback = ""
            if suggestions:
                feedback = f"Acceptable but below target: {'; '.join(suggestions)}"

            return VerificationResult(
                complete=True,
                reason=feedback or f"All {prd.name} PRD metrics met"
            )

        super().__init__(
            agent_fn=agent_fn,
            verify_fn=verify_fn,
            max_iterations=max_iterations,
            **kwargs
        )
```

### 6.3 Scheduler for Multiple PRD Roles

```python
# ralph_scheduler.py

import asyncio
from datetime import datetime
from typing import List

class RalphScheduler:
    """Orchestrates multiple PRD-driven Ralph Loops on a schedule."""

    def __init__(self, roles: List[Tuple[PRDRalphLoop, str]]):
        """
        roles: list of (loop_instance, cron_expression)
        """
        self.roles = roles

    async def run_role(self, loop: PRDRalphLoop) -> dict:
        role_name = loop.prd.name
        print(f"[{datetime.now()}] Checking PRD for {role_name}...")
        result = loop.run(f"Execute your mission as {role_name}. Review your PRD.")
        print(f"[{datetime.now()}] {role_name}: {result['completion_reason']} "
              f"in {result['iterations']} iterations")
        return result

    async def run_due_roles(self):
        """Run all roles whose schedule matches current time."""
        tasks = []
        for loop, cron_expr in self.roles:
            if self._cron_matches_now(cron_expr):
                tasks.append(self.run_role(loop))
        return await asyncio.gather(*tasks)

    def _cron_matches_now(self, cron_expr: str) -> bool:
        """Check if cron expression matches current time."""
        from croniter import croniter
        prev = croniter(cron_expr, datetime.now())
        return prev.get_prev(datetime) == prev.get_current(datetime)


# Usage:
# scheduler = RalphScheduler([
#     (cfo_loop, "30 15 * * 1-5"),      # 15:30 IST weekdays
#     (ceo_loop, "30 18 * * 5"),         # 18:30 IST Fridays
#     (analyst_loop, "45 16 * * 1-5"),   # 16:45 IST weekdays
# ])
# asyncio.run(scheduler.run_due_roles())
```

---

## 7. Ralph Loop as a Bash Loop (Simplest Form)

The simplest possible implementation — works with any CLI tool:

```bash
#!/bin/bash
# ralph_loop.sh — The simplest Ralph Loop

MAX_ITERATIONS=10
TASK="$1"
ITERATION=0

while [ $ITERATION -lt $MAX_ITERATIONS ]; do
    ITERATION=$((ITERATION + 1))
    echo "=== Ralph Loop Iteration $ITERATION/$MAX_ITERATIONS ==="

    # Call your agent (replace with your actual command)
    RESULT=$(python -m antariksh.crews.trading.run "$TASK")

    # Verify — replace with your actual verification
    if echo "$RESULT" | python -c "
import sys
data = sys.stdin.read()
if 'PASSED' in data:
    sys.exit(0)
else:
    sys.exit(1)
"; then
        echo "Verification PASSED. Exiting."
        break
    else
        echo "Verification FAILED. Adding feedback..."
        TASK="$TASK

    [ITERATION $ITERATION FEEDBACK]: The previous attempt failed verification.
    Please review and fix the issues before trying again."
    fi
done

echo "Ralph Loop exited after $ITERATION iterations."
```

---

## 8. Where Ralph Loop Fits in Antariksh

```
                    ┌──────────────────────────────┐
                    │   Chairman (You)              │
                    │   Vision: Retire by 50,       │
                    │   ₹3L/month passive income    │
                    └──────────┬───────────────────┘
                               │
                    ┌──────────▼───────────────────┐
                    │   Ralph Loop (Meta Layer)     │
                    │                               │
                    │  CEO → monthly goal tracking  │
                    │  CFO → profitability PRD      │
                    │  Analyst → win rate PRD       │
                    │  Asset Mgr → allocation PRD   │
                    │  Risk Guard → capital floor   │
                    │                               │
                    │  Each checks PRD on schedule  │
                    │  Self-corrects if off track   │
                    │  Escalates to chairman if     │
                    │  beyond bounded autonomy      │
                    └──────────┬───────────────────┘
                               │
                    ┌──────────▼───────────────────┐
                    │   CrewAI (Tactical Layer)     │
                    │                               │
                    │  Scanner → market analysis    │
                    │  Strategist → strategy choice │
                    │  Executor → order placement   │
                    │  Sentinel → risk monitoring   │
                    │  Auditor → compliance check   │
                    │                               │
                    │  CrewAI runs per-session:     │
                    │  09:30 entry / 14:35 exit     │
                    └──────────────────────────────┘
```

**Key distinction:**
- **CrewAI** = Tactical execution (how to run Iron Fly today)
- **Ralph Loop** = Strategic oversight (should we run Iron Fly at all? Is it hitting our ₹3L/month goal?)

---

## 9. Summary

| Aspect | Detail |
|--------|--------|
| **Origin** | Geoffrey Huntley, Vercel Labs |
| **Core idea** | `while not done: run → verify → feedback → repeat` |
| **Original package** | `npm install ralph-loop-agent` (TypeScript, AI SDK) |
| **Python/CrewAI** | Trivial to reimplement — just a `while` loop with verification |
| **Bash** | Literally a Bash loop around any CLI agent |
| **Antariksh fit** | Strategic meta-layer above CrewAI tactical layer |
| **PRD-driven** | Each role gets measurable goals; Ralph checks if on track |
| **Safety critical** | Capital rules are constitutional, cannot be overridden by any Ralph role |

### Key Principle

```
Don't treat agent output as correct just because the agent stopped talking.
Always verify. If it's wrong, tell it what's wrong and make it try again.
That's Ralph.
```

---

## 10. Files in this Directory

| File | Purpose |
|------|---------|
| `ralph_loop.md` | Your original vision/notes on Ralph for Antariksh |
| `RALPH_LOOP_ANALYSIS.md` | Claude's architectural analysis & phased roadmap |
| `ralph_loop_full_reference.md` | This file — technical reference & implementation patterns |
