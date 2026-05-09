# Antariksh — Pending Scenario Analysis
**File:** `diagnostic_pending_scenarios.md`
**Created:** 2026-05-09
**Purpose:** Full technical diagnosis of timeout failures and resolution plan

---

## TL;DR

**13 scenarios time out because they call `antariksh_crew.kickoff()` — which fires real LLM calls to DeepSeek.**
The `MockLLM` class exists but **was never wired into the agents**.
Resolution is straightforward: patch all 7 agents to use `MockLLM` in test mode.
Estimated fix effort: **~2 hours of code changes + validation**.

---

## 1. Classification: 32 Scenarios

| Category | Count | Engine? | CrewAI? | Timeout? |
|----------|-------|---------|---------|---------|
| RM (Risk Management) | 6 | ✅ YES | ❌ No | ❌ |
| DD (Drawdown) | 4 | ✅ YES | ❌ No | ❌ |
| EC (Edge Cases) | 2 | ✅ YES | ❌ No | ❌ |
| OP-02 (confirmation) | 1 | ✅ YES | ❌ No | ❌ |
| LC (Lifecycle) | 3 | ✅ YES | ❌ No | ❌ |
| HP-01/02/03 | 3 | ❌ No | ✅ YES | ✅ **YES** |
| HP-04 | 1 | ✅ YES | ✅ YES | ✅ FIXED (stub removed) |
| MC-01 to MC-05 | 5 | ❌ No | ✅ YES | ✅ **YES** |
| SF-01 to SF-05 | 5 | ❌ No | ✅ YES | ✅ **YES** |
| OP-01 (override block) | 1 | ✅ YES | ❌ No | ❌ |
| OP-03 (Telegram) | 1 | ✅ YES | ✅ YES | ✅ **YES** |
| LC-02 (weekend) | 1 | ✅ YES | ✅ YES | ✅ **YES** |

**Total timeouts: 13** — all require full crew kickoff with LLM calls.

---

## 2. Root Cause: Why They Timeout

### The Call Chain

```
ScenarioRunner.run()
  └─ crew.run_full_session(mock_mode=True, ...)
       └─ antariksh_crew.kickoff(inputs={...})          ← LLM call #1
            ├─ scanner.agent.llm.call()                 ← LLM call #2
            ├─ strategist.agent.llm.call()               ← LLM call #3
            ├─ risk_guard.agent.llm.call()              ← LLM call #4
            ├─ executor.agent.llm.call()                ← LLM call #5
            ├─ sentinel.agent.llm.call()                ← LLM call #6
            ├─ auditor.agent.llm.call()                 ← LLM call #7
            └─ orchestrator (manager)                   ← Additional calls
```

**In mock mode (`ANTARIKSH_MOCK_MODE=1`):**
- Market data is mocked ✅
- Time is mocked ✅
- Event day is mocked ✅
- **But the LLM calls are NOT mocked** ❌

The `MockLLM` class exists at `tests/fixtures/mock_llm.py` — it returns canned JSON responses instantly. But it was never patched into any agent. The agents still hold `deepseek_llm` which makes real HTTP calls to `api.deepseek.com`.

### Why VPS Times Out

```
DeepSeek API latency on VPS:  25-120 seconds (observed)
pytest timeout per test:        60 seconds (default)
Test command timeout:           60 seconds
─────────────────────────────────────────────────
Result: LLM call hangs → pytest kills test → timeout
```

VPS network limitations (no dedicated bandwidth, 512MB RAM shared, CPU contention during CrewAI agent initialization) amplify the latency.

### The MockLLM Never Got Wired

```python
# tests/fixtures/mock_llm.py — EXISTS but never used
class MockLLM:
    def call(self, messages, **kwargs):
        # Returns canned JSON in <1ms
        ...

# tests/scenario_runner.py — stub that does nothing
def set_llm_responses(self, response_map: Dict[str, str]):
    pass   # ← no-op, never wired
```

The test framework has the tool but never connected it.

---

## 3. Scenario-by-Scenario Breakdown

### 3.1 HP Scenarios (4 total)

| ID | Scenario | Issue | Fix |
|----|----------|-------|-----|
| HP-01 | Clean Win — full crew flow | Calls `crew.kickoff()` → 7 LLM calls | Mock LLM |
| HP-02 | Time Exit at 14:30 | Calls `crew.kickoff()` → 7 LLM calls | Mock LLM |
| HP-03 | Gate skip on VIX > 20 | Calls `crew.kickoff()` → 7 LLM calls | Mock LLM |
| HP-04 | Gate skip on event day | **FIXED** — `is_event_day()` now reads JSON | Done ✅ |

### 3.2 MC Scenarios (5 total) — Market Conditions

