# Antariksh Project Instructions

## Session Bookkeeping (MANDATORY)

At the end of every session — after any significant work is done — run this command BEFORE saying goodbye:

```bash
python3 tools/update_context.py --last-task "one-line summary of what you just built" --priority "next thing to do"
git add CONTEXT.md && git commit -m "chore: auto-update session context" && git push origin master
```

This keeps `CONTEXT.md` fresh so the next session starts with zero discovery overhead.

## Additional Rules

1. Before writing code, check `CONTEXT.md` for current state and `ARCHITECTURE.md` for system design.
2. `GAPS_AND_ROADMAP.md` lists what's mocked vs production. When wiring a mock → real, mark it done there.
3. Deterministic tools take priority over LLM-driven agents for risk/execution decisions.
4. Run `python3 tests/test_integration_end_to_end.py` after any change to `trading_desk.py` — must stay at 39/39.
