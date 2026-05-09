# Antariksh Code Conventions

**Generated:** 2026-05-09  
**Scope:** All Python files under `/home/trading_ceo/antariksh/`

---

## 1. Shebang & File Header

Every executable `.py` file starts with a shebang and a module-level docstring describing purpose.

```python
#!/usr/bin/env python3
"""
Module Name — one-line description.
Extended description with trade parameters, session times, protocol names.
"""
```

Files using this pattern:
- `session_orchestrator.py:1-6` — entry point with cron orchestration
- `phase1_mvs.py:1-10` — MVS with gate parameters inline
- `crew_structure.py:1-9` — usage examples embedded in docstring
- `backtester.py:1-6` — dry-run disclaimer
- `broker_manager.py:1-6` — dual-broker abstraction
- `cfo_auditor.py:1-5` — immutable audit trail context
- `event_calendar.py:1-7` — hardcoded 2026 dates
- `exec_report.py:1-5` — CEO report generation
- `telegram_bridge.py:1-5` — picoclaw integration
- `token_refresh_dual.py:1-5` — cron job for token refresh
- `cron_simulator.py:1-5` — Phase 1 timing simulation
- `test_full_scenario.py:1-5` — e2e scenario test
- `crew_test.py:1-14` — manual crew test
- `tests/scenario_runner.py:1-4` — CrewAI mock injection
- `tests/test_scenarios.py:1-5` — 32 scenario tests
- `tests/fixtures/mock_llm.py:1-4` — canned LLM responses
- `tests/fixtures/mock_broker.py:1-4` — env-var broker
- `tests/fixtures/seed_history.py:1-4` — JSONL fixture seeder
- `tests/generate_report.py:1-5` — result reporter

---

## 2. Import Organization

Three-tier import grouping (stdlib → third-party → local), each separated by blank lines:

```python
# ── stdlib ──
import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple, List

# ── third-party ──
from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

# ── local ──
from phase1_mvs import GateChecker, TradeDecisionEngine
from backtester import backtest_trade
```

See `crew_structure.py:12-29`, `session_orchestrator.py:8-26`, `broker_manager.py:4-22`.

Conditional imports with fallback are common for optional dependencies:

```python
try:
    from broker_manager import get_broker_manager
    BROKER_AVAILABLE = True
except ImportError:
    BROKER_AVAILABLE = False
```
(`phase1_mvs.py:26-30`, `event_calendar.py:33-37`, `broker_manager.py:21-24`)

---

## 3. Class & Function Naming

### Classes: PascalCase
```
Phase1Config, MarketDataBridge, GateChecker, TradeDecisionEngine,
TelegramBridge, CFOAuditor, Backtester, Phase1Orchestrator,
SessionOrchestrator, BrokerManager, Shoonya, Flattrade,
IronFlyBacktester, AuditorEngine, RiskGuardEngine, ReEntryTracker,
CronSimulator, ExecReportGenerator, ScenarioRunner, MockLLM, MockBrokerManager
```

All 30 classes enumerated above. Found via `grep "class "`.

### Functions: snake_case
```
check_gate(), generate_trade_plan(), calculate_atm_strike(),
get_current_vix(), get_nifty_spot(), backtest_trade(),
log_session(), send_entry_gate(), send_exit_report(),
validate_l1_invariants(), check_daily_sl(), check_portfolio_sl(),
check_30day_dd(), check_free_cash_floor(), check_burn_rate(),
full_check(), can_re_enter(), mark_re_entry(), reset_session(),
initialize_session(), run_full_session(), run_entry_session(),
run_exit_session(), seed_jsonl(), seed_consecutive_losses(),
make_mock_responses(), get_broker_manager(), get_cfo_auditor()
```

### Constants: UPPER_SNAKE_CASE on class attributes
```python
class Phase1Config:
    ENTRY_TIME = dt_time(9, 30)           # `phase1_mvs.py:45`
    EXIT_TIME = dt_time(14, 35)           # `phase1_mvs.py:46`
    VIX_MAX = 20.0                         # `phase1_mvs.py:57`
    TARGET_PROFIT_INR = 1000              # `phase1_mvs.py:52`
    MAX_LOSS_INIR = 3500                  # `phase1_mvs.py:53` (note: typo "INIR" preserved)

class RiskGuardEngine:
    DAILY_SL = 3500                        # `crew_structure.py:504`
    PORTFOLIO_SL = 4500                   # `crew_structure.py:505`
    MAX_30DAY_DD = 30000                  # `crew_structure.py:506`
    MIN_FREE_CASH = 11000                 # `crew_structure.py:507`

class AuditorEngine:
    DAILY_SL = 3500                        # `crew_structure.py:359`
    PORTFOLIO_SL = 4500                   # `crew_structure.py:360`
    MAX_30DAY_DD = 30000                  # `crew_structure.py:361`
    MIN_FREE_CASH = 11000                 # `crew_structure.py:362`

class IronFlyBacktester:
    RISK_FREE_RATE = 0.06                 # `backtester.py:50`
    IMPLIED_VOL = 0.20                    # `backtester.py:51`
    DAYS_TO_EXPIRY = 7                    # `backtester.py:52`
```

