# DEEPSEEK EXECUTION PLAN — Step-by-Step Weekend Tasks
**For:** DeepSeek (Primary Developer)  
**Timeline:** Friday 10:00 AM → Sunday 11:59 PM IST  
**Target:** 8-10 hours focused work  
**Outcome:** All critical systems ready for Monday 9:30 AM live trading

---

## PHASE 1: CRITICAL BLOCKERS (2 Hours) — Do First

These three items MUST be fixed before anything else. They block Monday live trading.

---

### TASK 1.1: Fix Event Calendar Check (30 min)
**File:** `/home/trading_ceo/antariksh/crew_structure.py`  
**Lines:** ~335-380 (GateChecker class, check_layer_1 method)  
**Current Code:** 
```python
# Around line 360-370 — find this block:
def check_layer_1(self, vix: float, nifty: float, current_time: str = None) -> dict:
    """Layer 1 gate: VIX, event day, time window."""
    # ...
    # Find: if vix >= 20:  (or similar)
    # Find: if self.is_event_day(date):  or is_event_day(date) call
```

**Problem:** `is_event_day()` returns hardcoded `False` always. System will trade on RBI days.

**Solution:**
1. Open `config/event_calendar.json`
   ```bash
   cat /home/trading_ceo/antariksh/config/event_calendar.json | head -50
   ```
   Expected format:
   ```json
   {
     "rbi_events": [
       {"date": "2026-04-08", "name": "RBI Monetary Policy"},
       {"date": "2026-05-29", "name": "RBI Rate Decision"}
     ],
     "nse_holidays": [
       "2026-03-25",
       "2026-08-15"
     ]
   }
   ```

2. In `crew_structure.py`, find the `is_event_day()` function (or add it if missing)
   ```python
   def is_event_day(date: str) -> bool:
       """Check if date is RBI event or NSE holiday."""
       import json
       from pathlib import Path
       
       config_file = Path(__file__).parent / "config" / "event_calendar.json"
       with open(config_file) as f:
           calendar = json.load(f)
       
       # Extract date from ISO format "2026-05-09"
       date_str = date.split('T')[0] if 'T' in date else date
       
       # Check RBI events
       for event in calendar.get("rbi_events", []):
           if event["date"] == date_str:
               return True
       
       # Check NSE holidays
       if date_str in calendar.get("nse_holidays", []):
           return True
       
       return False
   ```

3. Wire into gate check. Find where gate evaluates VIX and add event check:
   ```python
   # In check_layer_1() method, add:
   if is_event_day(current_date):
       return {"pass": False, "reason": "Event day"}
   ```

4. **Test:**
   ```bash
   cd /home/trading_ceo/antariksh
   python3 -m pytest tests/test_scenarios.py::test_HP_04_gate_skip_event_day -v
   ```
   Expected: ✅ PASS (test passes because is_event_day() now works)

5. **Commit:**
   ```bash
   git add -A
   git commit -m "[BLOCKER] Event Calendar: FIXED — is_event_day() reads config/event_calendar.json, HP-04 PASS"
   ```

**Validation:** HP-04 test passes. System refuses to trade on 2026-05-29 (RBI event).

---

### TASK 1.2: Fix ScenarioRunner MOCK_MODE Inheritance (30 min)
**File:** `/home/trading_ceo/antariksh/tests/scenario_runner.py`  
**Lines:** ~50-70 (__enter__ method)  
**Problem:** `os.environ["ANTARIKSH_MOCK_MODE"] = "1"` is set but not inherited by crew subprocess. MC tests marked NOTEST.

**Solution:**
1. Read current `scenario_runner.py`:
   ```bash
   head -80 /home/trading_ceo/antariksh/tests/scenario_runner.py
   ```

2. Find the `__enter__` method. Should look like:
   ```python
   def __enter__(self):
       self.temp_dir = tempfile.mkdtemp()
       os.environ["LOG_DIR"] = self.temp_dir
       return self
   ```

