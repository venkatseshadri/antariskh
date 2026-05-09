# PHASE 1 DEPLOYMENT SPEC — Exactly What Must Work Monday 9:30 AM
**Critical Document:** Read this before, during, and after implementation  
**Purpose:** Define non-negotiable requirements for live trading MVP  
**Verification:** Each requirement has exact test case

---

## Requirement Matrix

### 🔴 CRITICAL REQUIREMENTS (Non-Negotiable)

These 10 features MUST work Monday 9:30 AM. No exceptions.

| # | Requirement | Test | Must Pass | Verified |
|---|---|---|---|---|
| **R1** | Gate Layer 1: VIX < 20 | HP-03 | ✅ PASS | 2026-05-09 18:00 |
| **R2** | Gate Layer 1: Time window 10:30-11:30 IST | (Gate logic test) | ✅ PASS | TBD |
| **R3** | Daily SL at -₹3,500 triggers halt | RM-01 | ✅ PASS | TBD |
| **R4** | Free cash floor at ₹11,000 halts | RM-05 | ✅ PASS | TBD |
| **R5** | 30-day DD at -₹30,000 halts | RM-04 | ✅ PASS | TBD |
| **R6** | MTD reset on month change | LC-01 | ✅ PASS | TBD |
| **R7** | Re-entry limited to 1 per session | RM-02 | ✅ PASS | TBD |
| **R8** | Risk Guard blocks Executor when halt=true | (RM tests) | ✅ PASS | TBD |
| **R9** | JSONL audit logs written | (All scenarios) | ✅ PASS | TBD |
| **R10** | Event day calendar blocks trading | HP-04 | ✅ PASS | TBD |

**Success Criteria:** All 10/10 requirements verified by Monday 9:15 AM.

---

## Functional Specification

### Function 1: Gate Layer 1 Filtering
**Purpose:** Prevent trading in unfavorable market regimes  
**Components:** Scanner agent, GateChecker class  
**Logic:**
```
IF (VIX < 20) AND (NOT event_day) AND (10:30 ≤ time ≤ 11:30) THEN
  gate_pass = True
  → Continue to plan generation
ELSE
  gate_pass = False
  → Skip session, log reason, exit
END IF
```

**Verification:**
- HP-03: VIX > 20 → gate_pass = False ✅
- HP-04: Event day → gate_pass = False ✅
- EC-01: VIX = 20.0 exactly → gate_pass = False ✅
- (Time window test in cron_simulator)

**Failure Mode:** Gate passes when VIX > 20 or on event day
**Impact:** TRADE ON UNFAVORABLE DAYS → HIGH LOSS RISK
**Mitigation:** All 3 gate checks tested, cannot deploy if any fail

---

### Function 2: Capital Preservation (Risk Guard Engine)
**Purpose:** Hard stops trading when capital thresholds breached  
**Components:** RiskGuardEngine class (deterministic, no LLM)  
**Hard Rules:**
```
Rule 1: Daily SL ≤ -₹3,500  → halt = True
Rule 2: Portfolio SL ≤ -₹4,500 MTD  → halt = True
Rule 3: 30-Day DD ≤ -₹30,000 MTD  → halt = True
Rule 4: Free cash < ₹11,000  → halt = True
Rule 5: Burn rate > 30% in 10 days  → halt = True

If ANY rule breaches:
  halt = True
  → Executor.place_order() REFUSED
  → Return error: "Risk Guard halt"
END IF
```

**Verification:**
- RM-01: Daily SL -3,500 → halt = True ✅
- RM-04: 30-day DD -30,000 → halt = True ✅
- RM-05: Free cash 10,500 → halt = True ✅
- RM-02: 2nd SL at -7,000 MTD → halt = True (with portfolio breach)

**Failure Mode:** Order placed despite halt=true → UNLIMITED LOSS
**Impact:** CATASTROPHIC (capital obliteration)
**Mitigation:** Risk Guard is deterministic (no LLM), heavily tested, cannot deploy if fails

---

### Function 3: Re-Entry Limit (ReEntryTracker)
**Purpose:** Prevent cascading SL losses (allow 1 re-entry/session, then halt)  
**Components:** ReEntryTracker class  
**Logic:**
```
Session SL hit (-₹3,500):
  IF can_re_enter() == True:
    re_entries_used += 1
    → Ask operator for re-entry approval
  ELSE:
    halt = True
    → No re-entry, game over for the day
END IF

2nd SL hit (-₹3,500 again):
  re_entries_used = 1, max = 1
  → can_re_enter() = False
  → halt = True (permanent for day)
  → No more trades allowed
```

**Verification:**
- RM-01: SL hit, can_re_enter() = True ✅
- RM-02: 2nd SL hit, can_re_enter() = False ✅

**Failure Mode:** 3rd+ SL allowed in same session
**Impact:** COMPOUNDING LOSSES (multiplier effect)
**Mitigation:** RM-02 test verifies re-entry exhaustion