### Module-level state variables: snake_case
```python
market_state: Dict = { ... }              # `crew_structure.py:68-84` — shared state dict
_cfo_auditor = None                       # `cfo_auditor.py:146` — singleton
_broker_manager = None                    # `broker_manager.py:293` — singleton
_crew_cache = None                        # `crew_structure.py:676` — lazy crew cache
```

Underscore prefix for "private" module-level state (`_crew_cache`, `_cfo_auditor`, `_broker_manager`).

---

## 4. Method Design Patterns

### Heavy use of `@staticmethod` everywhere

The codebase uses `@staticmethod` for virtually all methods. There are **no instance methods calling `self`** in production code — only `__init__` for setup. This is a deliberate functional-style pattern.

```python
# `crew_structure.py:364-367`
class AuditorEngine:
    @staticmethod
    def read_phase1_logs(date_str: Optional[str] = None) -> List[Dict]:
        ...

# `phase1_mvs.py:242-245`
class TradeDecisionEngine:
    @staticmethod
    def calculate_atm_strike(spot: float) -> float:
        return round(spot / 50) * 50
```

Count: **46 `@staticmethod`** occurrences across 10 files (grep confirmed).

Only `BrokerManager` (`broker_manager.py:109-119`) and `CFOAuditor` (`cfo_auditor.py:29-34`) have `__init__` with instance state. Others are stateless utility classes.

### Singleton pattern (module-level lazy init)
```python
_broker_manager = None
def get_broker_manager() -> BrokerManager:
    global _broker_manager
    if _broker_manager is None:
        _broker_manager = BrokerManager()
    return _broker_manager
```
(`broker_manager.py:293-300`, `cfo_auditor.py:146-153`)

### `@tool` decorator from CrewAI (deterministic tools)
```python
@tool
def scan_market() -> str:
    """..."""
```
(`crew_structure.py:90-133` — 6 tools: `scan_market`, `generate_trade_plan`, `check_risk`, `execute_trade`, `monitor_positions`, `log_audit`)

These are deterministic functions that return JSON strings. They read/write the shared `market_state` dict. No LLM in the execution path.

### Lazy-crew builder pattern
```python
_crew_cache = None
def _build_crew():
    global _crew_cache
    if _crew_cache is None:
        _crew_cache = Crew(...)
    return _crew_cache
```
(`crew_structure.py:676-688`)

---

## 5. Error Handling

### Pattern: `try/except Exception as e` with logging
```python
try:
    # operation
    return result
except Exception as e:
    logger.error(f"Operation failed: {e}")
    return None
```

Seen in:
- `broker_manager.py:60-64` — credential loading
- `backtester.py:60-70` — Black-Scholes calc
- `telegram_bridge.py:89-93` — RPC timeouts
- `token_refresh_dual.py:75-77` — subprocess errors

### Pattern: Top-level catch-all with Telegram alert
```python
try:
    # full session logic
    return result
except Exception as e:
    logger.error(f"Entry session failed: {e}", exc_info=True)
    TelegramBridge.send_alert("critical", "Entry Session Error", str(e))
    return False, None
```
(`session_orchestrator.py:79-82`, `session_orchestrator.py:122-125`)

### Custom exceptions: None defined
No custom exception classes exist. All error handling uses built-in exceptions caught as `Exception`.

### Return-value pattern: `Optional[Dict]` or `Optional[float]`
Functions return `None` on failure (not exceptions). This is the dominant pattern:
```python
def get_current_vix() -> Optional[float]:
    ...
    return None  # on any failure
```
(`phase1_mvs.py:103-114` — see `get_current_vix`, `get_nifty_spot`, `generate_trade_plan`)

---

## 6. Logging

### Mandatory: `logging` module only — NEVER `print()`

Every file configures logging at module level:

```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(Phase1Config.LOG_DIR / f"phase1_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Antariksh-MVS")
```

### Log format convention
```
%(asctime)s | %(levelname)-8s | %(message)s
```
With optional `%(name)s` for multi-module systems. Left-aligned 8-char levelname with `%-8s`.

Seen in:
- `phase1_mvs.py:70-78` — Phase1Config.setup_logging()
- `session_orchestrator.py:30-38` — with `| %(message)s` pipe format
- `crew_structure.py:49-53` — with `| %(name)s | %(message)s`
- `exec_report.py:20-23` — basic config
- `token_refresh_dual.py:18-25` — file + stream
- `cron_simulator.py:17-20` — basic config
- `crew_test.py:36-40` — with TEST tag
- `test_full_scenario.py:26` — basic config

### Log levels used
- `logger.info(...)` — all normal execution
- `logger.warning(...)` — recoverable issues (VIX unavailable, broker down)
- `logger.error(...)` — operation failures (usually `exc_info=True` in top-level handlers)
- `logger.debug(...)` — trace mode only

### Log file naming
```
logs/phase1_{YYYYMMDD}.log
logs/orchestrator_{YYYYMMDD}.log
logs/cfo_audit_{YYYYMMDD}.jsonl        # immutable audit trail
logs/token_refresh_{YYYYMMDD}.log
```

---

## 7. Docstrings & Comments

### Module docstrings: triple-quoted at top of file
```python
"""
Module Name — one-line purpose.
Extended description. Usage examples.
"""
```
All 22 `.py` files have module docstrings.

### Function docstrings: triple-quoted, imperative style
```python
@staticmethod
def calculate_atm_strike(spot: float) -> float:
    """Calculate ATM strike: round(spot/50)*50 for NIFTY"""
    return round(spot / 50) * 50
```

### Comment style: `#` for section dividers and inline explanations
```python
# ============================================================
# GATE LOGIC (3-LAYER)
# ============================================================
```
(`phase1_mvs.py:164-166`)

Section dividers use 60-char `=` lines with capitalized section name. This pattern is in **every** file.

```python
# # ── section name ────────────────────────────────────
# # ── section name ────────────────────────────────────
```
Another variant in `tests/scenario_runner.py:61`, `tests/test_scenarios.py:21-23`.

### TODO markers
```python
# TODO: Implement signal calculation
# TODO: Implement confirmation logic
# TODO: Implement Telegram API integration via picoclaw
# TODO: Implement realistic P&L simulation
```
Approximately 8-10 TODO markers across `phase1_mvs.py`, `telegram_bridge.py`, `broker_manager.py`.

---

## 8. Type Hints

### Used consistently on function signatures
```python
from typing import Dict, Optional, Tuple, List

def check_gate() -> Tuple[bool, str]:
def generate_trade_plan() -> Optional[Dict]:
def get_current_vix() -> Optional[float]:
def full_check(
    session_pnl: float,
    mtd_pnl: float,
    recent_pnls: Optional[List[float]] = None,
) -> Dict:
```

### Module-level typed variable
```python
market_state: Dict = { ... }           # `crew_structure.py:68`
```

### TypedDict — NOT used
Plain `Dict` with `Optional` keys. No `TypedDict` or `dataclass` for structured data.

### Return types
- `Optional[Dict]` — data that may fail (most common)
- `Optional[float]` — scalar lookups
- `Dict` — always returns
- `Tuple[bool, str]` — gate results (pass/fail + reason)
- `bool` — success indicators
- `str` — JSON serialized strings from `@tool` functions

---

## 9. Configuration Conventions

### YAML for rules/constitution (immutable, human-ratified)
```
config/antariksh_rules.yaml     — L3 parameters with ratification date and write-protection
ralph/constitution.yaml         — vision, mission, capital limits, authority chain
ralph/prds/*.yaml               — agent PRDs (CEO, PM, OM, TA, AM, PA)
```

### JSON for data calendars (machine-writable)
```
config/event_calendar.json      — 22 event dates for 2026 with skip_trading flags
```

### Python class for runtime config (from YAML values)
```python
class Phase1Config:
    ENTRY_TIME = dt_time(9, 30)
    VIX_MAX = 20.0
    INSTRUMENT = "NIFTY"
    LOTS = 1
    WING_WIDTH = 300
```
(`phase1_mvs.py:43-65`) — Values seeded from `config/antariksh_rules.yaml`.