3. Add MOCK_MODE setup:
   ```python
   def __enter__(self):
       self.temp_dir = tempfile.mkdtemp()
       os.environ["LOG_DIR"] = self.temp_dir
       
       # FIX: Set mock mode in parent environment so crew inherits it
       os.environ["ANTARIKSH_MOCK_MODE"] = "1"
       
       # Store original values for restoration in __exit__
       self._original_mock_mode = os.environ.get("ANTARIKSH_MOCK_MODE_ORIG")
       
       return self
   ```

4. In `run()` method, ensure env vars are set:
   ```python
   def run(self) -> Dict:
       """Execute the full session with all mocks/patches active."""
       # Ensure mock mode is active in parent before invoking crew
       os.environ["ANTARIKSH_MOCK_MODE"] = "1"
       if hasattr(self, 'mock_vix'):
           os.environ["ANTARIKSH_MOCK_VIX"] = str(self.mock_vix)
       if hasattr(self, 'mock_nifty'):
           os.environ["ANTARIKSH_MOCK_NIFTY"] = str(self.mock_nifty)
       
       # Now invoke crew — it inherits env vars from parent
       result = crew.run_full_session(mock_mode=True)
       return result
   ```

5. **Test:**
   ```bash
   python3 -m pytest tests/test_scenarios.py::test_MC_01_intraday_vix_spike -v
   ```
   Expected: ✅ Test runs (either PASS or FAIL, not NOTEST)

6. **Commit:**
   ```bash
   git commit -m "[BLOCKER] ScenarioRunner: FIXED — MOCK_MODE env inheritance, MC tests now testable"
   ```

**Validation:** MC-01 test runs (passes or fails, but not NOTEST).

---

### TASK 1.3: Implement RM-02 Re-entry Cascade Test (1 hour)
**File:** `/home/trading_ceo/antariksh/tests/test_scenarios.py`  
**Lines:** After test_RM_01, add new function  
**Purpose:** Verify system halts after 2nd SL hit during re-entry.

**Solution:**
1. Find where RM-01 test ends (around line 100-120 in test_scenarios.py)
   ```bash
   grep -n "def test_RM_01\|def test_RM_02\|def test_RM_03" /home/trading_ceo/antariksh/tests/test_scenarios.py
   ```

2. Add new test after RM-01:
   ```python
   def test_RM_02_second_sl_hard_halt():
       """RM-02: Second SL Hit → Hard Halt (re-entry attempts exhausted)."""
       # Setup: first SL already hit, re-entry approved
       crew.market_state["re_entries_used"] = 1  # After first re-entry
       crew.market_state["halt"] = False
       
       # Simulate 2nd SL (cumulative MTD = -7000, session = -3500)
       result = crew.RiskGuardEngine.full_check(
           session_pnl=-3500, 
           mtd_pnl=-7000  # -3500 from first SL + -3500 from second SL
       )
       
       # Assert 1: Halt must be triggered
       assert result["halt"] is True, f"Second SL must trigger halt, got {result['halt']}"
       
       # Assert 2: Re-entry must be blocked
       can_re = crew.ReEntryTracker.can_re_enter()
       assert can_re is False, f"Re-entry should be exhausted, got {can_re}"
       
       # Assert 3: Portfolio SL violation logged
       violations = result.get("violations", [])
       assert any("Portfolio SL" in v for v in violations), \
           f"Portfolio SL breach should be logged, got {violations}"
       
       # Assert 4: market_state updated
       assert crew.market_state.get("halt") is True, "market_state halt should be True"
   ```

3. **Test:**
   ```bash
   python3 -m pytest tests/test_scenarios.py::test_RM_02_second_sl_hard_halt -v
   ```
   Expected: ✅ PASS

4. **Commit:**
   ```bash
   git commit -m "[TEST] RM-02 Re-entry Cascade: IMPLEMENTED — 2nd SL triggers hard halt + re-entry block"
   ```

**Validation:** Test passes. System correctly prevents 3rd SL after 2 attempts.

---

## PHASE 2: STRONG RECOMMENDATIONS (3 Hours) — Do Next

These aren't blockers but provide critical test coverage. Do if time allows.

---

### TASK 2.1: Implement HP-02 Time Exit Test (1 hour)
**File:** `/home/trading_ceo/antariksh/tests/test_scenarios.py`  
**After:** HP-03 test  
**Purpose:** Verify hard 14:30 exit closes positions without target/SL hit.

