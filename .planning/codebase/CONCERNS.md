# CONCERNS.md — Technical Debt, Security Risks, Fragile Areas
**Generated:** 2026-05-09
**Scope:** Full codebase audit of `/home/trading_ceo/antariksh/`

---

## CRITICAL (Blocks Monday Live Trading or Exposes Secrets)

### 1. Hardcoded DeepSeek API Key in Source Code
**Severity:** CRITICAL
**File:** `crew_structure.py:35`
```
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-...REDACTED...")
```
A live DeepSeek API key is hardcoded as a fallback default. This key is visible in plaintext in the source file. If this repository is ever committed to a public remote, the key is leaked. The default value should be removed entirely — only environment variable sourcing should remain.

### 2. Event Calendar `is_event_day()` Stub — Would Trade on RBI Days
**Severity:** CRITICAL (BLOCKER #1 per `CRITICAL_FIXES_REQUIRED.md`)
**Files:** `crew_structure.py:62-63` (tool-level `scan_market()` checks mock env vars only, not `event_calendar.json`), `phase1_mvs.py:131-152` (FIXED on 2026-05-09 per `ISSUE_UPDATE_DeepSeek.md`)
- The CrewAI `crew_structure.py` `scan_market()` tool (lines 90-133) only reads `ANTARIKSH_MOCK_EVENT_DAY` env var — it never reads `config/event_calendar.json` for live event days.
- `phase1_mvs.py:MarketDataBridge.is_event_day()` was fixed on 2026-05-09 to read the JSON file (per `ISSUE_UPDATE_DeepSeek.md`), but the CrewAI path is NOT fixed.
- **Impact:** The CrewAI Phase 2 path would trade on RBI Monetary Policy days, Holidays, and Budget days. This is a production risk for any day between now and when the fix propagates to `crew_structure.py`.

### 3. ScenarioRunner MOCK_MODE Not Inherited by Crew Subprocess
**Severity:** CRITICAL (BLOCKER #2 per `CRITICAL_FIXES_REQUIRED.md`)
**File:** `tests/scenario_runner.py:33-34`
```python
os.environ.setdefault("ANTARIKSH_MOCK_MODE", "1")
```
Uses `setdefault` which means if the env var is already set (even to "0"), it won't override. Additionally, the crew `kickoff()` spawns subprocesses that may not inherit all env vars. The `run()` method (line 105-116) sets `ANTARIKSH_MOCK_MODE=1` but doesn't propagate `MOCK_VIX`, `MOCK_NIFTY`, `MOCK_TIME` to the environment the way `run_full_session()` expects.
- **Impact:** All 5 MC (Market Conditions) and 5 SF (System Failures) scenarios are marked NOTEST. Can't verify intraday dynamics before live trading.

### 4. RM-02 Re-Entry Cascade Test Missing Entirely
**Severity:** CRITICAL (BLOCKER #3 per `CRITICAL_FIXES_REQUIRED.md`)
**File:** `tests/test_scenarios.py` (test `test_RM_02_second_sl_hard_halt` exists at line 74 but per `DEEPSEEK_STATUS_LOG.md` was not verified)
- Per `SCENARIO_COVERAGE_AND_GAPS_ANALYSIS.md`, RM-02 was among 6 entirely missing scenarios.
- **Impact:** Can't verify that a second SL hit after re-entry triggers a hard halt and exhausts re-entry attempts.

### 5. No Cron Scheduler Actually Deployed
**Severity:** CRITICAL
**Evidence:** `DEEPSEEK_REPORT.md:135-143` explicitly documents this gap. The `scheduler/` directory contains only shell scripts (`run_phase1_9am.sh`, `run_phase1_2pm.sh`) but there is no evidence of crontab configuration. The `cron_simulator.py` is a simulator, not actual cron integration.
- **Impact:** System will NOT auto-run at 9:30 AM or 2:35 PM on Monday. Requires manual invocation unless crontab is configured.

### 6. MockLLM Never Wired Into Agents — 13 Scenarios Time Out
**Severity:** CRITICAL
**File:** `tests/fixtures/mock_llm.py:9` (class exists), `tests/scenario_runner.py:90-91` (stub `set_llm_responses` is a no-op `pass`)
- Per `diagnostic_pending_scenarios.md`, all 13 scenarios that call `crew.kickoff()` time out because the LLM calls to DeepSeek are real, not mocked. The `MockLLM` class was built but never patched into any agent.
- **Impact:** HP-01/02/03, MC-01→05, SF-01→05, LC-02, OP-03 are all untestable. Can't validate crew flow logic before Monday.

### 7. Order Execution Completely Stubbed — No Live Trading Possible
**Severity:** CRITICAL
**File:** `broker_manager.py:245, 259, 270, 272`
```python
logger.info(f"TODO: implement Flattrade {side} order for {qty} {instrument}")
return None
```
Both Flattrade and Shoonya `place_order()` methods return `None`. The `get_position()` method also returns `None`. The `Executor` agent in `crew_structure.py` (line 199-228, `execute_trade` tool) simulates fills with `"price": 0.0` and marks them as `"filled"`.
- **Impact:** In Phase 1 dry-run mode, this is expected. But if anyone tries to go live, orders will silently fail with no error. No safeguard against accidental live mode with stubbed execution.

---

## HIGH (Significant Risk to Operations)

### 8. Phase 2 Crews Not Built — All Empty Directories
**Severity:** HIGH
**Directories:** `agents/` (empty), `crews/` (empty), `autonomy/` (empty), `tools/` (empty), `hitl/` (empty)
- The `CHARTER.md` Phase 1 hire order (items 2-6) specifies building: HITL surface, Tool layer, Operations team (7 agents), Audit+reporting, Watchdog (systemd service), and stability soak.
- Per `CLAUDE_MASTER_HANDOFF.md`, only the core `crew_structure.py` (single Orchestrator+task model) exists. The 7 independent agent files (`agents/orchestrator.py`, etc.) were never created. The multi-crew daily/weekly/monthly compositions in `crews/` were never built.
- **Impact:** Phase 2 autonomous multi-agent system is still a single file with one agent orchestrating. The Phase 2 multi-crew architecture from `docs/Project_Varaha_CrewAI_Design.md` (sections 5-6: 3 crews — daily ops, weekly analysis, monthly governance) is entirely deferred.

### 9. Inter-Crew Communication Deferred
**Severity:** HIGH
**Evidence:** `DEEPSEEK_HANDOFF.md:13` — "Build during Claude's cooldown (~2-3 hours). Claude resumes to integrate + validate." The inter-crew communication patterns (Scanner→Strategist, Risk Guard↔Executor, Sentinel→Risk Guard) documented in `SCENARIO_COVERAGE_AND_GAPS_ANALYSIS.md:199-206` have ZERO test coverage.
- **Impact:** No scenario tests agent-to-agent interaction. The system has never been tested with two agents needing to coordinate.

### 10. Scanner Has No Real-Time Polling Loop
**Severity:** HIGH
**File:** `crew_structure.py:90-133` (single-shot `scan_market` tool)
- Per `diagnostic_pending_scenarios.md:114`, "No Scanner real-time polling loop exists. If VIX spikes at 11 AM, the system has no mechanism to detect and halt mid-session."
- MC-01 scenario (intraday VIX spike 15→22) is untestable because Scanner runs once at session start.
- **Impact:** The system cannot detect mid-session market regime changes. A VIX spike after entry time will go undetected until EOD.

### 11. Sentinel Has No Timeout Handling
**Severity:** HIGH
**File:** `crew_structure.py:231-260` (single-shot `monitor_positions` tool)
- Per `diagnostic_pending_scenarios.md:128`, "No Sentinel polling timeout mechanism." SF-05 scenario tests Sentinel network blackout but no timeout logic exists.
- The `monitor_positions` tool runs once and exits. There's no continuous polling loop, no timeout, no circuit breaker.
- **Impact:** If the broker network hangs, the monitoring function will hang indefinitely. No watchdog to detect this condition.

### 12. No LLM Provider Failover Implemented
**Severity:** HIGH
**Configuration:** `config/antariksh_rules.yaml:193-248` defines a sophisticated 3-tier fallback chain with circuit breaker, retry backoff, and prompt caching. But this is configuration only.
**File:** `crew_structure.py:35-43` — Only a single `deepseek_llm` is configured. No multi-provider LLM initialization exists.
- **Impact:** If DeepSeek API is down or rate-limited, the entire crew hangs. The failover chain exists on paper only.

### 13. Black-Scholes Backtester Uses Hardcoded Parameters
**Severity:** HIGH
**File:** `backtester.py:50-52`
```python
RISK_FREE_RATE = 0.06  # 6% annual
IMPLIED_VOL = 0.20     # 20% IV (typical for NIFTY)
DAYS_TO_EXPIRY = 7     # Weekly expiry
```
- IV is hardcoded at 20%, not read from market. Risk-free rate is hardcoded. Days to expiry is hardcoded.
- P&L calculations are therefore approximate. For dry-run Phase 1 this is acceptable. For live Phase 2, real IV and actual expiry dates must be used.

### 14. Duplicate CFO Auditor Implementations
**Severity:** HIGH
**Files:** `cfo_auditor.py:15-158` (Phase 1 CFOAuditor class with `log_session()`) and `crew_structure.py:349-491` (AuditorEngine class with `append_session()`)
- Two different CFO auditing implementations exist with slightly different schemas.
- `cfo_auditor.py` uses a singleton-based pattern with in-memory `cumulative_dd` tracking across sessions (line 94: `self.cumulative_dd += abs(min(pnl, 0))`).
- `crew_structure.py:AuditorEngine` reads from JSONL log files to calculate MTD.
- If both are used simultaneously (Phase 1 cron + Phase 2 crew), MTD calculations will diverge.
- **Impact:** Audit trail inconsistency. MTD P&L could be double-counted or missed.

### 15. market_state Is a Module-Level Global Mutable Dict
**Severity:** HIGH
**File:** `crew_structure.py:68-84`
```python
market_state: Dict = { ... }
```
- All agents read/write this single shared dict. No locking, no copy-on-write.
- `ScenarioRunner.__exit__()` (line 50-59) attempts to clean up env vars but doesn't fully reset `market_state` if an exception occurs during cleanup.
- If CrewAI ever parallelizes tasks, there's a data race on this dict.
- **Impact:** Tests can interfere with each other (known Gotcha #1 from `CLAUDE_MASTER_HANDOFF.md:324-325`). In production, concurrent agent access is undefined.

---

## MEDIUM (Operational or Architectural Concerns)

### 16. Event Calendar Schema Mismatch
**Severity:** MEDIUM
**Files:** `event_calendar.py:13-35` (flat list of tuples) vs `config/event_calendar.json` (nested `events_2026` dict with `skip_trading` boolean)
- `phase1_mvs.py:MarketDataBridge.is_event_day()` (line 131-152) reads from `config/event_calendar.json` with the nested schema (fixed 2026-05-09).
- `event_calendar.py:38-43` has its own `is_event_day()` using the flat list.
- If any code imports from `event_calendar.py` instead of `phase1_mvs.py:MarketDataBridge`, it gets the wrong behavior.
- The `crew_structure.py:scan_market()` tool doesn't read either — it only checks the mock env var.

### 17. Phase1Config Values Hardcoded, Not Loaded from rules.yaml
**Severity:** MEDIUM
**File:** `phase1_mvs.py:43-63`
```python
class Phase1Config:
    TARGET_PROFIT_INR = 1000
    MAX_LOSS_INIR = 3500
    FREE_CASH_FLOOR = 11000
    VIX_MAX = 20.0
    WING_WIDTH = 300
```
- The `config/antariksh_rules.yaml` file exists with canonical L3 parameters, but `phase1_mvs.py` and `crew_structure.py` hardcode their own copies.
- If `antariksh_rules.yaml` is updated, the runtime won't pick up the changes.
- **Impact:** Configuration drift. The YAML file is "write-protected" per its own docs but the code doesn't read it.

### 18. Telegram Bridge Depends on External picoclaw Installation
**Severity:** MEDIUM
**File:** `telegram_bridge.py:16-17`
```python
PICOCLAW_SCRIPT = Path("/root/.picoclaw") / "telegram_send.sh"
PICOCLAW_RPC = Path("/root/.picoclaw") / "rpc.py"
```
- If picoclaw is not installed at `/root/.picoclaw`, all Telegram messages fall back to console logging only (line 52-58).
- No error is raised — the system silently degrades.
- The `session_orchestrator.py` calls `TelegramBridge.send_alert("critical", ...)` (line 81) but if picoclaw is down, the Chairman never sees the alert.

### 19. Token Refresh Has Fragile Error Handling
**Severity:** MEDIUM
**File:** `token_refresh_dual.py:46, 93`
```python
timeout=120
```
- Both Flattrade and Shoonya refreshes have 120-second timeouts. No retry logic if the subprocess fails.
- Shownya refresh checks if `cred.yml` mtime < 300 seconds (line 114) — a heuristic that could give false positives if the file was touched for another reason.
- Flattrade refresh checks for `"client"` key (line 63) — if the token file schema changes, this check silently fails.
- Exit code is 0 if at least one broker succeeds (line 149) — a partial failure (one broker down) reports success to cron.

### 20. 6 Scenario Tests Still Missing
**Severity:** MEDIUM
**Files:** `tests/test_scenarios.py` (despite having 32 test functions, some are shallow stubs)
- Per `SCENARIO_COVERAGE_AND_GAPS_ANALYSIS.md:153-167`, the following were initially missing: HP-02, RM-02, RM-03, RM-06, DD-02, DD-04.
- Tests `test_HP_02_time_exit_no_target` (line 35), `test_RM_02_second_sl_hard_halt` (line 74), `test_RM_03_portfolio_sl_breach` (line 83), `test_RM_06_burn_rate_30pct` (line 104), `test_DD_02_10day_burn_boundary` (line 131), `test_DD_04_profit_factor_below_1` (line 146) now exist.
- Some of these are shallow: `test_HP_02` only asserts `gate_pass in (True, False)` which always passes. `test_DD_02` assertions are lenient.
- **Impact:** Coverage is formally 31/32 but assertion quality varies widely.

### 21. Zero Inter-Agent Conflict Scenario Tests
**Severity:** MEDIUM
**Evidence:** `SCENARIO_COVERAGE_AND_GAPS_ANALYSIS.md:294-363`
- No scenarios test what happens when two agents disagree (e.g., Strategist recommends ENTER but Risk Guard says HALT).
- No scenarios test multi-session MTD aggregation across JSONL files.
- No scenarios validate that halt flags persist across month boundaries.
- **Impact:** Production behavior in conflict situations is completely unknown.

### 22. LLM Token Costs Not Tracked or Enforced
**Severity:** MEDIUM
**Config:** `config/antariksh_rules.yaml:244-248` defines daily token soft budgets (₹50 default, ₹100 notification threshold).
**Files:** `phase1_mvs.py:388` — `"llm_tokens_approx": 500` is hardcoded, marked TODO. `crew_structure.py` has no token counting.
- The CFO Auditor's constitutional duty includes OpEx management ("tokens are cash" per `CHARTER.md:51`), but no mechanism exists to count or bill tokens.
- The `config/antariksh_rules.yaml:193-268` defines a sophisticated LLM tiering system, but no code implements it.
- **Impact:** If the system runs 10+ sessions a day, DeepSeek API costs are unknown and unbounded.

### 23. CFO Auditor Free Cash Value Hardcoded
**Severity:** MEDIUM
**File:** `cfo_auditor.py:103`
```python
free_cash = 100000  # Mock: ₹1L free cash in Phase 1
```
- The free cash floor is hardcoded at ₹100K in the CFO auditor, but `config/antariksh_rules.yaml:35` specifies `free_cash_inr_current: 100000` and `free_cash_floor_inr: 11000`.
- If free cash changes, the CFO auditor's DD ceiling calculation (line 104: `dd_ceiling = free_cash * self.MAX_DD_PERCENTAGE`) will be wrong.
- **Impact:** Burn-rate detection threshold silently drifts from config.

### 24. Schedule Shell Scripts Use `set -e`
**Severity:** MEDIUM
**Files:** `scheduler/run_phase1_9am.sh:6`, `scheduler/run_phase1_2pm.sh:6`
```bash
set -e  # Exit on error
```
- If `phase1_mvs.py` encounters any error (e.g., broker temporarily down, VIX fetch fails), the script exits immediately. No retry, no alert to Telegram, no graceful degradation.
- The `session_orchestrator.py` has try/except blocks (lines 50-77, 85-125) that catch exceptions and send Telegram alerts, but `set -e` may kill the process before those handlers run depending on how Python exits.

---

## LOW (Minor Concerns / Future Work)

### 25. Multiple TODO Markers in Production Code
**Severity:** LOW
**Files:**
- `phase1_mvs.py:207` — `# TODO: Implement signal calculation` (Layer 2 gate, supertrend_1min)
- `phase1_mvs.py:214` — `# TODO: Implement confirmation logic` (Layer 3 gate, multi-indicator)
- `phase1_mvs.py:289` — `# TODO: Implement Telegram API integration via picoclaw`
- `phase1_mvs.py:388` — `# TODO: track actual token usage`
- `phase1_mvs.py:417, 429-431` — Multiple TODOs in backtester for MTD tracking, win rate, max DD
- `exec_report.py:200-201` — `# TODO: Call picoclaw/Kubera RPC to send message`
- `broker_manager.py:245, 259, 270, 272` — Order placement/position TODOs
- **Impact:** Layer 2 and 3 gates are effectively pass-through (always return True), meaning the system only gates on Layer 1 (VIX + event day + time window). All multi-indicator confirmation is deferred.

### 26. Backtester Depends on scipy
**Severity:** LOW
**File:** `backtester.py:26, 35`
```python
from scipy.stats import norm
```
- scipy is a heavy dependency (~60MB) for just the normal CDF function. Could use `math.erfc` instead.
- If scipy is not installed, the entire backtester fails at import time (not at call time — the import is inside functions, but still required).
- **Impact:** Additional VPS disk usage and pip install failure risk.

### 27. Broker Manager Logs on Init — Potential Side Effects
**Severity:** LOW
**File:** `broker_manager.py:109-123`
- `BrokerManager.__init__()` tries to load Shoonya credentials and Flattrade token, and initializes the Shoonya API connection immediately.
- If brokers are down at import time, the singleton is created in a degraded state and never retries.
- **Impact:** A broker outage at 9:25 AM would persist all day even if broker recovers at 9:35 AM.

### 28. No Logging Configuration for Broker Manager
**Severity:** LOW
**File:** `broker_manager.py:26`
```python
logger = logging.getLogger("BrokerManager")
```
- The logger is created at module level but never configured. It relies on `phase1_mvs.py` or `crew_structure.py` to set up `logging.basicConfig` first.
- If `broker_manager.py` is imported before logging is configured, messages are silently dropped.
- **Impact:** Debugging broker connectivity issues in isolation is harder.

### 29. Crew Test File vs Scenario Tests — Two Testing Entry Points
**Severity:** LOW
**Files:** `crew_test.py` (265 lines) vs `tests/test_scenarios.py` (323 lines)
- `crew_test.py` has 4 basic tests (`test_1` through `test_4`) with CLI flags (`--mock-mode`, `--trace`, etc.).
- `tests/test_scenarios.py` has the 32-scenario test suite.
- The split is confusing — a developer might run `crew_test.py` and think everything is tested.
- Per `CLAUDE_MASTER_HANDOFF.md:146`, `crew_test.py` is an earlier, simpler test file. It should be deprecated in favor of the scenario framework.

### 30. Unused Ralph Loop Meta-Layer
**Severity:** LOW
**File:** `ralph/ralph_loop.py` (765 lines), `ralph/constitution.yaml`, `ralph/prds/` (6 PRD YAML files)
- The Ralph Loop is a meta-layer that wraps CrewAI agents in PRD-driven verification loops. It has a full scheduler, verification result dataclass, and CrewAI/PRD integration.
- Per `ralph/constitution.yaml:5`, effective date is "2026-05-12" — it's not yet active.
- No code in `crew_structure.py` or `session_orchestrator.py` references the Ralph Loop.
- **Impact:** 765 lines of code that are not wired in. Unclear whether this is Phase 2+ or an abandoned experiment.

### 31. JSONL Log Filename Inconsistency
**Severity:** LOW
**Files:**
- `cfo_auditor.py:57` — `f"cfo_audit_{session_date}.jsonl"` → produces `cfo_audit_2026-05-09.jsonl`
- `phase1_mvs.py:400` — `f"cfo_audit_{datetime.now().strftime('%Y%m%d')}.jsonl"` → produces `cfo_audit_20260509.jsonl`
- `crew_structure.py:456` — `f"cfo_audit_{session_date}.jsonl"` → produces `cfo_audit_2026-05-09.jsonl`
- Two different naming conventions (hyphen-separated vs compact) coexist in the logs directory.
- `AuditorEngine.read_phase1_logs()` (line 365-383) loads logs by date string — if the date format passed doesn't match the filename, logs are missed.
- **Impact:** Cross-component log reading may silently miss entries.

### 32. ReEntryTracker Reset Race Condition Potential
**Severity:** LOW
**File:** `crew_structure.py:647-650`
```python
@staticmethod
def reset_session():
    market_state["re_entries_used"] = 0
```
- `reset_session()` is called by `initialize_session()` (line 668) which is called by `ScenarioRunner.run()` (line 107).
- If `initialize_session()` is called multiple times in one session (e.g., retry logic), the re-entry counter is silently reset to 0, allowing unlimited re-entries.
- **Impact:** Low in Phase 1 (dry-run), but in Phase 2 live, a bug in the session lifecycle could bypass the 1-re-entry limit.

---

## Summary Table

| # | Concern | Severity | File(s) | Fixable Before Monday? |
|---|---------|----------|---------|----------------------|
| 1 | Hardcoded DeepSeek API key | CRITICAL | `crew_structure.py:35` | Yes (5 min) |
| 2 | `is_event_day()` stub in crew path | CRITICAL | `crew_structure.py:62-63` | Yes (30 min) |
| 3 | MOCK_MODE not inherited | CRITICAL | `tests/scenario_runner.py:33-34` | Yes (30 min) |
| 4 | RM-02 test missing | CRITICAL | `tests/test_scenarios.py:74` | Yes (exists, verify) |
| 5 | No cron deployed | CRITICAL | System crontab | Yes (10 min) |
| 6 | MockLLM not wired | CRITICAL | `tests/scenario_runner.py:90-91` | Yes (2 hrs) |
| 7 | Order execution stubbed | CRITICAL | `broker_manager.py:245-272` | No (Phase 2) |
| 8 | Phase 2 crews not built | HIGH | `agents/`, `crews/`, etc. | No (weeks) |
| 9 | Inter-crew comms deferred | HIGH | Multiple | No (weeks) |
| 10 | No Scanner real-time loop | HIGH | `crew_structure.py:90-133` | No (1 day) |
| 11 | No Sentinel timeout | HIGH | `crew_structure.py:231-260` | No (1 day) |
| 12 | No LLM provider failover | HIGH | `crew_structure.py:35-43` | No (1 day) |
| 13 | Hardcoded BS parameters | HIGH | `backtester.py:50-52` | No (Phase 2) |
| 14 | Duplicate CFO implementations | HIGH | `cfo_auditor.py`, `crew_structure.py` | No (refactor) |
| 15 | Global mutable market_state | HIGH | `crew_structure.py:68-84` | No (architectural) |
| 16 | Event calendar schema mismatch | MEDIUM | `event_calendar.py` vs JSON | Yes (dedup) |
| 17 | Config values hardcoded | MEDIUM | `phase1_mvs.py:43-63` | Yes (1 hr) |
| 18 | picoclaw dependency risk | MEDIUM | `telegram_bridge.py:16-17` | No (external) |
| 19 | Token refresh fragile | MEDIUM | `token_refresh_dual.py` | Yes (30 min) |
| 20 | Shallow test assertions | MEDIUM | `tests/test_scenarios.py` | Yes (1 hr) |
| 21 | No conflict scenarios | MEDIUM | Test suite | No (days) |
| 22 | LLM cost not tracked | MEDIUM | Multiple | No (Phase 2) |
| 23 | Free cash hardcoded | MEDIUM | `cfo_auditor.py:103` | Yes (5 min) |
| 24 | `set -e` in cron scripts | MEDIUM | `scheduler/*.sh` | Yes (5 min) |
| 25 | TODO markers in prod code | LOW | Multiple | Some (Phase 2) |
| 26 | scipy dependency | LOW | `backtester.py:26,35` | No (rewrite) |
| 27 | Broker init at import time | LOW | `broker_manager.py:109` | Yes (lazy init) |
| 28 | Unconfigured logger | LOW | `broker_manager.py:26` | Yes (5 min) |
| 29 | Two testing entry points | LOW | `crew_test.py` vs `tests/` | Yes (deprecate) |
| 30 | Unused Ralph Loop | LOW | `ralph/` | No (Phase 2+) |
| 31 | JSONL filename inconsistency | LOW | Multiple | Yes (standardize) |
| 32 | ReEntryTracker reset race | LOW | `crew_structure.py:647-650` | Yes (guard) |

---

## References
- `CRITICAL_FIXES_REQUIRED.md` — 3 blockers documented with copy-paste fixes
- `DEEPSEEK_STATUS_LOG.md` — Execution progress tracker (status: 0/3 blockers fixed as of writing)
- `diagnostic_pending_scenarios.md` — Root cause analysis of 13 timeout scenarios
- `CLAUDE_MASTER_HANDOFF.md` — Full project state handed off by Claude to DeepSeek
- `DEEPSEEK_HANDOFF.md` — Phase 2 CrewAI build instructions
- `DEEPSEEK_REPORT.md` — DeepSeek's build report with 7 "Notes for Claude" and missing items
- `SCENARIO_COVERAGE_AND_GAPS_ANALYSIS.md` — Comprehensive 629-line analysis of all 32 scenarios
- `ISSUE_UPDATE_DeepSeek.md` — HP-04 partial fix log (fixed in `phase1_mvs.py` but not in `crew_structure.py`)
