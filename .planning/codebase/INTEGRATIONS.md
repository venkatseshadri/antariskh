# Antariksh External Integrations

**Generated:** 2026-05-09
**Focus:** TECH — External APIs, broker connections, messaging, databases, auth, scheduling

---

## 1. Broker APIs

### 1.1 Shoonya (Primary Market Data)

**Definition:** `broker_manager.py:32-65` (class), `broker_manager.py:126-151` (API init)

**Library:** `api_helper.NorenApiPy` from sibling directory `/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/`

**Authentication:** OAuth header injection using credentials from `python-trader/Shoonya_oAuthAPI-py/cred.yml`
- Token type: `Access_token`, `UID`, `Account_ID` (YAML file)
- Auth flow: `broker_manager.py:136-139` — calls `shoonya_api.injectOAuthHeader(Access_token, UID, Account_ID)`
- Token refresh: `token_refresh_dual.py:79-128` — runs `GetAuthcode.py` via subprocess, verifies cred.yml modified within last 5 minutes

**Exchange Tokens:** Well-known NSE tokens stored as class attributes:
- `NIFTY50`: `"99926000"`
- `INDIAVIX`: `"99926009"`
- `NIFTY_INDEX`: `"99926000"`

**API Methods Used:**
| Method | Purpose | Location |
|---|---|---|
| `get_quotes("NSE", token)` | Fetch VIX, NIFTY spot, LTP | `broker_manager.py:166,192,221` |
| `get_limits()` | Verify API session health | `broker_manager.py:142` |
| `injectOAuthHeader()` | Initialize authenticated session | `broker_manager.py:136` |

**Role:** Primary data source (most uptime). Used for market data only (VIX, NIFTY spot). Order execution falls back to Shoonya if Flattrade unavailable.

---

### 1.2 Flattrade (Primary Execution)

**Definition:** `broker_manager.py:67-89` (class), `broker_manager.py:234-249` (order placement)

**Authentication:** Bearer token from `python-trader/tokens.json`
- Token type: JSON with `token` and `client` fields
- Token refresh: `token_refresh_dual.py:28-77` — runs `get_flattrade_token_auto.py` via subprocess, checks token file was written

**Role:** Execution broker (₹0 brokerage). Used for order placement. Falls back to Shoonya if Flattrade token unavailable.

**Order Placement (stubbed):**
- `place_order()` at `broker_manager.py:234` — marked as TODO for actual Flattrade API
- `_place_order_shoonya()` at `broker_manager.py:251` — Shoonya fallback (also TODO)

**Position Management (stubbed):**
- `get_position()` at `broker_manager.py:265`
- `close_position()` at `broker_manager.py:278`

---

### 1.3 Broker Manager Singleton

**Definition:** `broker_manager.py:293-300`

```python
_broker_manager = None
def get_broker_manager() -> BrokerManager:
```

Thread-safe singleton. Mock mode bypasses all broker calls when `ANTARIKSH_MOCK_MODE=1`.

---

## 2. Telegram Messaging (via Picoclaw)

### 2.1 Picoclaw Bridge

**Definition:** `telegram_bridge.py` (full module, 212 lines)

**Transport methods (in priority order):**

1. **Python RPC** (`telegram_bridge.py:60-94`)
   - Calls `/root/.picoclaw/rpc.py` via `subprocess.run()`
   - Payload format: JSON-RPC with `method: "telegram.send"`, params include `chat_id`, `text`, `parse_mode`, `metadata`
   - Timeout: 10 seconds

2. **Shell Script** (`telegram_bridge.py:96-119`)  
   - Calls `/root/.picoclaw/telegram_send.sh` with chat_id and text as arguments
   - Timeout: 10 seconds

3. **Console Fallback** (`telegram_bridge.py:50-58`)  
   - Prints to stdout if neither picoclaw path exists

**Chat Configuration:**
- `CHAT_ID = "antariksh"` — picoclaw resolves this to actual Telegram chat/group