**Implementation:**
```python
def test_HP_02_time_exit_no_target():
    """HP-02: Time Exit at 14:30 — No Target Hit. EOD hard exit fires."""
    with ScenarioRunner("HP-02") as sc:
        sc.set_time("2026-05-12T14:30:00")  # Exactly at hard exit time
        sc.set_market(vix=13.0, nifty=24600.0)  # Within range, no target hit
        sc.seed_history(days=0)
        
        result = sc.run()
        
        # Assert 1: Gate passed (normal market)
        assert crew.market_state.get("gate_pass") is True, "Gate should PASS at normal VIX"
        
        # Assert 2: Exit reason is TIME, not TARGET or SL
        exit_reason = crew.market_state.get("exit_reason", "")
        assert "time" in exit_reason.lower() or "14:30" in exit_reason.lower(), \
            f"Exit should be time-based, got {exit_reason}"
        
        # Assert 3: P&L is positive (no SL), under target
        pnl = crew.market_state.get("pnl_realized", 0)
        assert 0 < pnl < 1000, f"P&L should be modest (0-1000), got {pnl}"
```

**Test:**
```bash
python3 -m pytest tests/test_scenarios.py::test_HP_02_time_exit_no_target -v
```
Expected: ✅ PASS

---

### TASK 2.2: Implement RM-03 Portfolio SL Test (1 hour)
**File:** `/home/trading_ceo/antariksh/tests/test_scenarios.py`  
**Purpose:** Verify multi-instrument cumulative SL works.

**Implementation:**
```python
def test_RM_03_portfolio_sl_breach():
    """RM-03: Portfolio SL Breach (₹4,500 cumulative)."""
    # Simulate two positions combined
    crew.market_state["positions"] = [
        {"instrument": "NIFTY", "mtm": -2500},
        {"instrument": "SENSEX", "mtm": -2000}
    ]
    
    result = crew.RiskGuardEngine.full_check(
        session_pnl=-4500,  # Combined MTM
        mtd_pnl=-4500
    )
    
    # Assert: Portfolio SL breach detected
    assert result["halt"] is True, "Portfolio SL -4500 must trigger halt"
    
    violations = result.get("violations", [])
    assert any("Portfolio" in v for v in violations), \
        f"Portfolio SL violation expected, got {violations}"
```

**Test:**
```bash
python3 -m pytest tests/test_scenarios.py::test_RM_03_portfolio_sl_breach -v
```
Expected: ✅ PASS

---

### TASK 2.3: Implement RM-06 Burn Rate Test (1 hour)
**File:** `/home/trading_ceo/antariksh/tests/test_scenarios.py`  
**Purpose:** Verify 10-day rolling burn rate calculation.

**Implementation:**
```python
def test_RM_06_burn_rate_30pct():
    """RM-06: Burn Rate — 30% of free cash lost in 10 days."""
    recent_pnls = [-300, -200, -400, -500, -350, -600, -400, -300, -500, -700]
    total_burn = abs(sum(p for p in recent_pnls if p < 0))  # = 3950
    burn_pct = total_burn / 11000  # = 35.9%
    
    result = crew.RiskGuardEngine.full_check(
        session_pnl=-500,
        mtd_pnl=-5000,
        recent_pnls=recent_pnls
    )
    
    # Assert: Burn rate >30% triggers halt
    assert result["halt"] is True, f"Burn rate 35.9% > 30%, should halt. Got halt={result['halt']}"
    
    checks = result.get("checks", {})
    assert "burn_rate" in checks, "Burn rate check should be present"
    
    violations = result.get("violations", [])
    assert any("Burn rate" in v for v in violations), \
        f"Burn rate violation expected, got {violations}"
```

**Test:**
```bash
python3 -m pytest tests/test_scenarios.py::test_RM_06_burn_rate_30pct -v
```
Expected: ✅ PASS

---

## PHASE 3: VALIDATION & TESTING (2 Hours) — Verify Everything

---

### TASK 3.1: Run Full Scenario Suite
**After all implementations, run complete test suite:**