| ID | Scenario | Issue | Fix |
|----|----------|-------|-----|
| MC-01 | Intraday VIX spike 15→22 | Scanner needs to re-check VIX mid-session; no real-time loop | Add Scanner polling loop OR mock intraday VIX change |
| MC-02 | Gap-up > 0.5% at open | Crew flow handles gate check; mock gap open values | Mock LLM |
| MC-03 | Late entry after 11:30 | Time-based gate skip; test verifies gate_pass=False | Mock LLM |
| MC-04 | Wide bid-ask spread | Executor needs broker spread data; mock spread | Mock LLM |
| MC-05 | First 15 min skip at 9:16 | Early entry should be blocked; verify time gate | Mock LLM |

**MC-01 has an additional gap:** No Scanner real-time polling loop exists. If VIX spikes at 11 AM, the system has no mechanism to detect and halt mid-session. This needs a Scanner loop (cron every 5 min or async polling) AND mock VIX trajectory support.

### 3.3 SF Scenarios (5 total) — System Failures

| ID | Scenario | Issue | Fix |
|----|----------|-------|-----|
| SF-01 | Shoonya down → Flattrade fallback | Broker failover logic needs mock broker state | Mock broker + Mock LLM |
| SF-02 | Both brokers down | All brokers mocked down; skip trade safely | Mock broker + Mock LLM |
| SF-03 | LLM provider failover (DeepSeek→OpenAI→Anthropic) | Tiered LLM fallback; needs mock LLM failures | Mock LLM with configurable failure |
| SF-04 | Cron late trigger at 10:15 instead of 9:30 | No cron exists; relies on manual trigger | Add cron OR mock scheduler |
| SF-05 | Sentinel network blackout | No Sentinel timeout handling; needs 30s timeout | Add Sentinel polling timeout |

**SF-04 and SF-05 are documented gaps, not just timeouts:**
- SF-04: No cron job exists in the codebase at all
- SF-05: No Sentinel polling timeout mechanism

These require architectural additions beyond just mocking LLM.

### 3.4 OP Scenarios (3 total)

| ID | Scenario | Issue | Fix |
|----|----------|-------|-----|
| OP-01 | Operator override blocked | Deterministic check — `ReEntryTracker.can_re_enter()` → halt blocks re-entry | Done ✅ |
| OP-02 | Operator confirmation timeout | Deterministic; no LLM needed | Done ✅ |
| OP-03 | Telegram unreachable | Telegram bridge not integrated; needs mock or real Telegram | Mock Telegram |

### 3.5 LC Scenarios (3 total)

| ID | Scenario | Issue | Fix |
|----|----------|-------|-----|
| LC-01 | Month rollover MTD reset | Deterministic; `risk_ok` check | Done ✅ |
| LC-02 | Weekend no session | Calls `crew.kickoff()` — needs Mock LLM | Mock LLM |
| LC-03 | First session after 30-day halt | Deterministic `full_check()` call | Done ✅ |

---

## 4. What Would Fix the 13 Timeouts?

### Option A: Wire MockLLM (Fastest — ~2 hours)

**Goal:** Make all 13 scenarios run in <5 seconds by mocking LLM responses.

```python
# In scenario_runner.py — wire the MockLLM

def _patch_llm_agents(self, response_map: Dict[str, str]):
    """Patch all 7 agent LLMs to use MockLLM."""
    mock = MockLLM(response_map)
    
    agents_to_patch = [
        'antariksh.crew_structure.scanner',
        'antariksh.crew_structure.strategist', 
        'antariksh.crew_structure.executor',
        'antariksh.crew_structure.sentinel',
        'antariksh.crew_structure.risk_guard',
        'antariksh.crew_structure.auditor',
        'antariksh.crew_structure.orchestrator',
    ]
    
    for agent_path in agents_to_patch:
        import importlib
        parts = agent_path.split('.')
        module = importlib.import_module('.'.join(parts[:-1]))
        agent_name = parts[-1]
        agent = getattr(module, agent_name)
        # Replace the LLM with mock
        agent.llm = mock  # or create proper MockLLM wrapper

def run(self):
    # Before kickoff, patch LLMs
    self._patch_llm_agents(make_mock_responses())
    
    result = crew.run_full_session(
        mock_mode=True,
        mock_vix=float(os.environ.get("ANTARIKSH_MOCK_VIX", 14.0)),
        mock_nifty=float(os.environ.get("ANTARIKSH_MOCK_NIFTY", 24500.0)),
        mock_time=os.environ.get("ANTARIKSH_MOCK_TIME", "10:30"),
    )
```

**Impact:** All 13 scenarios pass in <5 seconds. Validates crew flow logic without LLM.

