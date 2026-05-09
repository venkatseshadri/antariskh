# Antariksh CrewAI — Mocking & Testing Infrastructure
**Companion to:** `SCENARIO_TEST_PLAN.md`
**Purpose:** Engineering playbook for HOW to inject scenarios into the CrewAI 7-agent system. Covers what's real, what's mocked, where state lives, how to trigger sessions, and how to verify agent behavior matches expectations.

**Audience:** Engineer running scenarios over the weekend. Anyone debugging "did the agent actually do what we wanted?"

---

## Table of Contents

1. [Architecture: What's Real, What's Mocked](#1-architecture-whats-real-whats-mocked)
2. [The Five Mocking Layers](#2-the-five-mocking-layers)
3. [Where the State Machine Lives](#3-where-the-state-machine-lives)
4. [How to Trigger a Session](#4-how-to-trigger-a-session)
5. [CrewAI-Specific Mocking Patterns](#5-crewai-specific-mocking-patterns)
6. [Verification Hooks — Did the Agent Do What We Wanted?](#6-verification-hooks)
7. [Building a Scenario Runner](#7-building-a-scenario-runner)
8. [Per-Scenario Mock Recipes](#8-per-scenario-mock-recipes)
9. [Common Pitfalls](#9-common-pitfalls)

---

## 1. Architecture: What's Real, What's Mocked

### The Layered View

```
┌───────────────────────────────────────────────────────────────────┐
│ TEST RUNNER (crew_test.py + scenario fixtures)                    │
│ - Injects environment, seeds JSONL, patches LLM, asserts state    │
└────────────────┬──────────────────────────────────────────────────┘
                 │ invokes
                 ▼
┌───────────────────────────────────────────────────────────────────┐
│ ENTRY POINT: run_full_session() / antariksh_crew.kickoff()        │
└────────────────┬──────────────────────────────────────────────────┘
                 │ calls
                 ▼
┌─────────────────────────────────┬─────────────────────────────────┐
│ CREWAI LAYER (LLM-DRIVEN)       │ DETERMINISTIC LAYER (NO LLM)    │
│ - 7 Agents: Orchestrator,       │ - AuditorEngine                 │
│   Scanner, Strategist,          │ - RiskGuardEngine               │
│   Executor, Sentinel,           │ - ReEntryTracker                │
│   Risk Guard, Auditor           │ - initialize_session()          │
│ - Each calls LLM via LiteLLM    │ - Pure Python, deterministic    │
│   ↓ MOCK THIS LAYER             │   ↓ DO NOT MOCK — verify it     │
└─────────────────────────────────┴─────────────────────────────────┘
                 │
                 ▼
┌───────────────────────────────────────────────────────────────────┐
│ TOOLS / EXTERNAL SYSTEMS                                          │
│ - broker_manager.py (Shoonya/Flattrade) ← MOCK at function level  │
│ - telegram_bridge.py ← MOCK by redirecting to /tmp file           │
│ - Black-Scholes calc (backtester.py) ← REAL (deterministic)       │
└───────────────────────────────────────────────────────────────────┘
                 │
                 ▼
┌───────────────────────────────────────────────────────────────────┐
│ STATE STORES                                                      │
│ - market_state dict (in-memory) ← REAL (the state machine)        │
│ - logs/cfo_audit_*.jsonl (disk) ← SEED with fixture, READ real    │
│ - config/antariksh_rules.yaml ← REAL (immutable in test)          │
│ - Environment variables ← INJECT for time/vix/nifty               │
└───────────────────────────────────────────────────────────────────┘
```

### What Stays REAL in Tests (and why)

| Component | Why Real |
|---|---|
| `RiskGuardEngine` | Deterministic capital math. Test verifies its output. Mocking it = not testing it. |
| `AuditorEngine` | Reads JSONL → calculates MTD. Test verifies arithmetic. Critical to leave real. |
| `ReEntryTracker` | Pure counter logic. Real. |
| `market_state` dict | THIS IS the state machine. Tests assert on its values. |
| `antariksh_rules.yaml` | Configuration is part of the system contract. Read real values. |
| Black-Scholes (`backtester.py`) | Pure math. Real. |
| JSONL log writing | Real (audit trail integrity is part of the test). |

### What MUST Be Mocked

| Component | Why Mocked | Mocking Layer |
|---|---|---|
| `datetime.now()` | Tests run any day. Need to control "current time". | `freezegun` or monkeypatch |
| Broker API (Shoonya/Flattrade) | No live trading allowed. | Patch `broker_manager.get_broker_manager()` |
| LLM calls (all 7 agents) | Cost money, non-deterministic, slow. | Patch `litellm.completion` or replace LLM instance |
| Telegram send | Don't spam the user during tests. | Redirect to `/tmp/antariksh_telegram_test.txt` |
| Sentinel real-time MTM | We control trajectory in tests. | Inject mock MTM sequence |

### What's INJECTED (test fixtures)

| Injected | Mechanism | Example |
|---|---|---|
| Current time | `os.environ['ANTARIKSH_MOCK_TIME']` + monkeypatch `datetime.now()` | `"2026-05-12 10:30:00"` |
| Current VIX | `os.environ['ANTARIKSH_MOCK_VIX']` | `"14.0"` |
| Current NIFTY spot | `os.environ['ANTARIKSH_MOCK_NIFTY']` | `"24500"` |
| Historical sessions | Pre-write `logs/cfo_audit_*.jsonl` files | 30 days of synthetic JSONL |
| MTM trajectory | Class `MockSentinel` returns sequence | `[-500, -1500, -2500, -3500]` (SL hit) |
| LLM responses | `MockLLM` returns canned outputs per agent | "Gate PASS" / "Trade plan: {...}" |
| Broker responses | `MockBrokerManager.get_vix()` returns env var | reads `ANTARIKSH_MOCK_VIX` |

---

## 2. The Five Mocking Layers

### Layer 1: Time Mocking

**Why:** Phase 1 has hard time gates (10:30-11:30 entry, 14:30 hard exit). Tests need to run at any time of day.

**How:**
```python
# Option A: freezegun (cleanest, requires pip install freezegun)
from freezegun import freeze_time

with freeze_time("2026-05-12 10:30:00"):
    result = run_full_session(mock_mode=True)
    # Inside this block, datetime.now() returns 2026-05-12 10:30:00

# Option B: monkeypatch (no extra dependency)
import datetime as dt_mod

class MockDatetime:
    @staticmethod
    def now():
        target = os.environ.get('ANTARIKSH_MOCK_TIME', '2026-05-12T10:30:00')
        return dt_mod.datetime.fromisoformat(target)
    
    @staticmethod
    def fromisoformat(s):
        return dt_mod.datetime.fromisoformat(s)

# Patch only where needed (NOT globally — would break logging timestamps)
import market_data_bridge
market_data_bridge.datetime = MockDatetime  # only the bridge sees mock time
```

**Gotcha:** Don't patch `datetime` globally. CrewAI internal logging uses `datetime.now()` — patching globally breaks logs. Patch at module level inside the modules under test.

### Layer 2: Market Data Mocking

**Why:** Tests need controlled VIX, NIFTY, event-day responses without hitting brokers.

**How:** The codebase already has a hook — `os.environ['ANTARIKSH_MOCK_MODE']`. The `BrokerManager` in `broker_manager.py` checks this and returns mock values.

But for full control, replace the broker manager itself:

```python
class MockBrokerManager:
    """Returns values from env vars; no API calls."""
    
    def get_vix(self):
        return float(os.environ.get('ANTARIKSH_MOCK_VIX', '15.0'))
    
    def get_nifty_spot(self):
        return float(os.environ.get('ANTARIKSH_MOCK_NIFTY', '24500'))
    
    def place_order(self, leg):
        # Don't actually place — log and return mock order_id
        logger.info(f"MOCK ORDER: {leg}")
        return {"order_id": f"MOCK_{int(time.time())}", "status": "FILLED"}
    
    def get_position_mtm(self, position_id):
        # Inject from trajectory
        traj = json.loads(os.environ.get('ANTARIKSH_MOCK_PNL_TRAJECTORY', '[0]'))
        idx = int(os.environ.get('ANTARIKSH_MOCK_PNL_IDX', '0'))
        os.environ['ANTARIKSH_MOCK_PNL_IDX'] = str(idx + 1)
        return traj[min(idx, len(traj)-1)]

# Patch at import site
import unittest.mock as mock
with mock.patch('crew_structure.get_broker_manager', return_value=MockBrokerManager()):
    result = run_full_session(mock_mode=True)
```

### Layer 3: LLM Mocking (CrewAI-Specific)

**This is the trickiest layer.** CrewAI agents call LLMs internally to "decide" what to do. We need to control these decisions for deterministic tests.

**Three options:**

#### Option A: Replace the LLM Instance (cleanest)
```python
from crewai.llm import LLM

class MockLLM(LLM):
    """Returns canned responses based on the system prompt."""
    
    def __init__(self, response_map):
        # response_map = {"scanner": "Gate PASS", "strategist": "{...JSON plan...}"}
        self.response_map = response_map
    
    def call(self, messages, **kwargs):
        # Inspect the system prompt to detect which agent is calling
        system = str(messages).lower()
        for agent_name, response in self.response_map.items():
            if agent_name in system:
                return response
        return "OK"  # default

# In test setup
mock_llm = MockLLM({
    "market scanner": '{"vix": 14.0, "gate_pass": true, "reason": "VIX safe"}',
    "trade strategist": '{"strikes": [24500, 24800, 24200], "premium": 1100}',
    "auditor": '{"logged": true}',
})

# Replace deepseek_llm in crew_structure
import crew_structure
crew_structure.deepseek_llm = mock_llm
# Re-import the agents to pick up new LLM
# OR construct the test crew with the mock_llm explicitly
```

#### Option B: Patch LiteLLM at the bottom (CrewAI uses LiteLLM internally)
```python
import litellm

def mock_completion(model, messages, **kwargs):
    # Returns CrewAI/OpenAI-compatible response
    system_prompt = next((m['content'] for m in messages if m['role']=='system'), '')
    
    if 'scanner' in system_prompt.lower():
        content = '{"vix": 14, "gate_pass": true}'
    elif 'strategist' in system_prompt.lower():
        content = '{"strikes": [24500, 24800, 24200]}'
    else:
        content = "OK"
    
    return {
        "choices": [{"message": {"content": content, "role": "assistant"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20}
    }

with mock.patch('litellm.completion', side_effect=mock_completion):
    result = run_full_session(mock_mode=True)
```

#### Option C: Bypass CrewAI LLM Entirely (for pure logic tests)
For scenarios that test the deterministic engines (Risk Guard, Auditor), skip the crew entirely:

```python
from crew_structure import RiskGuardEngine, market_state

# Direct deterministic test — no CrewAI, no LLM
market_state['session_pnl'] = -4000
market_state['mtd_pnl'] = -5000

result = RiskGuardEngine.full_check(session_pnl=-4000, mtd_pnl=-5000)

assert result['halt'] == True
assert 'daily_sl' in result['violations']
```

**Recommendation:** Use **Option C** for risk/audit/re-entry tests (RM-*, DD-*). Use **Option A** when you need to test the full crew choreography (HP-*, MC-*).

### Layer 4: Tool Mocking

**Why:** Agents use tools (broker_manager, telegram_bridge) to interact with the world. We need to capture these without side effects.

**How:** CrewAI tools are passed to agents at construction. Replace them in tests:

```python
from crewai_tools import BaseTool

class MockBrokerTool(BaseTool):
    name = "Broker Tool"
    description = "Mock broker for tests"
    captured_orders = []  # class-level, accessible from test
    
    def _run(self, action, **kwargs):
        if action == 'get_vix':
            return float(os.environ.get('ANTARIKSH_MOCK_VIX', '15'))
        if action == 'place_order':
            self.captured_orders.append(kwargs)
            return {"order_id": "MOCK_001", "status": "FILLED"}

# Construct test crew with mock tool
mock_broker_tool = MockBrokerTool()
test_scanner = Agent(role="Market Scanner", ..., tools=[mock_broker_tool])
```

### Layer 5: State Seeding (Historical JSONL)

**Why:** Auditor calculates MTD by reading `logs/cfo_audit_*.jsonl`. To test "10 days of losses", we need to write 10 days of synthetic JSONL.

**How:**
```python
import json
from datetime import datetime, timedelta
from pathlib import Path

LOG_DIR = Path('/home/trading_ceo/antariksh/logs')

def seed_jsonl_history(days_back, pnl_per_day):
    """
    days_back: int (e.g., 10)
    pnl_per_day: list of floats (one per day, oldest first)
    """
    today = datetime.now()
    for i, pnl in enumerate(pnl_per_day):
        date = today - timedelta(days=days_back - i)
        date_str = date.strftime("%Y-%m-%d")
        
        entry = {
            "timestamp": date.isoformat(),
            "date": date_str,
            "gate_pass": True,
            "trade_executed": True,
            "capital_impact": {
                "net_pnl": pnl,
                "free_cash_after": 11000 + pnl,
            },
            "mtd_pnl": sum(pnl_per_day[:i+1])
        }
        
        log_file = LOG_DIR / f"cfo_audit_{date_str}.jsonl"
        with open(log_file, 'a') as f:
            f.write(json.dumps(entry) + "\n")

# In test: seed 10 days of small losses
seed_jsonl_history(days_back=10, pnl_per_day=[-300, -400, -200, -350, -400, -300, -250, -400, -350, -300])
# Total = -₹3,250 → 32.5% of ₹10,000 free cash → burn rate trigger
```

**Gotcha:** Tests must clean up after themselves. Use a temporary log directory:
```python
import tempfile
test_log_dir = tempfile.mkdtemp(prefix="antariksh_test_")
# Patch LOG_DIR for the test
```

---

## 3. Where the State Machine Lives

### The State Machine — One Source of Truth

```python
# crew_structure.py:218 (approx)
market_state = {
    # Set by Scanner
    "vix": None,
    "nifty_spot": None,
    "gate_pass": False,
    "gate_reason": None,
    "is_event_day": False,
    
    # Set by Strategist
    "trade_plan": None,  # Dict with strikes, premiums, lots
    
    # Set by Risk Guard (deterministic)
    "halt": False,
    "risk_ok": True,
    "violations": [],
    "halt_reason": None,
    
    # Set by Executor
    "positions": [],
    "order_ids": [],
    
    # Set by Sentinel (real-time during session)
    "current_mtm": 0,
    "exit_reason": None,
    
    # Set by Auditor
    "mtd_pnl": 0,
    "session_pnl": 0,
    "audit_verdict": {},
    
    # Set by ReEntryTracker
    "re_entries_used": 0,
    "max_re_entries": 1,
}
```

**This dict is the contract.** Every agent reads from it and writes to it. Tests assert on it.

### State Transitions Per Scenario

For HP-01 (clean win, target hit):
```
T+0:    {gate_pass: False, halt: False, mtd_pnl: 0}                ← initialize_session()
T+1:    Scanner sets {vix: 14, nifty_spot: 24500, gate_pass: True}
T+3:    Strategist sets {trade_plan: {...}}
T+5:    Risk Guard verifies (no halt) → {risk_ok: True}
T+6:    Executor sets {positions: [...4 legs...], order_ids: [...]}
T+session: Sentinel updates {current_mtm: 1000} → triggers exit
T+exit: Executor closes → {positions: []}
T+end:  Auditor sets {session_pnl: 1000, mtd_pnl: 1000, exit_reason: "Target hit"}
```

For RM-01 (SL hit, re-entry available):
```
T+0:    {gate_pass: False, halt: False, mtd_pnl: 0, re_entries_used: 0}
T+1:    Scanner sets {gate_pass: True}
T+3:    Strategist sets {trade_plan}
T+5:    Risk Guard {risk_ok: True}
T+6:    Executor sets {positions}
T+~2hr: Sentinel: {current_mtm: -3500} → emit STOP_LOSS
T+~2hr: Risk Guard: {halt: False} (single-instrument SL, not portfolio)
T+exit: Executor closes → {positions: []}
T+end:  Auditor sets {session_pnl: -3500, mtd_pnl: -3500, exit_reason: "Stop loss"}
        ReEntryTracker: can_re_enter() == True (attempts=0, halt=False)
```

### Persistent State (Disk)

Beyond the in-memory dict:

| Store | What | Lifetime |
|---|---|---|
| `logs/cfo_audit_YYYY-MM-DD.jsonl` | Per-session audit entries | Permanent |
| `logs/phase1_YYYYMMDD.log` | Console log, INFO+DEBUG | Per-day |
| `config/antariksh_rules.yaml` | L3 parameters | Until chairman commits |
| `config/event_calendar.json` | RBI/budget dates (when created) | Until event passes |
| `/tmp/antariksh_telegram.txt` | Outgoing Telegram queue | Reset per boot |

In tests, use a temporary directory:
```python
@contextmanager
def isolated_state():
    """Isolate logs and state for one test."""
    test_dir = tempfile.mkdtemp(prefix="antariksh_test_")
    
    # Save originals
    orig_log_dir = Path('/home/trading_ceo/antariksh/logs')
    orig_state = market_state.copy()
    
    # Redirect
    Phase1Config.LOG_DIR = Path(test_dir)
    market_state.clear()
    market_state.update(initial_state())
    
    try:
        yield test_dir
    finally:
        # Restore
        Phase1Config.LOG_DIR = orig_log_dir
        market_state.clear()
        market_state.update(orig_state)
        shutil.rmtree(test_dir)
```

---

## 4. How to Trigger a Session

### Three Ways to Run

#### A. Direct Crew Kickoff (full LLM flow)
```bash
cd /home/trading_ceo/antariksh
ANTARIKSH_MOCK_MODE=1 ANTARIKSH_MOCK_VIX=14 python3 -c "
from crew_structure import run_full_session, initialize_session
initialize_session()
result = run_full_session(mock_mode=True, mock_vix=14, mock_nifty=24500)
print(result)
"
```

This invokes `antariksh_crew.kickoff()` → all 7 agents → full LLM calls. Slow but realistic.

#### B. Direct Engine Invocation (no LLM)
```python
# Skip CrewAI entirely. Test deterministic logic.
from crew_structure import (
    initialize_session, RiskGuardEngine, AuditorEngine, 
    ReEntryTracker, market_state
)

initialize_session()
result = RiskGuardEngine.full_check(session_pnl=-4000, mtd_pnl=-5000)
print(result)  # {halt: True, violations: [...], ...}
```

#### C. Cron Trigger (production simulation)

**Once cron is configured** (currently missing — see PHASE_AUDIT_REPORT.md):
```bash
# Add to /etc/cron.d/antariksh_exec_reports
30 09 * * 1-5 root /home/trading_ceo/antariksh/scheduler/run_entry.sh
35 14 * * 1-5 root /home/trading_ceo/antariksh/scheduler/run_exit.sh
```

To simulate a cron trigger in test:
```bash
# Run as root to mimic cron environment
sudo -u root /home/trading_ceo/antariksh/scheduler/run_entry.sh
```

### Fast-Forward Time (Replay Multi-Day Scenarios)

For DD-01 (5 consecutive losses), don't wait 5 days. Seed JSONL + run today's session:
```python
# Pre-seed 5 days of losses
seed_jsonl_history(days_back=5, pnl_per_day=[-3500, -2200, -1800, -3500, -2900])

# Run today's session — Auditor reads JSONL, detects streak
with freeze_time("2026-05-13 09:30:00"):
    result = run_full_session(mock_mode=True, mock_vix=14)
    # Expected: gate_pass=False, reason="cooldown_active"
```

---

## 5. CrewAI-Specific Mocking Patterns

### Pattern 1: Replace the LLM at Import Time

**Best for:** Whole-crew tests (HP-*, MC-*).

```python
# tests/conftest.py
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.call = MagicMock(side_effect=mock_llm_dispatcher)
    return llm

def mock_llm_dispatcher(messages, **kwargs):
    """Inspect messages, return canned response based on agent role."""
    # CrewAI passes the system prompt as first message
    system = next((m['content'] for m in messages if m['role'] == 'system'), '')
    
    if 'Market Scanner' in system:
        return '{"vix": ' + os.environ.get('ANTARIKSH_MOCK_VIX', '15') + ', "gate_pass": true}'
    if 'Trade Strategist' in system:
        return '{"strikes": [24500, 24800, 24200], "premium": 1100, "lots": 1}'
    if 'Executor' in system:
        return '{"order_ids": ["MOCK_1", "MOCK_2", "MOCK_3", "MOCK_4"]}'
    if 'Sentinel' in system:
        # Return next MTM from trajectory
        return '{"mtm": ' + str(get_next_mtm()) + '}'
    # Risk Guard, Auditor are deterministic — should not call LLM
    return '{}'
```

Then in the test:
```python
def test_HP_01_clean_win(mock_llm):
    # Patch the module-level llm
    import crew_structure
    crew_structure.deepseek_llm = mock_llm
    # Need to re-bind to agents — see Pattern 2
```

### Pattern 2: Reconstruct Crew with Mock LLM

CrewAI agents bind LLM at construction. To swap, build a fresh crew:
```python
from crewai import Agent, Task, Crew, Process

def build_test_crew(mock_llm, market_data):
    scanner = Agent(role="Market Scanner", ..., llm=mock_llm)
    # ... other agents
    return Crew(agents=[...], tasks=[...], manager_agent=..., process=Process.hierarchical)
```

### Pattern 3: step_callback for Verification

CrewAI provides callbacks to inspect agent outputs:
```python
captured_steps = []

def step_callback(step_output):
    """Called after each agent step. Capture for assertions."""
    captured_steps.append({
        "agent": step_output.agent.role if hasattr(step_output, 'agent') else None,
        "output": str(step_output),
        "timestamp": datetime.now().isoformat()
    })

crew = Crew(
    agents=[...],
    tasks=[...],
    step_callback=step_callback,
    process=Process.hierarchical,
)
```

After kickoff:
```python
assert len(captured_steps) >= 6  # all 6 tasks fired
assert captured_steps[0]['agent'] == 'Market Scanner'  # gate first
assert captured_steps[1]['agent'] == 'Trade Strategist'  # plan second
# ... etc
```

### Pattern 4: Task-Level Callbacks

```python
def task_callback(task_output):
    """Called when a task completes."""
    print(f"Task done: {task_output.description[:50]}")
    print(f"Output: {task_output.raw[:100]}")

scan_market_task = Task(
    description="...",
    agent=scanner,
    callback=task_callback,
)
```

### Pattern 5: Skip the Crew, Test the Engine Directly

For deterministic engines (Risk Guard, Auditor, ReEntry), bypass CrewAI entirely:
```python
def test_RM_01_session_sl_first_hit():
    # Setup
    initialize_session()  # loads MTD from JSONL (real)
    market_state['session_pnl'] = -3500
    market_state['re_entries_used'] = 0
    
    # Run Risk Guard directly
    result = RiskGuardEngine.full_check(session_pnl=-3500, mtd_pnl=-3500)
    
    # Assert
    assert result['halt'] == False  # session SL not portfolio SL
    assert 'daily_sl_warning' in result['recommendations']  # at threshold
    
    # Run ReEntryTracker directly
    can_re = ReEntryTracker.can_re_enter()
    assert can_re == True  # 0 attempts used, halt False
    
    # Mark re-entry, verify counter
    ReEntryTracker.mark_re_entry()
    assert market_state['re_entries_used'] == 1
    
    # Try second re-entry → blocked
    can_re_2 = ReEntryTracker.can_re_enter()
    assert can_re_2 == False  # max attempts reached
```

This is **fast, deterministic, and tests the actual safety logic** without LLM noise.

---

## 6. Verification Hooks

### How to Assert "Did the Agent Do What We Wanted?"

#### Assertion 1: State Machine Snapshot
```python
def assert_state(expected: dict):
    """Assert market_state matches expected values."""
    for key, value in expected.items():
        actual = market_state.get(key)
        assert actual == value, f"{key}: expected {value}, got {actual}"

# Usage
assert_state({
    'gate_pass': True,
    'mtd_pnl': 1000,
    'exit_reason': 'Target hit',
    'halt': False,
})
```

#### Assertion 2: JSONL Audit Entry
```python
def read_last_jsonl():
    log_file = LOG_DIR / f"cfo_audit_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    with open(log_file) as f:
        lines = f.readlines()
    return json.loads(lines[-1]) if lines else None

# Usage
last = read_last_jsonl()
assert last['exit_reason'] == 'Stop loss'
assert last['capital_impact']['net_pnl'] == -3500
```

#### Assertion 3: Agent Execution Order
```python
# Using step_callback (Pattern 3)
expected_order = [
    'Market Scanner',
    'Trade Strategist',
    'Risk Guard',
    'Executor',
    'Sentinel',
    'Auditor',
]
actual_order = [s['agent'] for s in captured_steps]
assert actual_order == expected_order, f"Order mismatch: {actual_order}"
```

#### Assertion 4: LLM Call Count (Verify Deterministic Path)
```python
# Risk Guard should NOT call LLM
mock_llm_calls = []

def track_llm(messages, **kwargs):
    mock_llm_calls.append(messages)
    # ... return canned response

# After test
risk_guard_calls = [c for c in mock_llm_calls 
                    if 'risk guard' in str(c).lower()]
# Risk Guard's LLM is for *recommendation text only*, not gating
# But the deterministic full_check() should fire regardless
assert market_state['halt'] == True  # halt is deterministic
```

#### Assertion 5: Telegram Messages Sent
```python
def read_telegram_log():
    """Read mock Telegram queue."""
    path = '/tmp/antariksh_telegram_test.txt'
    if not Path(path).exists():
        return []
    with open(path) as f:
        return [line.strip() for line in f]

# Usage
telegram_msgs = read_telegram_log()
assert any('SL HIT' in m for m in telegram_msgs)
assert any('Re-entry option' in m for m in telegram_msgs)
```

#### Assertion 6: No LLM Call in Critical Path

```python
# Verify Executor placed orders WITHOUT calling LLM (deterministic)
def test_executor_no_llm():
    captured_llm = []
    
    def track_llm(*args, **kwargs):
        captured_llm.append(('llm_call', args, kwargs))
        return {"choices": [{"message": {"content": "OK"}}]}
    
    with mock.patch('litellm.completion', side_effect=track_llm):
        # Setup: Risk Guard has approved
        market_state['risk_ok'] = True
        market_state['trade_plan'] = {...}
        
        # Direct Executor call (deterministic path)
        from crew_structure import execute_trade
        execute_trade()
    
    # Per spec: Executor llm_assignment = "none" (deterministic)
    executor_calls = [c for c in captured_llm if 'executor' in str(c).lower()]
    assert len(executor_calls) == 0, "Executor should NOT call LLM"
```

---

## 7. Building a Scenario Runner

Putting it all together, a complete scenario test fixture:

```python
# tests/scenario_runner.py
import os
import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import contextmanager
from unittest import mock

class ScenarioRunner:
    """
    Runs an Antariksh scenario end-to-end with full mocking.
    
    Usage:
        with ScenarioRunner("RM-01") as sc:
            sc.set_time("2026-05-12 10:30:00")
            sc.set_market(vix=14, nifty=24500)
            sc.set_pnl_trajectory([-500, -1500, -2500, -3500])  # SL hit
            sc.seed_history(days=0)  # clean slate
            sc.set_llm_responses({
                "scanner": '{"vix": 14, "gate_pass": true}',
                "strategist": '{"strikes": [24500, 24800, 24200]}',
            })
            
            result = sc.run()
            
            sc.assert_state({
                'exit_reason': 'Stop loss',
                'session_pnl': -3500,
                're_entries_used': 0,
                'halt': False,
            })
            sc.assert_jsonl({'exit_reason': 'Stop loss'})
            sc.assert_telegram_contains('SL HIT')
            sc.assert_agent_order(['Scanner', 'Strategist', 'Risk Guard', 'Executor', 'Sentinel', 'Auditor'])
    """
    
    def __init__(self, scenario_id):
        self.scenario_id = scenario_id
        self.test_dir = None
        self.captured_steps = []
        self.original_state = None
    
    def __enter__(self):
        self.test_dir = tempfile.mkdtemp(prefix=f"antariksh_{self.scenario_id}_")
        self.test_log_dir = Path(self.test_dir) / "logs"
        self.test_log_dir.mkdir()
        
        # Patch LOG_DIR
        from crew_structure import Phase1Config
        self.original_log_dir = Phase1Config.LOG_DIR
        Phase1Config.LOG_DIR = self.test_log_dir
        
        # Save market_state
        from crew_structure import market_state
        self.original_state = market_state.copy()
        
        # Set mock mode
        os.environ['ANTARIKSH_MOCK_MODE'] = '1'
        
        # Mock telegram path
        os.environ['ANTARIKSH_TELEGRAM_PATH'] = str(Path(self.test_dir) / "telegram.txt")
        
        return self
    
    def __exit__(self, *args):
        # Restore
        from crew_structure import Phase1Config, market_state
        Phase1Config.LOG_DIR = self.original_log_dir
        market_state.clear()
        market_state.update(self.original_state)
        
        # Cleanup
        shutil.rmtree(self.test_dir)
    
    def set_time(self, iso_str):
        os.environ['ANTARIKSH_MOCK_TIME'] = iso_str
    
    def set_market(self, vix, nifty):
        os.environ['ANTARIKSH_MOCK_VIX'] = str(vix)
        os.environ['ANTARIKSH_MOCK_NIFTY'] = str(nifty)
    
    def set_pnl_trajectory(self, trajectory):
        os.environ['ANTARIKSH_MOCK_PNL_TRAJECTORY'] = json.dumps(trajectory)
        os.environ['ANTARIKSH_MOCK_PNL_IDX'] = '0'
    
    def seed_history(self, days, daily_pnl=None):
        """Seed JSONL history."""
        if days == 0:
            return
        if daily_pnl is None:
            daily_pnl = [0] * days
        
        today = datetime.now()
        for i in range(days):
            date = today - timedelta(days=days - i)
            date_str = date.strftime("%Y-%m-%d")
            entry = {
                "timestamp": date.isoformat(),
                "date": date_str,
                "trade_executed": True,
                "capital_impact": {"net_pnl": daily_pnl[i]}
            }
            log_file = self.test_log_dir / f"cfo_audit_{date_str}.jsonl"
            with open(log_file, 'a') as f:
                f.write(json.dumps(entry) + "\n")
    
    def set_llm_responses(self, response_map):
        self.llm_response_map = response_map
    
    def _mock_llm(self, messages, **kwargs):
        system = next((m['content'] for m in messages if m['role'] == 'system'), '')
        for key, response in self.llm_response_map.items():
            if key.lower() in system.lower():
                return {"choices": [{"message": {"content": response}}]}
        return {"choices": [{"message": {"content": "{}"}}]}
    
    def _step_callback(self, step):
        self.captured_steps.append({
            "agent": getattr(step, 'agent', {}).role if hasattr(step, 'agent') else None,
            "output": str(step)
        })
    
    def run(self):
        from crew_structure import run_full_session, initialize_session, antariksh_crew
        
        # Patch step_callback
        antariksh_crew.step_callback = self._step_callback
        
        with mock.patch('litellm.completion', side_effect=self._mock_llm):
            initialize_session()  # reads JSONL we seeded
            result = run_full_session(mock_mode=True)
        
        return result
    
    def assert_state(self, expected):
        from crew_structure import market_state
        for key, value in expected.items():
            actual = market_state.get(key)
            assert actual == value, f"{self.scenario_id}: state[{key}] expected {value}, got {actual}"
    
    def assert_jsonl(self, contains):
        log_file = self.test_log_dir / f"cfo_audit_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        with open(log_file) as f:
            entries = [json.loads(line) for line in f]
        last = entries[-1]
        for key, value in contains.items():
            assert last.get(key) == value, f"{self.scenario_id}: jsonl[{key}] expected {value}"
    
    def assert_telegram_contains(self, substring):
        path = os.environ.get('ANTARIKSH_TELEGRAM_PATH')
        with open(path) as f:
            content = f.read()
        assert substring in content, f"{self.scenario_id}: telegram missing '{substring}'"
    
    def assert_agent_order(self, expected):
        actual = [s['agent'] for s in self.captured_steps if s['agent']]
        assert actual == expected, f"{self.scenario_id}: agent order mismatch. Got {actual}"
```

### Using the Runner

```python
# tests/test_scenarios.py
def test_HP_01_clean_win():
    with ScenarioRunner("HP-01") as sc:
        sc.set_time("2026-05-12 10:30:00")
        sc.set_market(vix=14, nifty=24500)
        sc.set_pnl_trajectory([0, 200, 500, 800, 1000])  # target hit
        sc.seed_history(days=0)
        sc.set_llm_responses({
            "scanner": '{"vix": 14, "gate_pass": true}',
            "strategist": '{"strikes": [24500, 24800, 24200]}',
        })
        
        sc.run()
        
        sc.assert_state({
            'exit_reason': 'Target hit',
            'session_pnl': 1000,
            'mtd_pnl': 1000,
            'halt': False,
        })

def test_RM_01_sl_first_hit():
    with ScenarioRunner("RM-01") as sc:
        sc.set_time("2026-05-12 11:45:00")
        sc.set_market(vix=14, nifty=24500)
        sc.set_pnl_trajectory([-500, -1500, -2500, -3500])  # SL trajectory
        sc.seed_history(days=0)
        sc.set_llm_responses({
            "scanner": '{"vix": 14, "gate_pass": true}',
            "strategist": '{"strikes": [24500, 24800, 24200]}',
        })
        
        sc.run()
        
        sc.assert_state({
            'exit_reason': 'Stop loss',
            'session_pnl': -3500,
            're_entries_used': 0,  # not yet attempted re-entry
            'halt': False,  # single-instrument SL, not portfolio
        })
        sc.assert_jsonl({'exit_reason': 'Stop loss'})
        sc.assert_telegram_contains('SL HIT')

def test_RM_04_30day_dd_breach():
    with ScenarioRunner("RM-04") as sc:
        sc.set_time("2026-05-12 09:30:00")
        sc.set_market(vix=14, nifty=24500)
        # Seed 28 days of small losses + today's -3500 = -30000 exact
        sc.seed_history(days=28, daily_pnl=[-946] * 28)  # 28 * -946 = -26488; close to -26500
        sc.set_pnl_trajectory([-1500, -2500, -3500])
        
        sc.run()
        
        sc.assert_state({
            'halt': True,
            'session_pnl': -3500,
        })
        sc.assert_jsonl({'kill_switch_triggered': 'rolling_30d'})
```

---

## 8. Per-Scenario Mock Recipes

### HP-04 (Event Day Skip) — Currently FAILS due to broken event_calendar
```python
def test_HP_04_event_day():
    with ScenarioRunner("HP-04") as sc:
        sc.set_time("2026-04-08 09:30:00")  # RBI day
        sc.set_market(vix=14, nifty=24500)
        # Inject event calendar (currently this won't work — is_event_day() always returns False)
        os.environ['ANTARIKSH_MOCK_EVENT_DAY'] = 'RBI Policy'
        
        sc.run()
        
        sc.assert_state({'gate_pass': False, 'gate_reason': 'event_day'})
        # EXPECTED FAILURE until event_calendar.py is implemented
```

### RM-02 (2nd SL → Hard Halt)
```python
def test_RM_02_second_sl_halt():
    with ScenarioRunner("RM-02") as sc:
        sc.set_time("2026-05-12 12:30:00")
        sc.set_market(vix=14, nifty=24500)
        sc.seed_history(days=0)
        # First trajectory: SL at -3500
        sc.set_pnl_trajectory([-1000, -2000, -3000, -3500])
        sc.run()  # First trade: SL hit
        sc.assert_state({'session_pnl': -3500, 're_entries_used': 0})
        
        # Trigger re-entry approval
        from crew_structure import ReEntryTracker
        ReEntryTracker.mark_re_entry()
        
        # Run second trade with another SL trajectory
        sc.set_pnl_trajectory([-500, -1500, -3500])  # 2nd SL
        sc.run()
        
        sc.assert_state({
            'halt': True,  # portfolio SL exceeded -4500 → halt
            'session_pnl': -3500,  # this session
            're_entries_used': 1,
        })
        sc.assert_jsonl({'kill_switch_check': 'two_consecutive_session_sl_breaches'})
```

### MC-01 (Intraday VIX Spike)
```python
def test_MC_01_intraday_vix_spike():
    with ScenarioRunner("MC-01") as sc:
        sc.set_time("2026-05-12 09:30:00")
        sc.set_market(vix=15, nifty=24500)
        sc.seed_history(days=0)
        
        # Inject VIX trajectory: starts 15, spikes to 22 at 11:00
        os.environ['ANTARIKSH_MOCK_VIX_TRAJECTORY'] = json.dumps([
            {"time": "09:30", "vix": 15.0},
            {"time": "10:30", "vix": 16.0},
            {"time": "11:00", "vix": 22.0},  # SPIKE
        ])
        
        sc.run()
        
        # Expected: position opened, then closed when VIX > 20
        sc.assert_state({'exit_reason': 'vix_spike_intraday'})
        # NOTE: This will FAIL until Scanner has real-time loop (currently single-fetch)
```

### SF-05 (Sentinel Blackout)
```python
def test_SF_05_sentinel_blackout():
    with ScenarioRunner("SF-05") as sc:
        sc.set_time("2026-05-12 12:00:00")
        sc.set_market(vix=14, nifty=24500)
        sc.seed_history(days=0)
        
        # Inject Sentinel timeout
        os.environ['ANTARIKSH_MOCK_SENTINEL_TIMEOUT'] = '1'  # signal blackout
        
        sc.run()
        
        sc.assert_state({
            'exit_reason': 'sentinel_blackout',
            'emergency_close': True,
        })
        # NOTE: This will FAIL until Sentinel timeout handling is implemented
```

---

## 9. Common Pitfalls

### Pitfall 1: Module-Level Imports Bind LLM at Import Time
The agents in `crew_structure.py` are constructed at module load:
```python
scanner = Agent(role="Market Scanner", ..., llm=deepseek_llm)
```
Patching `deepseek_llm` after import won't affect already-constructed agents. **Fix:** Either reimport modules or construct a fresh test crew.

### Pitfall 2: market_state Is Shared State
Tests that don't reset `market_state` will pollute each other:
```python
# Bad
def test_a(): market_state['halt'] = True
def test_b(): assert market_state['halt'] == False  # FAILS due to test_a
```
**Fix:** Use `ScenarioRunner` context manager (saves/restores).

### Pitfall 3: JSONL Files in Real Logs Directory
Tests writing to `/home/trading_ceo/antariksh/logs/` corrupt real audit trail.
**Fix:** Always use `tempfile.mkdtemp()` and patch `LOG_DIR`.

### Pitfall 4: CrewAI Hierarchical Process — Manager Re-Routes
With `Process.hierarchical`, the Orchestrator (manager) decides task order dynamically based on its LLM call. Mock LLM may return order different from spec.
**Fix:** For deterministic agent-order tests, use `Process.sequential` in test crew, OR mock Orchestrator's LLM to return the canonical order.

### Pitfall 5: LiteLLM Caches Models
LiteLLM may cache LLM clients. After patching, may need:
```python
import litellm
litellm.cache = None  # or reset
```

### Pitfall 6: Time Travel Across Module Boundaries
`freezegun.freeze_time()` only patches `datetime.datetime`. If a module did `from datetime import datetime as dt`, that imported reference is NOT patched.
**Fix:** Use `freeze_time(..., tick=True)` and verify modules use `datetime.datetime.now()` not aliased imports.

### Pitfall 7: ANTARIKSH_MOCK_PNL_IDX Leaks
Setting trajectory index in env var leaks across tests:
```python
os.environ['ANTARIKSH_MOCK_PNL_IDX'] = '0'  # reset before each test
```

### Pitfall 8: Risk Guard Should NOT Call LLM
Per spec, Risk Guard's *gating* is deterministic. Its LLM is only for *recommendation text*. If a test sees LLM calls in critical path, that's a regression.
**Fix:** Track LLM calls, assert Risk Guard's halt decision is set BEFORE any LLM completes.

---

## Summary: How to Verify a Scenario

For any scenario, you need to verify these 5 things:

1. **Agents fire in expected order** → use `step_callback`, capture `captured_steps`
2. **State machine ends correctly** → `assert_state(market_state, expected)`
3. **JSONL audit is correct** → `assert_jsonl(last_entry, expected)`
4. **Telegram messages dispatched** → `assert_telegram_contains(substring)`
5. **Deterministic engines fired** → assert RiskGuard halt decisions, Auditor MTD calculation

Plus, for negative tests:
6. **No LLM call in deterministic critical path** → track `litellm.completion` calls

---

## Implementation Roadmap

**Day 1 (Sat):** Build `ScenarioRunner` + 5 critical scenarios
**Day 2 (Sun):** Run all 32 scenarios, file failures, fix highest-impact gaps
**Day 3 (Mon):** Re-run, target 80%+ pass rate

**Files to create:**
- `tests/scenario_runner.py` — the runner
- `tests/test_scenarios.py` — one function per scenario
- `tests/fixtures/seed_history.py` — JSONL seeding helpers
- `tests/fixtures/mock_llm.py` — canned LLM responses
- `tests/fixtures/mock_broker.py` — mock broker manager

**Files to modify:**
- `crew_structure.py` — extract `LOG_DIR` to be patchable; expose `step_callback` injection point
- `broker_manager.py` — read more env vars for trajectory simulation
- `telegram_bridge.py` — read `ANTARIKSH_TELEGRAM_PATH` env var for redirect

---

## Sign-Off

**Author:** Claude (interim CEO)
**Companion document:** `SCENARIO_TEST_PLAN.md` (the WHAT)
**This document:** the HOW
**Next step:** Build `ScenarioRunner` Saturday morning; run 5 critical scenarios by Saturday evening.