**Two-Message Protocol** (from `phase1_mvs.py` and `telegram_bridge.py`):
| Time | Message | Method | Location |
|---|---|---|---|
| 9:30 AM IST | Entry gate decision + trade plan | `send_entry_gate()` | `telegram_bridge.py:122-156` |
| 2:35 PM IST | Exit report, P&L, MTD stats | `send_exit_report()` | `telegram_bridge.py:158-198` |

**Alert Types** (from `telegram_bridge.py:208-212`):
- `critical` — 🔴 red alert
- `warning` — 🟡 yellow alert  
- `info` — 🟢 green alert

**Parse Mode:** `MarkdownV2` (Telegram format) by default.

**Phase 1 Fallback** (in `phase1_mvs.py:283-369`):
A separate `TelegramBridge` class is defined with the same interface but defaults to logging messages to `logger.info()` rather than actual picoclaw calls. The `telegram_bridge.py` module supersedes this.

---

## 3. LLM Provider APIs

### 3.1 DeepSeek (Primary)

**Definition:** `crew_structure.py:35-43`

**Configuration:**
- API Key: `DEEPSEEK_API_KEY` environment variable (with hardcoded fallback in source)
- Base URL: `https://api.deepseek.com/v1` (configurable via `DEEPSEEK_BASE_URL`)
- Model: `deepseek/deepseek-chat`
- Temperature: 0.3

**Integration:** Via CrewAI LLM wrapper (`crewai.llm.LLM`). Instantiated once at module level.

### 3.2 Tiered Fallback Providers

**Definition:** `config/antariksh_rules.yaml:193-214` (provider tiers), `config/antariksh_rules.yaml:249-267` (provider configurations)

All configured but only DeepSeek is currently wired in code:

| Provider | Type | Model | Auth Method |
|---|---|---|---|
| claude_sonnet | anthropic | claude-sonnet-4-6 | subscription_pro |
| claude_haiku | anthropic | claude-haiku-4-5-20251001 | subscription_pro |
| deepseek | deepseek | deepseek-chat | api_key_topup |
| minimax | minimax | abab6.5 | subscription |

**Circuit Breaker** (`config/antariksh_rules.yaml:232-237`):
- Failure threshold: 3 failures in 60-second window
- Cooldown: 300 seconds before re-testing provider

**Token Budgets** (`config/antariksh_rules.yaml:244-247`):
- Default daily soft cap: ₹50 per agent
- Chairman notification above: ₹100 daily

---

## 4. Database & File-Based Storage

### 4.1 Immutable JSONL Audit Trail

**Encoding:** `logs/cfo_audit_YYYYMMDD.jsonl` — One JSON object per line, appended only (immutable).

**Writers:**
| Writer | Schema | Location |
|---|---|---|
| `CFOAuditor.log_session()` (Phase 1) | Simple: timestamp, gate_pass, trade_plan, backtest_pnl, capital_impact | `cfo_auditor.py:36-62` |
| `AuditorEngine.append_session()` (Phase 2) | Extended: session_id, trade_plan (full), cfo_verdict, capital_impact with brokerage | `crew_structure.py:416-463` |

**Readers:**
- `AuditorEngine.read_phase1_logs()` — reads entries for a given date, returns list of dicts (`crew_structure.py:364-383`)
- `AuditorEngine.calculate_mtd_from_logs()` — sums P&L across all monthly JSONL files, supports both Phase 1 and Phase 2 entry schemas (`crew_structure.py:385-413`)

**Entry Schema Fields (Phase 2):**
```json
{
  "timestamp": "ISO timestamp",
  "session_id": "YYYYMMDD_HHMMSS",
  "gate_pass": bool,
  "trade_plan": dict | null,
  "backtest_result": {"pnl_inr": float},
  "cfo_verdict": {"passed": bool, "checks": {}, "violations": [], "recommendations": [], "mtd_pnl": float, "summary": str},
  "capital_impact": {"gross_pnl": float, "brokerage_est": float, "net_pnl": float, "free_cash_after": float}
}
```

