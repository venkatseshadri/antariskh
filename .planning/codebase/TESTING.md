# Antariksh Testing Patterns

**Generated:** 2026-05-09  
**Scope:** All tests under `/home/trading_ceo/antariksh/tests/` + sibling test files

---

## 1. Test Framework

### Primary: **pytest** with `pytest-json-report` plugin

**Evidence:** `tests/run_all.sh:9-12` runs `python3 -m pytest` with `--json-report` flag.

No `pytest.ini`, `pyproject.toml`, `setup.cfg`, or `conftest.py` exists in the repo. Configuration is inline in the shell script.

### Manual test files (argparse-driven, not pytest)
- `crew_test.py` — four named test functions (`test_1_mock_crew_dryrun`, `test_2_task_dependencies`, `test_3_risk_guard_halt`, `test_4_gate_skip_high_vix`), run with `--mock-mode`, `--vix`, `--nifty`, `--time`, `--all` flags
- `test_full_scenario.py` — standalone e2e script (`test_scenario_pass()`), no test framework

---

## 2. Running Tests

### Full suite (32 scenario tests)
```bash
cd /home/trading_ceo/antariksh && bash tests/run_all.sh
```
This script (`tests/run_all.sh:1-16`):
1. Exports `ANTARIKSH_MOCK_MODE=1`, sets `PYTHONPATH`
2. Runs `python3 -m pytest tests/test_scenarios.py --tb=short --json-report --json-report-file=tests/results.json -v`
3. Pipes output to `tests/run.log`
4. Generates `SCENARIO_TEST_RESULTS.md` via `tests/generate_report.py`

### Individual test file
```bash
python3 -m pytest tests/test_scenarios.py -v
python3 -m pytest tests/test_scenarios.py -v -k "test_RM_"   # Risk Management only
python3 -m pytest tests/test_scenarios.py -v -k "test_HP_"   # Happy Path only
```

### Manual crew tests
```bash
python3 crew_test.py --all                           # All 4 manual tests
python3 crew_test.py --mock-mode --vix 18.5          # Dry-run
python3 crew_test.py --capital-floor-breach          # Risk halt test
python3 crew_test.py --high-vix                      # Gate skip test
```

### Single scenario e2e
```bash
python3 test_full_scenario.py                        # Gate pass → backtest → exit
```

---

## 3. Test Directory Structure

```
tests/
├── scenario_runner.py       # Context manager (210 lines) — mock injection into crew_structure
├── test_scenarios.py        # 32 scenario tests (323 lines) — 8 categories
├── generate_report.py       # Pytest JSON → Markdown reporter (255 lines)
├── run_all.sh               # Bash runner script (16 lines)
├── run.log                  # Last run output
├── results.json             # Last pytest-json-report output
└── fixtures/
    ├── __init__.py           # Package marker (1 line)
    ├── mock_llm.py           # Canned LLM response map (66 lines)
    ├── mock_broker.py        # Env-var MockBrokerManager (44 lines)
    └── seed_history.py       # Synthetic JSONL fixture generators (114 lines)
```

---

## 4. Test Patterns

### Pattern A: ScenarioRunner context manager (CrewAI integration tests)

```python
def test_HP_01_clean_win():
    """HP-01: Clean Win — Target Hit. Gate → plan → entry → target → exit → audit."""
    with ScenarioRunner("HP-01") as sc:
        sc.set_time("2026-05-12T10:30:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        sc.seed_history(days=0)
        result = sc.run()
        gate = crew.market_state.get("gate_pass", False)
        assert gate in (True, False), f"Gate check ran: {gate}"
```
(`tests/test_scenarios.py:25-33`)

**ScenarioRunner** (`tests/scenario_runner.py:21-166`):
- `__enter__`: Sets `ANTARIKSH_MOCK_MODE=1`, redirects `AuditorEngine.AUDIT_DIR` to temp dir, resets `market_state`
- `__exit__`: Stops all patches, restores env, removes temp dir
- Setup methods: `set_time()`, `set_market()`, `set_pnl_trajectory()`, `seed_history()`, `set_llm_responses()`, `set_event_day()`, `set_vix_trajectory()`, `set_sentinel_blackout()`
- Execution: `run()` → calls `crew.run_full_session(mock_mode=True, ...)`, returns `market_state` + return value
- `run_engine_only(engine_name)` → bypasses CrewAI, hits `RiskGuardEngine.full_check()` / `AuditorEngine` / `ReEntryTracker` directly
- Assertion methods: `assert_state()`, `assert_jsonl()`, `assert_telegram_contains()`, `assert_agent_order()`, `assert_no_llm_in()`

