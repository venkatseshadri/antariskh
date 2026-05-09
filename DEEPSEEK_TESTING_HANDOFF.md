# DeepSeek Scenario Testing Handoff
**Date:** 2026-05-09
**Status:** Phase 2 architecture complete (per `DEEPSEEK_REPORT.md`). Now we need scenario-based behavioral validation before Monday live.
**Handoff Time:** Saturday morning IST
**Resume Time:** Claude resumes Sunday evening to review report and integrate fixes

---

## Mission

Build a **scenario-based test harness** that injects mock market conditions into the existing CrewAI 7-agent system and verifies each agent behaves as the constitution requires. Run 32 scenarios. Report pass/fail with evidence.

**Outcome Expected (deliverables):**
1. `tests/scenario_runner.py` — reusable scenario harness (one file, ~400 lines)
2. `tests/test_scenarios.py` — 32 scenario test functions (one per scenario in the plan)
3. `tests/fixtures/` — helpers for JSONL seeding, mock LLM, mock broker
4. `SCENARIO_TEST_RESULTS.md` — pass/fail report (template at end of this doc)
5. `tests/run_all.sh` — single command to execute all scenarios

**Timeline:** ~6 hours of focused work over weekend. Claude reviews Sunday evening.

---

## Context: What Has Been Done

### Reference Documents (READ FIRST, IN ORDER)

