# Antariksh Project Instructions

## Behavioral Guidelines

Adapted from https://github.com/multica-ai/andrej-karpathy-skills

These bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think before coding
State assumptions explicitly. If multiple interpretations exist, surface them — don't pick silently. If unclear, stop and ask.

### 2. Simplicity first
Minimum code that solves the problem. No features beyond what was asked, no single-use abstractions, no error handling for impossible scenarios. If you wrote 200 lines and it could be 50, rewrite.

### 3. Surgical changes
Touch only what you must. Don't "improve" adjacent code, formatting, or comments. Match existing style. If you spot unrelated dead code, mention it — don't delete it. Every changed line traces to the user's request.

### 4. Goal-driven execution
Transform tasks into verifiable goals: "fix the bug" → "write a failing test, then make it pass." For multi-step work, state a brief plan with verification per step.

### 5. Cite the rule
When making a design or implementation decision, explicitly mention which rule (1-4) guided it. Example: "Using Rule 2 (simplicity first), inlining this instead of extracting a one-off abstraction."

## Session Bookkeeping (MANDATORY)

At the end of every session — after any significant work is done — run this command BEFORE saying goodbye:

```bash
python3 tools/update_context.py --last-task "one-line summary of what you just built" --priority "next thing to do"
git add CONTEXT.md && git commit -m "chore: auto-update session context" && git push origin master
```

This keeps `CONTEXT.md` fresh so the next session starts with zero discovery overhead.

## Project-Specific Rules

1. Before writing code, check `CONTEXT.md` for current state and `ARCHITECTURE.md` for system design.
2. `GAPS_AND_ROADMAP.md` lists what's mocked vs production. When wiring a mock → real, mark it done there.
3. Deterministic tools take priority over LLM-driven agents for risk/execution decisions.
4. Run `python3 tests/test_integration_end_to_end.py` after any change to `trading_desk.py` — must stay at 39/39.