### Pattern B: Engine-only tests (fast, deterministic, no LLM)

```python
def test_RM_01_session_sl_first_hit():
    result = crew.RiskGuardEngine.full_check(session_pnl=-3500, mtd_pnl=-3500)
    assert result["halt"] is True, "SL breach must trigger halt"
    violations = result.get("violations", [])
    assert any("Daily SL" in v for v in violations)
```
(`tests/test_scenarios.py:65-72`)

These bypass the ScenarioRunner entirely. Direct calls to:
- `crew.RiskGuardEngine.full_check(session_pnl=, mtd_pnl=, recent_pnls=)` — returns `{"passed": bool, "halt": bool, "violations": [], "checks": {}}`
- `crew.ReEntryTracker.can_re_enter()` — returns `bool`
- `crew.market_state[...]` — direct dict manipulation

### Pattern C: State injection + engine assertions

```python
# Pre-seed market_state for drawdown tests
crew.market_state["mtd_pnl"] = -17500
crew.market_state["re_entries_used"] = 0
crew.market_state["halt"] = False
result = crew.RiskGuardEngine.full_check(session_pnl=-3500, mtd_pnl=-21000)
assert result["halt"] is True
assert len(result["violations"]) >= 2
```
(`tests/test_scenarios.py:122-129`)

---

## 5. What the Tests Cover (32 Scenarios, 8 Categories)

| Category | Count | Test Pattern | What's Tested | Status |
|----------|-------|-------------|---------------|--------|
| **HP** (Happy Path) | 4 | ScenarioRunner | Gate pass, trade plan, exit, VIX/event skip | 1 engine-only pass, 3 CrewAI-pending |
| **RM** (Risk Management) | 6 | Engine-only | Daily SL, Portfolio SL, 30-day DD, Free cash, Burn rate, Re-entry gates | **6/6 PASS** |
| **DD** (Drawdown) | 4 | Engine-only | Consecutive losses, burn boundary, advancement, profit factor | **4/4 PASS** |
| **MC** (Market Conditions) | 5 | ScenarioRunner | VIX spike, gap open, late entry, spread, first 15min | 5 CrewAI-pending |
| **SF** (System Failures) | 5 | ScenarioRunner | Broker down, LLM failover, cron late, Sentinel blackout | 5 CrewAI-pending |
| **OP** (Operator/HITL) | 3 | Engine-only | Override blocked, timeout, Telegram unreachable | **3/3 PASS** |
| **LC** (Lifecycle) | 3 | Mixed | Month rollover, weekend, post-DD halt session | **3/3 PASS** |
| **EC** (Edge Cases) | 2 | Mixed | VIX at boundary, SL at race condition | **2/2 PASS** |

### Total: 19 of 32 pass at engine level (59%)
- **All 6 RM + 4 DD + 3 OP + 3 LC + 2 EC = 19 deterministic tests PASS**
- **13 CrewAI-dependent tests require full LLM execution** (timeout on VPS → marked "not tested" but framework ready)

---

## 6. Mocking Approach

### Layer 1: Environment variables (mock mode)
Tests set env vars like `ANTARIKSH_MOCK_MODE=1` and `ANTARIKSH_MOCK_VIX=14.0`. Production code checks these at runtime:
```python
MOCK_MODE = os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1"
```
(`crew_structure.py:60`, `broker_manager.py:105`)

### Layer 2: Fixture-based JSONL seeding
```python
from tests.fixtures.seed_history import seed_jsonl, seed_consecutive_losses, seed_30day_dd_at_threshold
```
(`tests/test_scenarios.py:16`)