**Immutable design:** Files are append-only. The auditor reads history and appends. No updates or deletes.

---

### 4.2 Text Logs

| File Pattern | Writer | Purpose |
|---|---|---|
| `logs/phase1_YYYYMMDD.log` | `phase1_mvs.py` (module-level logger) | Phase 1 MVS session logs |
| `logs/orchestrator_YYYYMMDD.log` | `session_orchestrator.py:34-37` | Orchestrator session logs |
| `logs/token_refresh_YYYYMMDD.log` | `token_refresh_dual.py:22-25` | Token refresh logs |

---

### 4.3 Configuration Files (Read-Only at Runtime)

| File | Format | Modified By | Purpose |
|---|---|---|---|
| `config/antariksh_rules.yaml` | YAML | Chairman (manual) | L3 parameters, capital, strategy, gates |
| `config/event_calendar.json` | JSON | Chairman (manual) | 2026 event calendar with skip_trading flags |
| `ralph/constitution.yaml` | YAML | Chairman (manual) | Vision, mission, goals, authority chain |
| `ralph/prds/*.yaml` | YAML | Chairman (manual) | Role PRDs with metric targets |

---

### 4.4 In-Memory Shared State

**Definition:** `crew_structure.py:68-84` — module-level `market_state: Dict`

Keys: `vix`, `nifty_spot`, `atm_strike`, `trade_plan`, `gate_pass`, `gate_reason`, `positions`, `mtd_pnl`, `session_pnl`, `alerts`, `audit_entries`, `halt`, `risk_ok`, `re_entries_used`, `max_re_entries`

This dict is shared between all 6 tools and both deterministic engines. Reset per test via `ScenarioRunner.__enter__()` at `tests/scenario_runner.py:40-47`.

---

## 5. Cron & Scheduling System

### 5.1 Defined Cron Jobs

**Definition:** `cron_simulator.py:26-52` (simulation), `scheduler/run_phase1_9am.sh`, `scheduler/run_phase1_2pm.sh` (production scripts)

| Job ID | Time (IST) | Script | Purpose |
|---|---|---|---|
| `token_refresh` | 07:00 | `token_refresh_dual.py` | Refresh Shoonya + Flattrade tokens |
| `entry_gate` | 09:30 | `session_orchestrator.py entry` | Gate check + trade plan generation |
| `exit` | 14:35 | `session_orchestrator.py exit` | Backtest + P&L + CFO audit |
| `exec_report_daily` | 18:00 | `exec_report.py daily` | Daily CEO report |
| `exec_report_weekly` | 20:00 (Sun) | `exec_report.py weekly` | Weekly CEO report |

### 5.2 Shell Scripts

- `scheduler/run_phase1_9am.sh` — Runs `phase1_mvs.py`, logs to `logs/scheduler_9am.log`
- `scheduler/run_phase1_2pm.sh` — Runs `phase1_mvs.py`, logs to `logs/scheduler_2pm.log`

Both use `set -e` for error propagation.

### 5.3 Cron Simulator

**Definition:** `cron_simulator.py` — Simulates all 5 cron jobs for testing without installing actual crons. Supports `list`, `entry`, `exit`, `full-day` commands with `--vix` and `--nifty` flags.

### 5.4 Ralph Scheduler

**Definition:** `ralph/ralph_loop.py:357-454` — `RalphScheduler` class

Schedules PRD-driven Ralph Loops using cron expressions (via `croniter`) or simple `HH:MM` format with a ±2-minute match window. Roles are scheduled per their PRD `frequency` fields.

---

## 6. Authentication & Credentials

### 6.1 Token Types