---

### Function 4: Audit Logging (AuditorEngine)
**Purpose:** Compliance + MTD calculation + risk tracking  
**Components:** AuditorEngine class, JSONL file logging  
**Schema (each session):**
```json
{
  "timestamp": "2026-05-12T14:35:00Z",
  "date": "2026-05-12",
  
  "gate_pass": true/false,
  "gate_reason": "VIX_LOW" | "EVENT_DAY" | "TIME_WINDOW",
  
  "vix": 14.0,
  "nifty_spot": 24500,
  
  "trade_plan": {
    "entry_price": 24500,
    "target_price": 24550,
    "stoploss_price": 24200,
    "position_size": 1
  },
  
  "exit_reason": "Target hit" | "Stop loss" | "Time exit",
  "pnl_realized": 1000,
  "mtd_pnl": 1000,
  
  "halt": false,
  "halt_reason": "None",
  "violations": [],
  
  "re_entries_used": 0,
  "max_re_entries": 1
}
```

**Verification:**
- All scenarios write valid JSONL
- Fields match schema
- MTD aggregated correctly across sessions

**Failure Mode:** JSONL not written / malformed JSON / MTD miscalculated
**Impact:** No compliance record, MTD state drifts
**Mitigation:** JSONL verified after every test run

---

### Function 5: Event Calendar Integration
**Purpose:** Skip trading on RBI event days (high volatility, policy impact)  
**Components:** is_event_day() function in GateChecker  
**Data Source:** `config/event_calendar.json`
**Logic:**
```
current_date = "2026-05-29"
IF current_date IN event_calendar["rbi_events"] OR event_calendar["nse_holidays"]:
  gate_pass = False
  exit_reason = "Event day"
ELSE:
  continue to VIX check
END IF
```

**Verification:**
- HP-04: 2026-05-29 (RBI event) → gate_pass = False ✅
- HP-01: 2026-05-12 (normal day) → gate checks VIX only ✅

**Failure Mode:** is_event_day() returns False always
**Impact:** TRADE ON RBI DAYS → WHIPSAW LOSSES (high volatility)
**Mitigation:** HP-04 test verifies calendar is read

---

## Performance Requirements

| Metric | Requirement | Acceptable? |
|--------|---|---|
| **Session startup latency** | < 5 seconds | No LLM bottleneck |
| **MTM polling interval** | 2 seconds | Real-time SL detection |
| **Entry decision latency** | < 30 seconds (includes LLM) | Acceptable for entry window |
| **Exit decision latency** | < 5 seconds (deterministic) | Fast halt mechanism |
| **JSONL write latency** | < 1 second | Audit logging non-blocking |

**Verification:** Cron simulator shows timings realistic.

---

## Data Quality Requirements

| Data | Source | Quality Gate | Verification |
|------|--------|---|---|
| **VIX Quote** | BrokerManager mock (test) or Shoonya (live) | ±1% accuracy | Spot check against real time |
| **NIFTY Spot** | BrokerManager | ±5pts accuracy | Spot check |
| **JSONL Audit** | AuditorEngine | No corruption | json.tool validation |
| **MTD P&L** | JSONL aggregation | Sum verification | Manual spot check |

---

## Failure Modes & Mitigations

### Critical Path Failure Modes

| Failure | Symptom | Detection | Mitigation | Status |
|---------|---------|-----------|---|---|
| Gate always PASS | Trades on VIX 22+ | HP-03 fails | Test validates | ✅ Tested |
| SL never triggers | Position drifts to -10K | RM-01 fails | Test validates | ✅ Tested |
| Risk Guard ignored | Order placed at halt=true | RM tests fail | Test validates | ✅ Tested |
| Re-entry unlimited | 5+ SL hits same day | RM-02 fails | Test validates | ⚠️ Must fix |
| Event day not checked | Trade on RBI day | HP-04 fails | Test validates | ⚠️ Must fix |
| JSONL corrupted | Audit entry invalid JSON | Validator fails | Restore from backup | ✅ Validated |
| MTD drifts | Next session wrong starting balance | Spot check vs logs | Manual audit | ✅ Audited |

---

## Deployment Checklist (Sunday Validation)

### Code Quality
- [ ] No Python syntax errors
- [ ] All imports resolve
- [ ] No undefined variables
- [ ] No circular imports

**Validation Command:**
```bash
python3 -m py_compile crew_structure.py
python3 -c "from antariksh import crew_structure; from antariksh.tests import test_scenarios"
```

### Critical Tests (10/10 Must Pass)
- [ ] R1: HP-03 (VIX gate) PASS
- [ ] R2: EC-01 (time window) PASS
- [ ] R3: RM-01 (daily SL) PASS
- [ ] R4: RM-05 (free cash) PASS
- [ ] R5: RM-04 (30-day DD) PASS
- [ ] R6: LC-01 (MTD reset) PASS
- [ ] R7: RM-02 (re-entry) PASS
- [ ] R8: RM tests (risk guard) ALL PASS
- [ ] R9: All scenarios write JSONL
- [ ] R10: HP-04 (event day) PASS