These write synthetic `cfo_audit_{date}.jsonl` files to a temp directory, matching the exact schema used by `CFOAuditor.log_session()` and `AuditorEngine.read_phase1_logs()`.

Functions in `tests/fixtures/seed_history.py:12-114`:
- `seed_jsonl(log_dir, days_back, pnl_per_day)` — generic history
- `seed_consecutive_losses(log_dir, count, sl_amount)` — SL-hit days
- `seed_30day_dd_at_threshold(log_dir, target_mtd)` — 28 days summing to target

### Layer 3: MockBrokerManager (env-driven broker)
```python
class MockBrokerManager:
    def get_vix(self) -> float:
        return float(os.environ.get("ANTARIKSH_MOCK_VIX", "14.0"))
    def get_nifty_spot(self) -> float:
        return float(os.environ.get("ANTARIKSH_MOCK_NIFTY", "24500.0"))
```
(`tests/fixtures/mock_broker.py:11-20`) — captures orders for assertions.

### Layer 4: MockLLM (canned responses)
```python
class MockLLM:
    def call(self, messages, **kwargs):
        # Detect agent role from message content
        # Return canned response from response_map
```
(`tests/fixtures/mock_llm.py:9-46`) — `make_mock_responses()` generates standard responses for all 7 agents (`tests/fixtures/mock_llm.py:55-66`).

### Layer 5: Redirected audit directory
```python
crew.AuditorEngine.AUDIT_DIR = self._log_dir   # temp dir during test
```
(`tests/scenario_runner.py:37`) — isolates test JSONL from production logs.

### What's NEVER mocked (deterministic, verified)
- `RiskGuardEngine.full_check()` — capital math verified
- `AuditorEngine.calculate_mtd_from_logs()` — arithmetic verified
- `ReEntryTracker` — counter logic verified
- Black-Scholes in `backtester.py` — pure math, real

---

## 7. Known Gaps & Documented Production Gaps

The test file explicitly tags known gaps in comments and asserts:

```python
def test_HP_04_gate_skip_event_day():
    """HP-04: Gate SKIP on event day. KNOWN GAP — is_event_day() returns False."""
    ...
    assert gate is False, f"PRODUCTION GAP: event_day stub never blocks. Gate was {gate}"
```
(`tests/test_scenarios.py:51-59`)

Tagged gaps in `tests/generate_report.py:58-63`:
- `HP-04` — `gate is False` (event day blocking) → **production_gap**
- `MC-01` — intraday VIX spike (no Scanner loop) → **production_gap**
- `SF-04` — cron late trigger (no cron installed) → **production_gap**
- `SF-05` — Sentinel timeout (no timeout handling) → **production_gap**

---

## 8. Test Function Naming Convention

### Pattern: `test_{CATEGORY}_{NUMBER}_{descriptive_name}`
```
test_HP_01_clean_win
test_RM_01_session_sl_first_hit
test_DD_01_5_consecutive_losses
test_MC_01_intraday_vix_spike
test_SF_01_shoonya_down_flattrade_fallback
test_OP_01_operator_override_attempt_blocked
test_LC_01_month_rollover_mtd_reset
test_EC_01_vix_exactly_at_2000
```
(`tests/test_scenarios.py:25-323`)

Category codes: HP, RM, DD, MC, SF, OP, LC, EC

### Manual crew tests use: `test_{NUMBER}_{descriptive_name}`
```
test_1_mock_crew_dryrun
test_2_task_dependencies
test_3_risk_guard_halt
test_4_gate_skip_high_vix
```
(`crew_test.py:44-206`)

---

## 9. TDD Approach for Phase 2 (120 Tests Planned)

**Source:** `SCENARIO_TEST_PLAN.md` (not read in full, referenced by `TESTING_INFRASTRUCTURE.md`)

### Planned expansion from 32 → 120 scenarios
The 32 scenarios form the **Critical Scenario Matrix** — a min-viable sanity check before proceeding to Phase 2 (real money). These test the deterministic engines (RiskGuard, Auditor, ReEntry) plus the CrewAI integration contract.

