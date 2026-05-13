# CTO-Dev-QA Pipeline — PAUL Plan

## Context
Build the technical governance pipeline: CTO gatekeeps changes, Dev implements, QA validates. Plus Research layer for comparative strategy analysis. **User mandate: always Plan→Apply→Unify→Loop. Never code without a plan.**

## P: Plan — What we're building

### Completed (Apply-first, retroactively documented):
- ✅ `tools/pm_tools.py` — `analyze_wing_margins()`, `recommend_optimal_wing()`, `build_strategy_spec()` with dynamic wing
- ✅ `crew_structure.py` — `generate_trade_plan()` reads `recommended_wing` from market_state
- ✅ `crews/pm_crew.py` — PM Strategist has wing optimization tools
- ✅ `tools/cto_tools.py` — gatekeeping + strategic functions (scout_technology, evaluate_architecture, design_poc_plan)
- ✅ `tools/dev_tools.py` — read_source, preview_edit, apply_edit, commit_change, rollback_change, run_smoke_test

### To build:
| # | Deliverable | Waves |
|---|------------|-------|
| 1 | `tools/qa_tools.py` — test runner, regression checker, scenario validator, diff comparator, QA report generator | Wave 1 |
| 2 | `crews/cto_crew.py` — CTO agent (strategic + gatekeeping) with manager_llm for delegation | Wave 2 |
| 3 | `crews/dev_crew.py` — Dev Engineer agent with implementation tools | Wave 2 |
| 4 | `crews/qa_crew.py` — QA Tester agent with validation tools | Wave 2 |
| 5 | Pipeline wiring — CTO receives change_request → evaluates → delegates to Dev → delegates to QA → final signoff | Wave 3 |
| 6 | Integration test — end-to-end flow with a dummy change | Wave 3 |

### Research Layer (after pipeline):
- Research Agent(s) + naming TBD
  - "Director of Alpha Research" (DAR)
  - "Head of Strategy Research"
  - "Quant Research Lab"
  - User will decide

## A: Apply — Implementation phases

### Wave 1: QA Tools (now)
- `tools/qa_tools.py`
  - `run_test_suite()` — executes pytest/scenario tests
  - `validate_no_regression()` — all tests pass vs. baseline
  - `compare_outputs()` — diff snapshots
  - `run_scenario()` — single scenario with assertions
  - `generate_qa_report()` — structured pass/fail + evidence

### Wave 2: Crew files (next)
- `crews/cto_crew.py` — CTO (strategic scouting + gatekeeping)
- `crews/dev_crew.py` — Dev Engineer
- `crews/qa_crew.py` — QA Tester

### Wave 3: Pipeline integration (last)
- Pipe change_request through CTO→Dev→QA→signoff

## U: Unify — Verification (after each wave)
1. Syntax check: `python3 -m py_compile`
2. Import test: `python3 -c "from tools.xxx_tools import *"`
3. Unit test: call each function with sample input
4. Integration test: end-to-end pipeline with dummy change

## L: Loop — Next iteration
- Research Agent layer
- Deploy pipeline to live session

## Decision Log
- **2026-05-10**: Chose CTO→Dev→QA pipeline over PM-direct-code-edit to maintain separation of concerns
- **2026-05-10**: CTO expanded from gatekeeper to strategic role (tech scouting, POC design, architecture)
- **2026-05-10**: Wing width analysis uses 50→500 in 50-pt increments with 4-factor scoring
- **2026-05-10**: PAUL model mandated for all builds going forward