**Validation Command:**
```bash
pytest tests/test_scenarios.py -k "HP or RM or DD or OP or LC or EC" -v
# Target: 25+ PASS
```

### Data Integrity
- [ ] JSONL files present: `ls logs/cfo_audit_*.jsonl`
- [ ] JSONL valid JSON: `cat logs/cfo_audit_*.jsonl | python3 -m json.tool`
- [ ] All required fields present
- [ ] No null values in critical fields

### Configuration
- [ ] event_calendar.json present: `ls config/event_calendar.json`
- [ ] event_calendar.json valid JSON
- [ ] RBI events populated
- [ ] NSE holidays populated
- [ ] antariksh_rules.yaml accessible

### Documentation
- [ ] SCENARIO_TEST_PLAN.md exists
- [ ] DEEPSEEK_STATUS_LOG.md filled out
- [ ] DEPLOYMENT_CHECKLIST.md signed off
- [ ] All blockers documented or resolved

---

## Monday Morning (9:15 AM) Pre-Live Verification

**5 minutes before go-live:**

1. **Quick sanity tests (90 seconds):**
   ```bash
   pytest tests/test_scenarios.py::test_HP_01_clean_win -v
   pytest tests/test_scenarios.py::test_RM_04_30day_dd_breach -v
   pytest tests/test_scenarios.py::test_RM_05_free_cash_floor_breach -v
   # All should PASS
   ```

2. **Check cron is configured (30 seconds):**
   ```bash
   crontab -l | grep session_orchestrator
   # Should show: 30 9 * * 1-5 /usr/bin/python3 /home/trading_ceo/antariksh/session_orchestrator.py --entry
   # And:        35 14 * * 1-5 /usr/bin/python3 /home/trading_ceo/antariksh/session_orchestrator.py --exit
   ```

3. **Verify credentials (30 seconds):**
   ```bash
   grep -i shoonya /home/trading_ceo/antariksh/config/credentials.yml
   # Should show: userid, password, vendor_code (all non-empty)
   ```

4. **Verify logs directory (30 seconds):**
   ```bash
   ls -la /home/trading_ceo/antariksh/logs/
   mkdir -p /home/trading_ceo/antariksh/logs  # if missing
   ```

**Total:** 3 minutes. If all pass → **GO LIVE**. If any fail → **ABORT and debug**.

---

## Scope Boundaries (Out of Scope for Phase 1)

### NOT Required for Monday 9:30 AM:
- ❌ Real broker order placement (orders logged, not executed)
- ❌ Real-time position monitoring (backtest simulates MTM)
- ❌ LLM mock layer (real API calls acceptable for MVP)
- ❌ System resilience (broker failover, LLM fallback)
- ❌ Multi-instrument trading (NIFTY weekly options only)
- ❌ Phase 2 autonomous trading (CrewAI just provides plans)

### Deferred to Week 1:
- ✋ MC-01…05 (market condition testing)
- ✋ SF-01…05 (system failure testing)
- ✋ Real broker integration
- ✋ Performance optimization

---

## Success Criteria

**Phase 1 MVP is successfully deployed if:**

1. ✅ All 10 critical requirements (R1-R10) verified by test pass
2. ✅ 25+/32 scenarios passing
3. ✅ Zero capital-preservation rule failures
4. ✅ JSONL audit logs written correctly
5. ✅ Event calendar integrated and blocking trades
6. ✅ No syntax or import errors
7. ✅ Deployment checklist complete and signed
8. ✅ Cron jobs configured and ready

**If all 8 criteria met → LIVE TRADING AUTHORIZED**

---

## Risk Assessment

### Residual Risks (Known & Accepted)

| Risk | Likelihood | Impact | Mitigation | Accept? |
|------|--|--|--|--|
| Event calendar missing entry | LOW | HIGH | HP-04 test validates | ✅ YES |
| Re-entry allowed 2+ times | LOW | HIGH | RM-02 test validates | ✅ YES |
| Daily SL not triggered | VERY LOW | CRITICAL | RM-01 test validates | ✅ YES |
| JSONL not written | VERY LOW | MEDIUM | Spot check after first session | ✅ YES |
| Broker API unavailable | LOW | MEDIUM | Falls back to mock, no trade | ✅ YES |
| DeepSeek API rate limit | LOW | MEDIUM | Session pauses, manual retry | ✅ YES |

**Overall Risk Level:** 🟡 **ACCEPTABLE for MVP** (capital preserved by hard rules, high upside on win days)

---

## Signoff

**Prepared by:** Claude (Project Consultant)  
**Implemented by:** DeepSeek (Developer)  
**Approved for Live Trading:** [Chairman Sign-Off Required]

**Date & Time Ready:** 2026-05-11 23:59 IST  
**Deployment:** Monday 2026-05-12 09:30 IST