### TDD workflow implied by existing patterns
1. **Write test first** — define scenario in `test_scenarios.py` using `ScenarioRunner` or engine-only pattern
2. **Seed history** if needed — `seed_jsonl()` or direct `market_state` injection
3. **Assert on state** — `crew.market_state.get(...)` or `result["halt"]`, `result["violations"]`
4. **Tag production gaps** — `KNOWN GAP` in test docstring + assert message
5. **Run with `tests/run_all.sh`** — generates `SCENARIO_TEST_RESULTS.md`
6. **Review generated report** — root cause distribution, category pass rates

### Engine-only test template (for new deterministic checks)
```python
def test_RM_XX_new_check_name():
    """RM-XX: Description of what's being tested."""
    crew.market_state["halt"] = False
    crew.market_state["..."] = ...  # seed state
    result = crew.RiskGuardEngine.full_check(session_pnl=..., mtd_pnl=...)
    assert result["halt"] is True  # or False
    violations = result.get("violations", [])
    assert any("Expected phrase" in v for v in violations)
```

### ScenarioRunner test template (for new CrewAI integration checks)
```python
def test_XX_XX_new_scenario():
    """XX-XX: Scenario description."""
    with ScenarioRunner("XX-XX") as sc:
        sc.set_time("2026-05-12T10:30:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        sc.seed_history(days=5)
        result = sc.run()
        assert crew.market_state.get("key") == expected_value
```

---

## 10. Test Reporting Pipeline

```
tests/test_scenarios.py
    │ pytest --json-report
    ▼
tests/results.json              (raw pytest JSON output)
    │ python3 tests/generate_report.py
    ▼
SCENARIO_TEST_RESULTS.md        (formatted Markdown report)
```

The report generator (`tests/generate_report.py:82-246`) outputs:
- Executive summary with pass %
- Category breakdown table (HP/RM/DD/MC/SF/OP/LC/EC)
- Critical findings (failures vs expected gaps)
- Per-scenario detailed results
- Root cause distribution table
- Actionable recommendations for the engineer

---

## 11. Assertion Style

### Simple assert with message string
```python
assert result["halt"] is True, "SL breach must trigger halt"
assert gate in (True, False), f"Gate check ran: {gate}"
assert result["halt"] is False, "Fresh month MTD should be safe"
```

### Violation-substring checking
```python
violations = result.get("violations", [])
assert any("Daily SL" in v for v in violations), f"Missing daily SL violation: {violations}"
assert any("Portfolio SL" in v for v in violations)
assert any("30-day DD" in v for v in violations)
assert any("Free cash" in v for v in violations)
assert any("Burn rate" in v for v in violations)
```
(`tests/test_scenarios.py:72-115`)

### Length-based assertions
```python
assert len(violations) >= 2, f"Expect >=2 violations for 5 consecutive losses: {violations}"
```

### Boolean check + content check
```python
checks = result.get("checks", {})
assert "burn_rate" in checks, "Burn rate check must run"
assert "OK" in checks or "WARNING" in checks
```

---

## 12. CI/CD

**No CI/CD pipeline exists.** Tests are run manually via `tests/run_all.sh`. The project is in Phase 1 (dress rehearsal, dry-run), so automated CI is not yet configured.

Cron jobs for production are simulated via `cron_simulator.py` (`cron_simulator.py:23-51` — 5 jobs: token_refresh, entry_gate, exit, exec_report_daily, exec_report_weekly).

---

## 13. Key Test Files Reference

| File | Lines | Purpose |
|------|-------|---------|
| `tests/test_scenarios.py` | 323 | 32 scenario tests, 8 categories |
| `tests/scenario_runner.py` | 166 | Context manager for mock injection |
| `tests/generate_report.py` | 255 | JSON → Markdown report generator |
| `tests/run_all.sh` | 16 | Bash test runner |
| `tests/fixtures/mock_llm.py` | 66 | Canned LLM responses |
| `tests/fixtures/mock_broker.py` | 44 | Env-var broker mock |
| `tests/fixtures/seed_history.py` | 114 | JSONL fixture generators |
| `tests/fixtures/__init__.py` | 1 | Package marker |
| `crew_test.py` | 261 | Manual crew test runner |
| `test_full_scenario.py` | 85 | Standalone e2e scenario |