| Service | Token Type | Storage | Refresh |
|---|---|---|---|
| DeepSeek LLM | API key (`sk-...`) | Environment var `DEEPSEEK_API_KEY` (with fallback in source) | Manual rotation |
| Shoonya broker | OAuth (`Access_token`, `UID`, `Account_ID`) | `python-trader/Shoonya_oAuthAPI-py/cred.yml` | Daily via `token_refresh_dual.py` |
| Flattrade broker | Bearer token + client ID | `python-trader/tokens.json` | Daily via `token_refresh_dual.py` |
| Anthropic LLM | Subscription Pro (in config only, not in code) | N/A | N/A |
| Minimax LLM | Subscription (in config only, not in code) | N/A | N/A |

### 6.2 Token Refresh Flow

`token_refresh_dual.py` runs daily (scheduled at 07:00 IST):
1. `refresh_flattrade()` — runs `get_flattrade_token_auto.py`, validates `tokens.json` was written with `token` + `client` fields
2. `refresh_shoonya()` — runs `GetAuthcode.py`, validates `cred.yml` modification time within 5 minutes
3. Exit code 0 if at least one broker succeeds

---

## 7. Inter-Service Communication

### 7.1 Picoclaw RPC Protocol

**Definition:** `telegram_bridge.py:60-94`

JSON-RPC style call to `/root/.picoclaw/rpc.py`:
```json
{
  "method": "telegram.send",
  "params": {
    "chat_id": "antariksh",
    "text": "...message...",
    "parse_mode": "MarkdownV2",
    "metadata": {"source": "antariksh", "type": "entry_gate"}
  }
}
```

Subprocess call with 10-second timeout.

### 7.2 CrewAI Internal Communication

**Definition:** `crew_structure.py:682-688`

Single orchestrator agent with 6 deterministic tools. The CrewAI framework handles tool invocation via the LLM. All 6 tools share the `market_state` dict for inter-tool data passing. Execution is sequential (`Process.sequential`).

### 7.3 Phase 1 Orchestrator Command Protocol

**Definition:** `session_orchestrator.py:127-141`

CLI with `entry` and `exit` subcommands, designed for cron invocation:
```bash
python3 session_orchestrator.py entry   # 9:30 AM
python3 session_orchestrator.py exit    # 2:35 PM
```

---

## 8. Webhooks

**No webhooks are configured in this codebase.** All integrations are pull-based (broker API calls, file reads) or push-based via subprocess (picoclaw, token refresh scripts).

---

## 9. Event Calendar Integration

**Definition:** `event_calendar.py` (hardcoded list), `config/event_calendar.json` (JSON config)

Two representations of the same 2026 event dates:
- `event_calendar.py:13-35` — Hardcoded Python list of 21 `(date, name)` tuples
- `config/event_calendar.json` — 22 JSON entries (includes Buddha Purnima 2026-05-07 not in the Python list)

**Usage in gate check:**
- `MarketDataBridge.is_event_day()` in `phase1_mvs.py:131-152` — reads `event_calendar.json`, supports `ANTARIKSH_MOCK_EVENT_DAY` override
- `event_calendar.is_event_day()` in `event_calendar.py:38-43` — checks hardcoded Python list

**Known Gap:** The `scan_market` tool in `crew_structure.py:91-133` uses `ANTARIKSH_MOCK_EVENT_DAY` env var but does NOT call `is_event_day()`. The event calendar is not integrated into the CrewAI Phase 2 gate.

---

## 10. CEO Report Distribution

**Definition:** `exec_report.py` (full module, 239 lines)

**Report Types:**
- `daily` — Daily snapshot (mvs_todos, completion %, metrics)
- `weekly` — Weekly deep dive (accomplishments, not done, risks, next week)
- `monthly` — Monthly board pack (phase status, capital, L1 invariants)

**Distribution:**
- File: Saved to `exec_reports/DAILY_YYYY-MM-DD.md`, `WEEKLY_YYYY-MM-DD.md`, or `MONTHLY_YYYY-MM-DD.md`
- Telegram: `send_to_telegram()` method at `exec_report.py:198-202` — marked as TODO, references Kubera/picoclaw integration