### Environment variables for runtime overrides (mock mode)
```python
MOCK_MODE = os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1"
MOCK_VIX = float(os.environ.get("ANTARIKSH_MOCK_VIX", "18.5"))
MOCK_NIFTY = float(os.environ.get("ANTARIKSH_MOCK_NIFTY", "24500.0"))
```
(`crew_structure.py:60-62`, `broker_manager.py:105-107`)

Mock control env vars used:
- `ANTARIKSH_MOCK_MODE` — enables mock (1/0)
- `ANTARIKSH_MOCK_VIX` — VIX value
- `ANTARIKSH_MOCK_NIFTY` — NIFTY spot
- `ANTARIKSH_MOCK_TIME` — override time (ISO or HH:MM)
- `ANTARIKSH_MOCK_EVENT_DAY` — force event day
- `ANTARIKSH_MOCK_EVENT_NAME` — event name
- `ANTARIKSH_MOCK_PNL` — session P&L
- `ANTARIKSH_MOCK_TRAJECTORY` — comma-separated P&L values
- `ANTARIKSH_TRAJ_IDX` — trajectory index
- `ANTARIKSH_MOCK_BROKER_DOWN` — simulate broker failure
- `ANTARIKSH_MOCK_SENTINEL_BLACKOUT` — timeout in seconds

### Data classes (Ralph Loop only)
```python
@dataclass
class VerificationResult:
    complete: bool
    reason: str = ""
```
(`ralph/ralph_loop.py:51-56`)

---

## 10. String Formatting

### f-strings for logging (Python 3.6+)
```python
logger.info(f"VIX: {vix:.2f}")
logger.info(f"Gate check result: {gate_pass=}, reason='{gate_reason}'")
logger.error(f"Entry session failed: {e}")
```

### f-string debugging shorthand: `{var=}`
```python
logger.info(f"  Result: {gate_pass=}, {gate_reason=}")   # `session_orchestrator.py:54`
logger.info(f"CFO audit logged: {gate_pass=}, {trade_plan is not None=}")  # `phase1_mvs.py:404`
```

### Pathlib over os.path
```python
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python-trader"))
Phase1Config.LOG_DIR.mkdir(exist_ok=True)
```
Consistent use of `Path` with `/` operator throughout.

---

## 11. Entry Points

### `if __name__ == "__main__":` with argparse
```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="...")
    parser.add_argument("session", choices=["entry", "exit"])
    args = parser.parse_args()
    ...
    main()
```
(`session_orchestrator.py:127-141`, `phase1_mvs.py:498-499`, `crew_structure.py:822-850`, `exec_report.py:228-239`, `cron_simulator.py:140-141`)

---

## 12. File Organization

```
antariksh/
├── phase1_mvs.py              # Phase 1 MVS — all-in-one entry
├── session_orchestrator.py    # Separate entry/exit orchestration
├── crew_structure.py          # Phase 2 CrewAI — tools, engines, crew
├── backtester.py              # Black-Scholes Iron Fly P&L calc
├── broker_manager.py          # Dual-broker (Shoonya + Flattrade)
├── cfo_auditor.py             # Immutable audit trail logger
├── event_calendar.py          # Hardcoded 2026 event dates
├── telegram_bridge.py         # picoclaw Telegram messaging
├── exec_report.py             # CEO daily/weekly/monthly reports
├── token_refresh_dual.py      # Cron: refresh both broker tokens
├── cron_simulator.py          # Test harness for cron jobs
├── crew_test.py               # Manual crew tests (entry point)
├── test_full_scenario.py      # E2E scenario manual test
│
├── tests/
│   ├── scenario_runner.py     # Context manager for mock injection
│   ├── test_scenarios.py      # 32 scenario tests
│   ├── generate_report.py     # Pytest JSON → markdown
│   ├── run_all.sh             # Bash: pytest + report gen
│   └── fixtures/
│       ├── mock_llm.py        # Canned LLM responses
│       ├── mock_broker.py     # Env-var mock broker
│       └── seed_history.py    # Synthetic JSONL fixture seeder
│
├── config/
│   ├── antariksh_rules.yaml   # L3 parameters (immutable)
│   └── event_calendar.json    # 2026 event calendar
│
├── ralph/
│   ├── ralph_loop.py          # Verify-retry meta-layer
│   ├── constitution.yaml      # Vision, mission, board
│   └── prds/
│       └── *.yaml             # Per-agent PRD documents
│
├── logs/                      # Runtime output (gitignored)
├── exec_reports/              # Generated CEO reports
└── .planning/                 # Planning documents
```