```bash
cd /home/trading_ceo/antariksh
export PYTHONPATH=/home/trading_ceo:$PYTHONPATH
export ANTARIKSH_MOCK_MODE=1

# Full run
python3 -m pytest tests/test_scenarios.py -v --tb=short

# Expected output:
# ========= test session starts =========
# tests/test_scenarios.py::test_HP_01_clean_win PASSED
# tests/test_scenarios.py::test_HP_02_time_exit_no_target PASSED (if implemented)
# tests/test_scenarios.py::test_HP_03_gate_skip_high_vix PASSED
# tests/test_scenarios.py::test_HP_04_gate_skip_event_day PASSED (after fix)
# tests/test_scenarios.py::test_RM_01_session_sl_first_hit PASSED
# tests/test_scenarios.py::test_RM_02_second_sl_hard_halt PASSED (if implemented)
# tests/test_scenarios.py::test_RM_03_portfolio_sl_breach PASSED (if implemented)
# tests/test_scenarios.py::test_RM_04_30day_dd_breach PASSED
# tests/test_scenarios.py::test_RM_05_free_cash_floor_breach PASSED
# tests/test_scenarios.py::test_RM_06_burn_rate_30pct PASSED (if implemented)
# ... (more tests)
# ========= 25+ passed, 0 failed =========
```

**Target:** 25+ passing (25/32 = 78%)

**If any FAIL:**
1. Read test file to see what it expects
2. Check the implementation in crew_structure.py
3. Verify mock data is being set correctly
4. Add print statements to debug (e.g., `print(f"halt={result['halt']}")`)

---

### TASK 3.2: Verify JSONL Audit Logging
**Run a single happy-path test and check logs:**

```bash
python3 -m pytest tests/test_scenarios.py::test_HP_01_clean_win -v

# Check logs were written
ls -la /home/trading_ceo/antariksh/logs/

# Inspect JSONL entry
cat /home/trading_ceo/antariksh/logs/cfo_audit_2026-05-12.jsonl | python3 -m json.tool

# Expected format:
# {
#   "timestamp": "2026-05-12T10:30:00Z",
#   "gate_pass": true,
#   "vix": 14.0,
#   "trade_plan": {...},
#   "pnl": 1000,
#   "mtd_pnl": 1000,
#   "halt": false,
#   ...
# }
```

**Check:** All required fields present, valid JSON, no errors.

---

### TASK 3.3: Syntax & Import Validation
**Ensure no Python errors:**

```bash
python3 -c "import sys; sys.path.insert(0, '/home/trading_ceo'); from antariksh import crew_structure; print('✅ crew_structure imports OK')"

python3 -c "import sys; sys.path.insert(0, '/home/trading_ceo'); from antariksh.tests import scenario_runner; print('✅ scenario_runner imports OK')"

python3 -c "import sys; sys.path.insert(0, '/home/trading_ceo'); from antariksh.tests import test_scenarios; print('✅ test_scenarios imports OK')"
```

**Expected:** All three print ✅ messages.

---

## PHASE 4: DEPLOYMENT READINESS (1 Hour) — Final Checklist

---

### TASK 4.1: Create Deployment Checklist
**File:** `/home/trading_ceo/antariksh/DEPLOYMENT_CHECKLIST.md`  
**Content:**

