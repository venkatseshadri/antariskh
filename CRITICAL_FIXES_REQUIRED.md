# CRITICAL FIXES REQUIRED — Must Fix Before Monday 9:30 AM
**Status:** 3 blockers identified, 0 fixed  
**Impact:** All 3 block Monday live trading  
**Timeline:** 2 hours to fix all three  
**Priority:** DO FIRST before any other work

---

## BLOCKER #1: Event Calendar Check Broken (30 min to fix)

### The Problem
**File:** `crew_structure.py` (lines ~360-370, GateChecker.check_layer_1())

**Current Behavior:**
```python
def is_event_day(date: str) -> bool:
    # WRONG: Always returns False
    return False
```

**Result:** System will trade on RBI policy days. Monday test will fail (HP-04).

### The Evidence
**Test that fails:**
```bash
python3 -m pytest tests/test_scenarios.py::test_HP_04_gate_skip_event_day -v
```

Output:
```
FAILED — AssertionError: PRODUCTION GAP: event_day stub never blocks.
Gate was True (should be False on 2026-05-29 RBI event)
```

### The Fix (Copy-Paste Ready)

**Step 1:** Verify event calendar exists and has correct format
```bash
cat /home/trading_ceo/antariksh/config/event_calendar.json | python3 -m json.tool | head -30
```

Expected:
```json
{
  "rbi_events": [
    {"date": "2026-05-29", "name": "RBI Monetary Policy"},
    ...
  ],
  "nse_holidays": [...]
}
```

**Step 2:** Replace the `is_event_day()` function in `crew_structure.py`

Find and replace:
```python
# WRONG (current):
def is_event_day(date: str) -> bool:
    return False

# RIGHT (new):
def is_event_day(date: str) -> bool:
    """Check if date is RBI event day or NSE holiday."""
    import json
    from pathlib import Path
    
    try:
        config_file = Path(__file__).parent / "config" / "event_calendar.json"
        with open(config_file) as f:
            calendar = json.load(f)
        
        # Extract date from ISO format "2026-05-09" or "2026-05-09T10:30:00"
        date_str = date.split('T')[0] if 'T' in date else date
        
        # Check RBI events
        for event in calendar.get("rbi_events", []):
            if event.get("date") == date_str:
                return True
        
        # Check NSE holidays
        if date_str in calendar.get("nse_holidays", []):
            return True
        
        return False
    except Exception as e:
        # Log error but don't crash
        print(f"WARNING: is_event_day check failed: {e}")
        return False
```

**Step 3:** Wire into gate check

Find `check_layer_1()` method and add event check AFTER VIX check:
```python
def check_layer_1(self, vix: float, nifty: float, current_time: str = None) -> dict:
    """Layer 1 gate: VIX, event day, time window."""
    
    # Existing VIX check
    if vix >= 20.0:
        return {"pass": False, "reason": "VIX >= 20"}
    
    # NEW: Add event day check
    # Extract current date from current_time or use today
    current_date = current_time.split('T')[0] if current_time and 'T' in current_time else current_time
    if is_event_day(current_date):
        return {"pass": False, "reason": f"Event day: {current_date}"}
    
    # Existing time window check
    if current_time:
        hour_min = current_time.split('T')[1][:5]  # Extract HH:MM
        if not (10:30 <= hour_min <= 11:30):
            return {"pass": False, "reason": "Outside entry window"}
    
    return {"pass": True}
```

**Step 4:** Test the fix
```bash
cd /home/trading_ceo/antariksh
python3 -m pytest tests/test_scenarios.py::test_HP_04_gate_skip_event_day -v
```

Expected output:
```
test_HP_04_gate_skip_event_day PASSED ✅
```

**Step 5:** Commit
```bash
git add crew_structure.py
git commit -m "[BLOCKER] Event Calendar: FIXED — is_event_day() reads config/event_calendar.json, HP-04 PASS"
```

### Verification Checklist
- [ ] Function reads event_calendar.json without error
- [ ] Returns True for 2026-05-29 (RBI event)
- [ ] Returns False for normal trading days
- [ ] HP-04 test passes
- [ ] No syntax errors

---