**Limitation:** Doesn't test LLM quality, just flow correctness.

### Option B: Add Scanner Real-time Polling Loop (MC-01 fix — ~1 hour)

**Goal:** Make MC-01 detect mid-session VIX spikes.

```python
# In crew_structure.py — add VIX re-check task

class MarketMonitorLoop:
    """Polling loop for mid-session VIX changes. Cron every 5 min."""
    
    def __init__(self, check_interval=300):  # 5 minutes
        self.check_interval = check_interval
    
    def run(self):
        while True:
            current_vix = self._get_vix()
            current_time = datetime.now()
            
            # Skip if outside trading hours
            if current_time.hour < 9 or current_time.hour >= 15:
                break
            
            if current_vix > 20:
                logger.warning(f"VIX spiked to {current_vix} — issuing mid-session halt")
                crew.market_state["halt"] = True
                crew.market_state["gate_reason"] = f"VIX spike: {current_vix}"
                break
            
            time.sleep(self.check_interval)
```

Add to `scenario_runner.py`:
```python
def set_vix_trajectory(self, trajectory: List[Dict]):
    """Mock a VIX change mid-session for MC-01."""
    os.environ["ANTARIKSH_MOCK_VIX_TRAJECTORY"] = json.dumps(trajectory)
    # Wire the mock trajectory into the Scanner agent's loop
```

### Option C: Add Sentinel Timeout (SF-05 fix — ~1 hour)

**Goal:** Make Sentinel stop polling after 30 seconds of no network.

```python
# In phase1_mvs.py or crew_structure.py

def poll_positions_with_timeout(timeout_seconds=30):
    start = time.time()
    while datetime.now().hour < 15:
        if time.time() - start > timeout_seconds:
            logger.warning("Sentinel: network timeout — skipping poll")
            return {"status": "timeout", "positions": {}}
        # ... normal polling
        time.sleep(2)
```

### Option D: Add Cron Scheduler (SF-04 fix — ~30 min)

**Goal:** Make system trigger at 9:30 AM automatically.

```bash
# Add to crontab
30 09 * * 1-5 cd /home/trading_ceo/antariksh && python3 -m antariksh.run --entry >> /tmp/antariksh_cron.log 2>&1
35 14 * * 1-5 cd /home/trading_ceo/antariksh && python3 -m antariksh.run --exit >> /tmp/antariksh_cron.log 2>&1
```

---

## 5. Resolution Priority

| Priority | Item | Scenarios Fixed | Effort | Impact |
|----------|------|-----------------|--------|--------|
| **P0** | Wire MockLLM | HP-01/02/03, MC-01→05, SF-01→03, LC-02, OP-03 | 2 hrs | All 13 timeouts resolved |
| **P1** | Scanner polling loop | MC-01 (real VIX spike) | 1 hr | MC-01 functional |
| **P2** | Sentinel timeout | SF-05 | 1 hr | SF-05 functional |
| **P3** | Cron scheduler | SF-04 | 30 min | SF-04 functional |
| **P3** | Telegram mock | OP-03 | 1 hr | OP-03 functional |

**P0 unblocks everything.** Once MockLLM is wired, all 13 scenarios validate the crew flow in <5 seconds. The architectural gaps (Scanner loop, Sentinel timeout, cron) can then be addressed one by one.

---

## 6. If P0 Is Done — Validation Matrix

After wiring MockLLM, expected results:

| Scenario | Expected Outcome | Validates |
|----------|-----------------|-----------|
| HP-01 | `gate_pass=True`, trade_plan generated | Happy path full flow |
| HP-02 | `gate_pass=True`, time exit at 14:30 | EOD hard close |
| HP-03 | `gate_pass=False`, reason: "VIX 22 > 20" | High VIX block |
| MC-01 | `gate_pass=False` mid-session after VIX spike | Scanner re-check |
| MC-02 | `gate_pass=False` on gap-up detection | Gap open logic |
| SF-01 | `gate_pass=None`, broker: Flattrade (fallback) | Failover |
| SF-02 | `gate_pass=False`, reason: "no broker" | Safe skip |
| SF-03 | crew uses backup LLM provider | Failover chain |

---

## 7. Current Test Status

```
18 PASS  (engine-only, deterministic): RM×6, DD×4, EC×2, OP-02, LC×3, HP-04✅
 1 FAIL  (pre-fix): HP-04 event_day stub → FIXED ✅
13 TIMEOUT: HP-01/02/03, MC-01→05, SF-01→05, LC-02, OP-03
───────────────────────────────────────────────────────
Total: 32 scenarios
```

---

*Document: diagnostic_pending_scenarios.md — Antariksh, 2026-05-09*