| # | File | Purpose | Read Time |
|---|---|---|---|
| 1 | `/home/trading_ceo/antariksh/SCENARIO_TEST_PLAN.md` | **WHAT** to test — 32 scenarios with expected behavior per agent | 25 min |
| 2 | `/home/trading_ceo/antariksh/TESTING_INFRASTRUCTURE.md` | **HOW** to mock/inject — complete `ScenarioRunner` design + 5 mocking layers | 20 min |
| 3 | `/home/trading_ceo/antariksh/DEEPSEEK_REPORT.md` | What you built last time (Phase 2 crew architecture) | 5 min |
| 4 | `/home/trading_ceo/PHASE_AUDIT_REPORT.md` | Known gaps in Phase 1/2 (some scenarios will fail because of these — that's expected) | 10 min |

### What's Already Built (don't rebuild)
- `crew_structure.py` (555 lines) — 7 agents, 6 tasks, hierarchical Crew
- `crew_test.py` (264 lines) — 4 baseline tests (HP-01 partial, HP-03 covered)
- `AuditorEngine`, `RiskGuardEngine`, `ReEntryTracker` — deterministic engines (DO NOT mock these — verify them)
- `config/antariksh_rules.yaml` — L3 parameters

### Known Gaps (some scenarios WILL fail — that's correct behavior)
- `is_event_day()` always returns False → HP-04 will fail
- Scanner has no real-time loop → MC-01 will fail
- Sentinel has no timeout handling → SF-05 will fail
- Cron not configured → SF-04 partial only

**Important:** Failed scenarios are not bugs in YOUR work. They reveal genuine gaps. Document them in the report. Do NOT modify production code to make tests pass.

---

## Your Task: Build & Run Scenario Tests

### Phase A: Build the Harness (3 hours)

#### Task A1: Create `tests/scenario_runner.py`
**File:** `/home/trading_ceo/antariksh/tests/scenario_runner.py`
**Reference:** Section 7 of `TESTING_INFRASTRUCTURE.md` has the complete pseudocode.

**Required class:**
```python
class ScenarioRunner:
    """Context manager. See TESTING_INFRASTRUCTURE.md §7 for full spec."""
    
    # Lifecycle
    def __enter__(self) -> 'ScenarioRunner': ...
    def __exit__(self, *args): ...  # MUST restore state, cleanup tempdir
    
    # Setup methods
    def set_time(self, iso_str: str): ...
    def set_market(self, vix: float, nifty: float): ...
    def set_pnl_trajectory(self, trajectory: List[float]): ...
    def seed_history(self, days: int, daily_pnl: List[float] = None): ...
    def set_llm_responses(self, response_map: Dict[str, str]): ...
    def set_event_day(self, event_name: str): ...  # for HP-04
    def set_vix_trajectory(self, trajectory: List[Dict]): ...  # for MC-01
    def set_sentinel_blackout(self, after_seconds: int): ...  # for SF-05
    
    # Execution
    def run(self) -> Dict: ...  # invokes run_full_session with all mocks active
    def run_engine_only(self, engine: str, **kwargs) -> Dict: ...  # bypass crew, hit RiskGuard/Auditor directly
    
    # Assertions
    def assert_state(self, expected: Dict): ...
    def assert_jsonl(self, contains: Dict): ...
    def assert_telegram_contains(self, substring: str): ...
    def assert_agent_order(self, expected: List[str]): ...
    def assert_no_llm_in(self, agent_name: str): ...  # verify deterministic path
```

**Acceptance:**
- All methods listed above are implemented
- Uses `tempfile.mkdtemp()` for isolated logs (see TESTING_INFRASTRUCTURE.md §3 "Persistent State")
- Saves and restores `market_state` dict
- Patches `litellm.completion` for LLM mocking
- Patches `LOG_DIR` for log isolation

#### Task A2: Create `tests/fixtures/seed_history.py`
**File:** `/home/trading_ceo/antariksh/tests/fixtures/seed_history.py`

Helper functions:
```python
def seed_jsonl(log_dir: Path, days_back: int, pnl_per_day: List[float]):
    """Write N days of synthetic JSONL files matching cfo_audit_*.jsonl schema."""

def seed_consecutive_losses(log_dir: Path, count: int, sl_amount: float = 3500):
    """Write N consecutive SL hit days (for DD-01)."""

def seed_30day_dd_at_threshold(log_dir: Path, target_mtd: float = -30000):
    """Write 28 days summing to ~ -₹26,500 (RM-04 setup)."""
```

#### Task A3: Create `tests/fixtures/mock_llm.py`
**File:** `/home/trading_ceo/antariksh/tests/fixtures/mock_llm.py`

```python
class MockLLM:
    """Returns canned responses based on agent role detection."""
    
    def __init__(self, response_map: Dict[str, str]):
        self.calls = []  # for assertion
    
    def call(self, messages, **kwargs):
        # Detect agent from system prompt, return canned response
        # Track calls in self.calls for assertions
        ...

def make_litellm_patch(response_map):
    """Returns a function suitable for mock.patch('litellm.completion', side_effect=...)."""
    ...
```

#### Task A4: Create `tests/fixtures/mock_broker.py`
**File:** `/home/trading_ceo/antariksh/tests/fixtures/mock_broker.py`

```python
class MockBrokerManager:
    """Reads from env vars; captures orders for assertions."""
    
    captured_orders = []  # class-level
    
    def get_vix(self) -> float: ...  # reads ANTARIKSH_MOCK_VIX
    def get_nifty_spot(self) -> float: ...  # reads ANTARIKSH_MOCK_NIFTY
    def get_position_mtm(self, position_id) -> float: ...  # reads trajectory
    def place_order(self, leg) -> Dict: ...  # captures, returns mock order_id
```

---

### Phase B: Build the 32 Scenario Tests (2.5 hours)

#### Task B1: Create `tests/test_scenarios.py`
**File:** `/home/trading_ceo/antariksh/tests/test_scenarios.py`

**Structure:** One function per scenario from `SCENARIO_TEST_PLAN.md`. Use this exact function naming convention:
```python
def test_HP_01_clean_win(): ...
def test_HP_02_time_exit_no_target(): ...
def test_HP_03_gate_skip_high_vix(): ...
def test_HP_04_gate_skip_event_day(): ...
def test_RM_01_session_sl_first_hit(): ...
def test_RM_02_second_sl_hard_halt(): ...
def test_RM_03_portfolio_sl_breach(): ...
def test_RM_04_30day_dd_breach(): ...
def test_RM_05_free_cash_floor_breach(): ...
def test_RM_06_burn_rate_30pct(): ...
def test_DD_01_5_consecutive_losses(): ...
def test_DD_02_10day_burn_boundary(): ...
def test_DD_03_30session_advancement_eligible(): ...
def test_DD_04_profit_factor_below_1(): ...
def test_MC_01_intraday_vix_spike(): ...
def test_MC_02_gap_open_above_05pct(): ...
def test_MC_03_late_entry_window_closed(): ...
def test_MC_04_wide_bid_ask_spread(): ...
def test_MC_05_first_15min_skip(): ...
def test_SF_01_shoonya_down_flattrade_fallback(): ...
def test_SF_02_both_brokers_down(): ...
def test_SF_03_llm_provider_failover(): ...
def test_SF_04_cron_late_trigger(): ...
def test_SF_05_sentinel_network_blackout(): ...
def test_OP_01_operator_override_attempt_blocked(): ...
def test_OP_02_operator_confirmation_timeout(): ...
def test_OP_03_telegram_unreachable(): ...
def test_LC_01_month_rollover_mtd_reset(): ...
def test_LC_02_weekend_no_session(): ...
def test_LC_03_first_session_after_30day_halt(): ...
def test_EC_01_vix_exactly_at_2000(): ...
def test_EC_02_sl_at_14_34_59_race(): ...
```

**Each function MUST follow this template:**
```python
def test_RM_01_session_sl_first_hit():
    """
    Scenario RM-01: Session SL Hit (₹3,500) — First Hit, Re-entry Allowed
    Validates: Sentinel SL detection, ReEntryTracker, no halt for single-instrument SL.
    Reference: SCENARIO_TEST_PLAN.md §RM-01
    """
    with ScenarioRunner("RM-01") as sc:
        # SETUP (per scenario spec)
        sc.set_time("2026-05-12 11:45:00")
        sc.set_market(vix=14, nifty=24500)
        sc.set_pnl_trajectory([-500, -1500, -2500, -3500])
        sc.seed_history(days=0)
        sc.set_llm_responses({
            "scanner": '{"vix": 14, "gate_pass": true}',
            "strategist": '{"strikes": [24500, 24800, 24200]}',
        })
        
        # EXECUTE
        result = sc.run()
        
        # ASSERT (per "Pass criteria" in SCENARIO_TEST_PLAN.md)
        sc.assert_state({
            'exit_reason': 'Stop loss',
            'session_pnl': -3500,
            're_entries_used': 0,
            'halt': False,
        })
        sc.assert_jsonl({'exit_reason': 'Stop loss', 'capital_impact.net_pnl': -3500})
        sc.assert_telegram_contains('SL HIT')
        sc.assert_telegram_contains('Re-entry option')
        sc.assert_agent_order(['Scanner', 'Strategist', 'Risk Guard', 'Executor', 'Sentinel', 'Auditor'])
```

**Pull setup/assertions from SCENARIO_TEST_PLAN.md** for each scenario. The scenario doc is the source of truth.

#### Task B2: Create `tests/run_all.sh`
**File:** `/home/trading_ceo/antariksh/tests/run_all.sh`

```bash
#!/bin/bash
# Run all 32 scenarios, generate SCENARIO_TEST_RESULTS.md
set -u
cd /home/trading_ceo/antariksh

export ANTARIKSH_MOCK_MODE=1

python3 -m pytest tests/test_scenarios.py \
    --tb=short \
    --json-report --json-report-file=tests/results.json \
    -v 2>&1 | tee tests/run.log

# Generate the markdown report
python3 tests/generate_report.py tests/results.json > SCENARIO_TEST_RESULTS.md
```

#### Task B3: Create `tests/generate_report.py`
Reads `results.json`, generates `SCENARIO_TEST_RESULTS.md` matching the template at end of this doc.

---

### Phase C: Run & Report (0.5 hours)

#### Task C1: Execute
```bash
chmod +x tests/run_all.sh
./tests/run_all.sh
```

#### Task C2: Generate Final Report
Write `/home/trading_ceo/antariksh/SCENARIO_TEST_RESULTS.md` using the **exact template at the end of this document**.

#### Task C3: Self-Verify
Before declaring done, verify:
- [ ] All 32 test functions exist in `test_scenarios.py`
- [ ] `SCENARIO_TEST_RESULTS.md` has all 32 scenarios listed
- [ ] Pass count + fail count + skip count = 32
- [ ] Each fail has a "root cause" classification
- [ ] Critical scenarios (RM-*, SF-02, SF-05, OP-01) are categorized

---

## Implementation Guidance

### Tech Stack
- Python 3.11
- `pytest` (already installed) — `pip3 install pytest pytest-json-report --break-system-packages` if needed
- `unittest.mock` (stdlib) — for patching litellm
- NO `freezegun` — use environment variables + monkeypatch (avoids new dependency)

### Pattern: Engine-Only Tests (FAST)
For RM-*, DD-* scenarios — bypass CrewAI entirely. Call `RiskGuardEngine.full_check()` and `AuditorEngine.calculate_mtd_from_logs()` directly. **5x faster than full crew run, 100% deterministic.**

```python
def test_RM_05_free_cash_floor_breach():
    with ScenarioRunner("RM-05") as sc:
        sc.seed_history(days=0)
        # Set up state directly
        from crew_structure import market_state, RiskGuardEngine
        market_state['session_pnl'] = -3500
        market_state['mtd_pnl'] = -3500
        # Free cash starts at 14000, after -3500 → 10500 (below 11000 floor)
        market_state['free_cash'] = 10500
        
        # Run engine directly
        result = RiskGuardEngine.full_check(session_pnl=-3500, mtd_pnl=-3500)
        
        # Assert
        assert result['halt'] == True
        assert 'free_cash_floor_breach' in result['violations']
```

### Pattern: Full Crew Tests (REALISTIC)
For HP-*, MC-*, OP-* scenarios — invoke the full crew. Mock LLM responses.

### Reading Inputs from Existing Code
Before mocking, READ these to understand current behavior:
- `crew_structure.py:644` — `initialize_session()`
- `crew_structure.py:484` — `RiskGuardEngine` (5 checks)
- `crew_structure.py:336` — `AuditorEngine` (JSONL parsing)
- `phase1_mvs.py:89` — `MarketDataBridge` class (inline)

### Don't Modify Production Code
**NEVER** change `crew_structure.py`, `phase1_mvs.py`, or `config/antariksh_rules.yaml` to make tests pass. If a test fails because of a real gap (e.g., `is_event_day()` broken), document it in the report. Claude integrates fixes separately.

You MAY add to:
- `tests/` (new directory — all your work goes here)
- New module imports in `crew_structure.py` only if they don't change behavior (e.g., adding `LOG_DIR` patchability)

---

## How to Verify Your Work Before Reporting

Run this checklist:

```bash
# 1. Files exist
ls /home/trading_ceo/antariksh/tests/
# Expected: scenario_runner.py, test_scenarios.py, fixtures/, run_all.sh, generate_report.py

# 2. Smoke test the runner alone
python3 -c "
import sys; sys.path.insert(0, '/home/trading_ceo/antariksh')
from tests.scenario_runner import ScenarioRunner
with ScenarioRunner('SMOKE') as sc:
    sc.set_market(vix=14, nifty=24500)
    print('Runner OK')
"

# 3. Smoke test one engine-only scenario (RM-01 is good)
python3 -m pytest tests/test_scenarios.py::test_RM_01_session_sl_first_hit -v

# 4. Run all
./tests/run_all.sh

# 5. Verify report exists
ls -la SCENARIO_TEST_RESULTS.md

# 6. Sanity-check report
grep -c "^### SC-" SCENARIO_TEST_RESULTS.md
# Expected: 32
```

---

## How to Report Back

Write `/home/trading_ceo/antariksh/SCENARIO_TEST_RESULTS.md` using **this exact template**:

```markdown
# Scenario Test Results
**Run Date:** {YYYY-MM-DD HH:MM IST}
**Total scenarios:** 32
**Passed:** {N}
**Failed:** {N}
**Skipped:** {N}
**Run duration:** {seconds}

---

## Executive Summary

{2-3 sentences: overall pass rate, critical findings, top recommendation}

## Pass Rate by Category

| Category | Total | Passed | Failed | Skipped | Pass % |
|---|---|---|---|---|---|
| HP (Happy Path) | 4 | x | x | x | xx% |
| RM (Risk Management) | 6 | x | x | x | xx% |
| DD (Drawdown) | 4 | x | x | x | xx% |
| MC (Market Conditions) | 5 | x | x | x | xx% |
| SF (System Failures) | 5 | x | x | x | xx% |
| OP (Operator/HITL) | 3 | x | x | x | xx% |
| LC (Lifecycle) | 3 | x | x | x | xx% |
| EC (Edge Cases) | 2 | x | x | x | xx% |
| **Total** | **32** | **x** | **x** | **x** | **xx%** |

## Critical Findings

{Numbered list of the 3-5 most important findings. Highlight scenarios where:
 - Risk Guard failed to halt
 - Re-entry permitted incorrectly
 - Deterministic engine path called LLM (regression)
 - Audit log inconsistency}

## Detailed Results — Per Scenario

### SC-HP-01: Clean Win — Target Hit
- **Status:** PASS / FAIL / SKIP
- **Duration:** xx ms
- **Asserts checked:** N/M passed
- **If FAIL — Root cause:** {one of: production_gap | test_bug | mock_setup | flaky}
- **Evidence:**
  - Final market_state: `{...}`
  - JSONL written: `{...}`
  - Telegram messages: `[...]`
  - Agent order: `[...]`
- **Notes:** {anything unusual}

### SC-HP-02: ...
{repeat for all 32}

## Failed Scenario Root Cause Distribution

| Root Cause | Count | Examples |
|---|---|---|
| production_gap (real gap in code) | x | HP-04 (event_calendar broken) |
| test_bug (test setup error) | x | ... |
| mock_setup (LLM mock too rigid) | x | ... |
| flaky (timing/race) | x | ... |

## Coverage Map: Spec vs. Test

| Spec Requirement | Covered by Scenario | Status |
|---|---|---|
| VIX gate < 20 | HP-03, EC-01 | ✅ |
| Event day skip | HP-04 | ❌ FAIL (production gap) |
| Daily SL ₹3,500 | RM-01 | {result} |
| Portfolio SL ₹4,500 | RM-03 | {result} |
| 30-day DD ₹30,000 | RM-04 | {result} |
| Free cash floor ₹11,000 | RM-05 | {result} |
| Burn rate 30%/10d | RM-06 | {result} |
| Re-entry max=1 | RM-02 | {result} |
| Hard kill: 2 consecutive SL | RM-02 | {result} |
| Hard kill: operator override | OP-01 | {result} |
| Real-time VIX (intraday) | MC-01 | ❌ FAIL (no Scanner loop) |
| Sentinel timeout fail-safe | SF-05 | ❌ FAIL (not implemented) |
| LLM tier failover | SF-03 | {result} |
| Month-to-date scoping | LC-01 | {result} |

## Recommendations for Claude

{Numbered, prioritized list. Tie each to a specific scenario.}

1. **CRITICAL — Fix `event_calendar.py`** (blocks HP-04, would trade on RBI day). Implement per PHASE_AUDIT_REPORT.md.
2. **CRITICAL — Implement Scanner real-time loop** (blocks MC-01, intraday VIX spikes invisible).
3. ...

## Files Created

- `/home/trading_ceo/antariksh/tests/scenario_runner.py` ({lines} lines)
- `/home/trading_ceo/antariksh/tests/test_scenarios.py` ({lines} lines)
- `/home/trading_ceo/antariksh/tests/fixtures/seed_history.py` ({lines} lines)
- `/home/trading_ceo/antariksh/tests/fixtures/mock_llm.py` ({lines} lines)
- `/home/trading_ceo/antariksh/tests/fixtures/mock_broker.py` ({lines} lines)
- `/home/trading_ceo/antariksh/tests/run_all.sh`
- `/home/trading_ceo/antariksh/tests/generate_report.py`

## Confidence Level

- **Harness correctness:** {High/Medium/Low} — {reason}
- **Coverage of spec:** {High/Medium/Low} — {reason}
- **Findings are real (not test bugs):** {High/Medium/Low} — {reason}

## Open Questions for Claude

{Things you weren't sure about while building. Examples:
 - "RM-03 portfolio SL — Phase 1 is NIFTY only; should this scenario be SKIP?"
 - "OP-02 timeout — what's the timeout duration? I assumed 30 min."
 - "MC-04 wide spread — what's the test for 'wide'? I checked 5% threshold."}

## Time Spent

- Phase A (harness): {hours} hr
- Phase B (32 tests): {hours} hr
- Phase C (run + report): {hours} hr
- Total: {hours} hr
```

---

## Success Criteria

You're done when ALL of these are true:

1. ✅ All 7 deliverable files exist (scenario_runner.py, test_scenarios.py, 3 fixtures, run_all.sh, generate_report.py)
2. ✅ All 32 test functions defined in `test_scenarios.py`
3. ✅ `./tests/run_all.sh` executes without crashing (individual tests may fail — that's data)
4. ✅ `SCENARIO_TEST_RESULTS.md` generated with all 32 scenarios reported
5. ✅ Each FAIL has a root cause classified (`production_gap | test_bug | mock_setup | flaky`)
6. ✅ At least 70% PASS rate (22+/32). Lower than that = harness bug, not production bug.
7. ✅ Critical scenarios (RM-01, RM-02, RM-04, RM-05) are PASS or have clear `production_gap` reason
8. ✅ Recommendations section in report is concrete (file paths + line numbers, not vague suggestions)

---

## Red Flags (What to Avoid)

❌ **Don't modify `crew_structure.py`, `phase1_mvs.py`, or `antariksh_rules.yaml` to make tests pass.** Document the gap in the report.

❌ **Don't mock `RiskGuardEngine`, `AuditorEngine`, or `ReEntryTracker`.** These are the safety logic — tests must verify them, not replace them.

❌ **Don't skip scenarios you find difficult.** Mark them SKIP with a reason. Skipping silently corrupts the coverage report.

❌ **Don't use real broker API calls.** Even read-only. Mock everything.

❌ **Don't write to real `logs/` directory.** Use `tempfile.mkdtemp()`.

❌ **Don't add new dependencies.** Use stdlib + pytest only. NO freezegun, NO mocker plugins.

❌ **Don't infer scenario behavior — read SCENARIO_TEST_PLAN.md.** Each scenario has explicit pass/fail criteria. Use those.

❌ **Don't hand-edit results.** The report must come from the actual `pytest` run, transformed by `generate_report.py`.

---

## Confusion? Reference These

| Question | Answer |
|---|---|
| "What does scenario X do?" | `SCENARIO_TEST_PLAN.md` — find the SC-XXX section |
| "How do I mock LLM for full crew test?" | `TESTING_INFRASTRUCTURE.md` §5 Pattern 1 |
| "How do I bypass crew for engine test?" | `TESTING_INFRASTRUCTURE.md` §5 Pattern 5 |
| "What's the JSONL schema?" | Read `crew_structure.py:336` (AuditorEngine) |
| "What's the L1 invariants list?" | `config/antariksh_rules.yaml` §kill_switches |
| "Where is market_state defined?" | `crew_structure.py:218` (approx) |
| "Why does HP-04 fail?" | `is_event_day()` returns False — see `phase1_mvs.py:115` |
| "What's the report template?" | This file, "How to Report Back" section above |

---

## Timeline for Claude's Resume

Sunday 2026-05-10 evening, Claude will:
1. Read `SCENARIO_TEST_RESULTS.md`
2. Verify report completeness against the template above
3. Triage findings by severity
4. Implement fixes for `production_gap` items (event_calendar.py, scanner loop, sentinel timeout)
5. Re-run failed tests after each fix
6. Compile a Phase 1 readiness checklist for Monday open

You don't need to wait for Claude. Once your report is written, your work is complete.

---

## Sign-Off

**This handoff is self-contained.** All context needed is in:
1. This file (the executable plan)
2. `SCENARIO_TEST_PLAN.md` (the WHAT)
3. `TESTING_INFRASTRUCTURE.md` (the HOW)
4. Existing source code (the system under test)

**If you find this handoff ambiguous, the source of truth precedence is:**
1. `config/antariksh_rules.yaml` (constitutional)
2. `STRATEGY_DESIGN_QUESTIONS.md` (canonical strategy)
3. `SCENARIO_TEST_PLAN.md` (scenario spec)
4. `TESTING_INFRASTRUCTURE.md` (mocking guide)
5. This handoff (task package)

**Author:** Claude (interim CEO)
**Receiver:** DeepSeek
**Status:** READY TO EXECUTE