## BLOCKER #2: ScenarioRunner MOCK_MODE Not Inherited (30 min to fix)

### The Problem
**File:** `tests/scenario_runner.py` (lines ~50-80, __enter__ method)

**Current Behavior:**
```python
def __enter__(self):
    self.temp_dir = tempfile.mkdtemp()
    os.environ["LOG_DIR"] = self.temp_dir
    return self
    # Missing: ANTARIKSH_MOCK_MODE not set
```

**Result:** MC-01…05 tests marked NOTEST (can't verify intraday dynamics).

### The Evidence
**Test that's broken:**
```bash
python3 -m pytest tests/test_scenarios.py::test_MC_01_intraday_vix_spike -v
```

Output:
```
test_MC_01_intraday_vix_spike NOTEST
(reason: BrokerManager mock not triggered)
```

### The Fix (Copy-Paste Ready)

**Step 1:** Open `tests/scenario_runner.py`

**Step 2:** Find the `__enter__` method (around line 50-60). Should look like:
```python
def __enter__(self):
    self.temp_dir = tempfile.mkdtemp()
    os.environ["LOG_DIR"] = self.temp_dir
    return self
```

**Step 3:** Replace with:
```python
def __enter__(self):
    self.temp_dir = tempfile.mkdtemp()
    os.environ["LOG_DIR"] = self.temp_dir
    
    # CRITICAL FIX: Set mock mode so crew inherits it
    os.environ["ANTARIKSH_MOCK_MODE"] = "1"
    
    # Store original for potential restoration
    self._original_env = {}
    self._original_env["MOCK_MODE"] = os.environ.get("ANTARIKSH_MOCK_MODE_ORIG")
    
    return self
```

**Step 4:** Find the `run()` method (around line 70-100). Should start like:
```python
def run(self) -> Dict:
    """Execute the full session with all mocks/patches active."""
    result = crew.run_full_session(mock_mode=True)
    return result
```

**Step 5:** Replace with:
```python
def run(self) -> Dict:
    """Execute the full session with all mocks/patches active."""
    # Ensure mock mode is set in parent process
    os.environ["ANTARIKSH_MOCK_MODE"] = "1"
    
    # Set mock data if available
    if hasattr(self, 'mock_vix') and self.mock_vix is not None:
        os.environ["ANTARIKSH_MOCK_VIX"] = str(self.mock_vix)
    if hasattr(self, 'mock_nifty') and self.mock_nifty is not None:
        os.environ["ANTARIKSH_MOCK_NIFTY"] = str(self.mock_nifty)
    if hasattr(self, 'mock_time') and self.mock_time is not None:
        os.environ["ANTARIKSH_MOCK_TIME"] = self.mock_time
    
    # Now crew inherits all env vars from parent
    result = crew.run_full_session(mock_mode=True)
    
    return result
```

**Step 6:** Test the fix
```bash
python3 -m pytest tests/test_scenarios.py::test_MC_01_intraday_vix_spike -v
```

Expected output:
```
test_MC_01_intraday_vix_spike PASSED (or FAILED with error, not NOTEST)
```

Note: Test might still FAIL due to other issues, but it should RUN (not NOTEST).

**Step 7:** Commit
```bash
git add tests/scenario_runner.py
git commit -m "[BLOCKER] ScenarioRunner: FIXED — MOCK_MODE env inheritance, MC tests now testable"
```

### Verification Checklist
- [ ] __enter__ sets ANTARIKSH_MOCK_MODE=1
- [ ] run() sets MOCK_VIX, MOCK_NIFTY, MOCK_TIME in env
- [ ] MC-01 test runs (not NOTEST)
- [ ] No syntax errors

---

## BLOCKER #3: RM-02 Test Missing (1 hour to fix)

### The Problem
**File:** `tests/test_scenarios.py` (add new test function)

**Current Behavior:**
```bash
grep "def test_RM_02" /home/trading_ceo/antariksh/tests/test_scenarios.py
# Returns: nothing (test doesn't exist)
```

**Result:** Can't verify re-entry cascade. RM-02 scenario untestable.

### The Evidence
**What's missing:**
- test_RM_02_second_sl_hard_halt() function
- Tests that 2nd SL triggers halt
- Tests that re-entry attempt count exhausted
- Tests that ReEntryTracker blocks further entries

### The Fix (Copy-Paste Ready)

**Step 1:** Open `tests/test_scenarios.py`

**Step 2:** Find the RM-01 test (around line 100-120)
```bash
grep -n "def test_RM_01" /home/trading_ceo/antariksh/tests/test_scenarios.py
```

**Step 3:** After RM-01 test ends, add new test:
```python
def test_RM_02_second_sl_hard_halt():
    """RM-02: Second SL Hit → Hard Halt (re-entry attempts exhausted)."""
    crew.market_state["re_entries_used"] = 1
    crew.market_state["halt"] = False
    
    result = crew.RiskGuardEngine.full_check(session_pnl=-3500, mtd_pnl=-7000)
    
    assert result["halt"] is True, f"Second SL must trigger halt, got halt={result['halt']}"
    
    can_re = crew.ReEntryTracker.can_re_enter()
    assert can_re is False, f"Re-entry exhausted, expected False, got {can_re}"
    
    violations = result.get("violations", [])
    assert any("Portfolio SL" in v for v in violations), \
        f"Portfolio SL violation expected in {violations}"
```

**Step 4:** Test the fix
```bash
python3 -m pytest tests/test_scenarios.py::test_RM_02_second_sl_hard_halt -v
```

Expected output:
```
test_RM_02_second_sl_hard_halt PASSED ✅
```

**Step 5:** Commit
```bash
git add tests/test_scenarios.py
git commit -m "[TEST] RM-02 Re-entry Cascade: IMPLEMENTED — 2nd SL triggers hard halt + re-entry block"
```

### Verification Checklist
- [ ] test_RM_02_second_sl_hard_halt function exists
- [ ] Test imports ScenarioRunner correctly
- [ ] Test sets market_state properly
- [ ] Test calls RiskGuardEngine.full_check() with correct params
- [ ] Test assertions pass
- [ ] No syntax errors

---

## Verification: Run All Critical Tests

After all 3 fixes:
```bash
cd /home/trading_ceo/antariksh
python3 -m pytest tests/test_scenarios.py::test_HP_04_gate_skip_event_day \
                  tests/test_scenarios.py::test_MC_01_intraday_vix_spike \
                  tests/test_scenarios.py::test_RM_02_second_sl_hard_halt -v
```

Expected:
```
test_HP_04_gate_skip_event_day PASSED ✅
test_MC_01_intraday_vix_spike [PASSED or error, not NOTEST]
test_RM_02_second_sl_hard_halt PASSED ✅

====== 2-3 passed ======
```

---

## If You Get Stuck

### Error: "FileNotFoundError: config/event_calendar.json"
**Fix:** Check file exists:
```bash
ls -la /home/trading_ceo/antariksh/config/event_calendar.json
```

If missing, create it (should already exist from May 8 build).

### Error: "ModuleNotFoundError: No module named 'crew_structure'"
**Fix:** Add to Python path:
```bash
export PYTHONPATH=/home/trading_ceo:$PYTHONPATH
```

### Error: "test_RM_02 not found"
**Fix:** Did you save the file after adding the function? Yes? Run again:
```bash
python3 -m pytest tests/test_scenarios.py::test_RM_02_second_sl_hard_halt -v
```

### Test still FAILS even after fixes
**Steps:**
1. Read test error message carefully
2. Check what the test expects vs what code does
3. Compare with passing test (e.g., RM-01)
4. Add `print()` statements to debug
5. Document issue in DEEPSEEK_STATUS_LOG.md
6. Move on to next blocker (don't get stuck)

---

## Timeline

```
Now: Read this document
↓
30 min: Fix Blocker #1 (Event Calendar)
↓
30 min: Fix Blocker #2 (ScenarioRunner MOCK_MODE)
↓
1 hour: Fix Blocker #3 (RM-02 Test)
↓
Test all three: pytest (should all pass)
↓
Commit & move to next phase (DEEPSEEK_EXECUTION_PLAN.md PHASE 2)
```

**Total: 2 hours to unblock Monday live trading.**

Good luck! 🚀