```markdown
# Deployment Checklist — Monday 9:30 AM Live Trading

**Date:** 2026-05-09 (verified)  
**By:** DeepSeek  
**Status:** [IN_PROGRESS / COMPLETE]

## Pre-Deployment Checks

### Code Quality
- [ ] No Python syntax errors: `python3 -m py_compile crew_structure.py`
- [ ] All imports work: `python3 -c "from antariksh import crew_structure"`
- [ ] Tests run: `python3 -m pytest tests/test_scenarios.py -v`

### Critical Features (Must Pass)
- [ ] HP-04: Event day gate skip — TEST PASS
- [ ] RM-01: Daily SL at -₹3,500 — TEST PASS
- [ ] RM-04: 30-day DD at -₹30,000 — TEST PASS
- [ ] RM-05: Free cash floor at ₹11,000 — TEST PASS
- [ ] DD-01: 5 consecutive losses — TEST PASS
- [ ] LC-01: Month MTD reset — TEST PASS

### Test Coverage
- [ ] Total tests passing: 25+ / 32 (78%+)
- [ ] Risk management (RM): 5/6 passing
- [ ] Happy path (HP): 3/4 passing (HP-02 optional)
- [ ] No FAIL tests (all should be PASS or NOTEST)

### JSONL Logging
- [ ] Audit logs written: `ls -la logs/cfo_audit_*.jsonl`
- [ ] JSONL format valid: `python3 -m json.tool logs/cfo_audit_*.jsonl`
- [ ] Fields present: timestamp, gate_pass, pnl, mtd_pnl, halt, violations

### Configuration
- [ ] event_calendar.json loaded correctly
- [ ] antariksh_rules.yaml accessible
- [ ] broker_manager.py can instantiate
- [ ] telegram_bridge.py can instantiate

### Documentation
- [ ] SCENARIO_TEST_PLAN.md up-to-date
- [ ] DEEPSEEK_STATUS_LOG.md filled with completion details
- [ ] All blockers documented or fixed

## Monday Morning (9:15 AM)

- [ ] Run sanity tests:
  - `pytest tests/test_scenarios.py::test_HP_01_clean_win -v`
  - `pytest tests/test_scenarios.py::test_RM_04_30day_dd_breach -v`
  - `pytest tests/test_scenarios.py::test_RM_05_free_cash_floor_breach -v`

- [ ] Verify cron jobs are configured:
  - `crontab -l | grep session_orchestrator`

- [ ] Check broker credentials:
  - `grep -i "shoonya\|flattrade" config/credentials.yml`

## Approval

- [ ] All checks passed: YES / NO
- [ ] Ready for live trading: YES / NO
- [ ] Known issues documented: YES / NO

**Signed:** DeepSeek  
**Date:** 2026-05-09  
```

---

### TASK 4.2: Final Status Report
**File:** `/home/trading_ceo/antariksh/DEEPSEEK_STATUS_LOG.md`  
**Fill in completion details:**

```markdown
# DeepSeek Status Log — Weekend Execution

## Summary
- Total tasks: 7 (3 critical + 4 optional)
- Completed: [X] / 7
- Test pass rate: [X] / 32 (target: 25+)
- Blockers remaining: [X] / 0 (target: 0)

## Task Log

### [HH:MM] BLOCKER #1: Event Calendar
- Status: COMPLETED
- What: Implemented is_event_day() to read config/event_calendar.json
- Test: test_HP_04_gate_skip_event_day PASS ✅
- Commit: [hash] Event Calendar: FIXED

### [HH:MM] BLOCKER #2: ScenarioRunner MOCK_MODE
- Status: COMPLETED
- What: Fixed __enter__ to inherit MOCK_MODE to crew subprocess
- Test: test_MC_01_intraday_vix_spike now runs (not NOTEST)
- Commit: [hash] ScenarioRunner: FIXED

### [HH:MM] BLOCKER #3: RM-02 Re-entry Cascade
- Status: COMPLETED
- What: Implemented test_RM_02_second_sl_hard_halt()
- Test: test_RM_02_second_sl_hard_halt PASS ✅
- Commit: [hash] RM-02 Re-entry: IMPLEMENTED

### [HH:MM] OPTIONAL: HP-02 Time Exit
- Status: COMPLETED / SKIPPED
- What: [If done] Implemented test_HP_02_time_exit_no_target()
- Test: test_HP_02_time_exit_no_target PASS ✅

### [HH:MM] OPTIONAL: RM-03 Portfolio SL
- Status: COMPLETED / SKIPPED
- Test: test_RM_03_portfolio_sl_breach PASS ✅

### [HH:MM] OPTIONAL: RM-06 Burn Rate
- Status: COMPLETED / SKIPPED
- Test: test_RM_06_burn_rate_30pct PASS ✅

## Test Results

```
pytest tests/test_scenarios.py -v
====== 25+ passed ======
- HP: 3/4 passing (HP-02 optional)
- RM: 5/6 passing
- DD: 2/4 passing
- MC: 0/5 passing (NOTEST, can test with fix)
- SF: 0/5 passing (NOTEST, deferred to week 1)
- OP: 3/3 passing
- LC: 3/3 passing
- EC: 2/2 passing
```

## Known Issues & Workarounds

1. **MC-01…05 Tests (Market Conditions):**
   - Status: NOTEST (can be fixed but optional)
   - Reason: Broker mock needs finalization
   - Plan: Enable in week 1 if needed
   - Impact: Low (gate + risk rules already tested)

2. **SF-01…05 Tests (System Failures):**
   - Status: NOTEST (deferred)
   - Reason: Network/LLM/Cron injection not critical for MVP
   - Plan: Build in Phase 2
   - Impact: None (MVP doesn't require resilience test)

3. **DeepSeek API Calls in Tests:**
   - Status: Real API calls made (not mocked)
   - Reason: Test harness invokes real DeepSeek
   - Cost: ~60 sec for full suite
   - Plan: Mock in week 2 if needed

## Deployment Sign-Off

- Ready for Monday 9:30 AM live trading: **YES ✅**
- All critical features verified: **YES ✅**
- Documentation complete: **YES ✅**

---

**Completed:** 2026-05-09 23:55 IST  
**Verified by:** DeepSeek  
```

---

## PHASE 5: OPTIONAL ENHANCEMENTS (4 Hours) — If Extra Time

If you finish all critical + strong tasks with time remaining:

---

### TASK 5.1: Implement DD-02 & DD-04 (Boundary + Soft Kill)
**File:** `tests/test_scenarios.py`

**DD-02 — 10-Day Burn @ 30% Boundary:**
```python
def test_DD_02_10day_burn_boundary():
    """DD-02: 10-day boundary — exactly at 29% (just under 30% threshold)."""
    pnls = [-300]*10  # total -3000, 27.2% of 11000
    result = crew.RiskGuardEngine.full_check(
        session_pnl=-300,
        mtd_pnl=-3300,
        recent_pnls=pnls
    )
    checks = result.get("checks", {}).get("burn_rate", "")
    assert "OK" in checks or "WARNING" in checks, f"At 27% should NOT halt: {checks}"
```

**DD-04 — Profit Factor < 1.0:**
```python
def test_DD_04_profit_factor_below_1():
    """DD-04: Profit factor below 1.0 raises recommendation."""
    crew.market_state["mtd_pnl"] = -8000
    result = crew.RiskGuardEngine.full_check(session_pnl=-2000, mtd_pnl=-10000)
    recommendations = result.get("recommendations", [])
    # Soft-kill should be recommended but not hard halt
    assert result["halt"] is False, "Soft kill is warning, not hard halt"
```

---

### TASK 5.2: Complete MC-01…05 Broker Mock
**File:** `tests/scenario_runner.py`  
**Effort:** High, but enables entire market condition testing

See TESTING_INFRASTRUCTURE.md for details on broker stub implementation.

---

## Summary: What to Do Now

### This Minute
1. Read this entire document top-to-bottom
2. Understand the 3 critical blockers
3. Start with TASK 1.1 (Event Calendar)

### Next 2 Hours
- [ ] TASK 1.1: Event Calendar (30 min)
- [ ] TASK 1.2: ScenarioRunner MOCK_MODE (30 min)
- [ ] TASK 1.3: RM-02 Test (1 hour)
- [ ] Run full suite: `pytest tests/test_scenarios.py -v`

### Next 1-3 Hours (If Critical Tests Pass)
- [ ] TASK 2.1: HP-02 (1 hour)
- [ ] TASK 2.2: RM-03 (1 hour)
- [ ] TASK 2.3: RM-06 (1 hour)
- [ ] Re-run: `pytest tests/test_scenarios.py -v`

### Last 1 Hour
- [ ] TASK 3.1: Full validation
- [ ] TASK 3.2: JSONL verification
- [ ] TASK 3.3: Syntax check
- [ ] TASK 4.1: Deployment checklist
- [ ] TASK 4.2: Status report

### Success Looks Like
```bash
pytest tests/test_scenarios.py -v
...
========= 25 passed, 0 failed, 7 notest in 1.2s =========
```

Good luck! 🚀

