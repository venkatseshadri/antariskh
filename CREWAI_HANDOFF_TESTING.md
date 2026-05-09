# CrewAI Handoff / Choreography Testing

**Purpose:** How to validate that CrewAI agents actually call tools in the correct sequence, and (for multi-agent crews) delegate to the right agents in the right order.

**Audience:** Engineer writing Phase 2 agent tests. Chairman reviewing UAT gating.

**Context:** This document captures the testing methodology we discussed vs. PAUL methodology for validating agent behavior, handoff integrity, silent-drift detection, and UAT acceptance across Antariksh's CrewAI architecture.

---

## 1. What "Handoff" Means in This Codebase

There are two distinct handoff types:

### Type A: Tool-Calling Choreography (current Phase 2)

A **single Orchestrator agent** with 6 deterministic tools. "Handoff" is the LLM deciding which tool to call next:

```
LLM reasoning → scan_market → LLM reasoning → generate_trade_plan → LLM reasoning → check_risk → ...
```

The agent is at `crew_structure.py:341`. The tools are `scan_market`, `generate_trade_plan`, `check_risk`, `execute_trade`, `monitor_positions`, `log_audit`. The agent's system prompt says "Follow this EXACT sequence" — we need to verify it actually does.

### Type B: Multi-Agent Delegation (future Phase 2/3)

Multiple agents with `Process.hierarchical`. A manager agent (Orchestrator) delegates tasks to worker agents (Scanner, Strategist, etc.). "Handoff" is the manager routing to the right worker:

```
Manager LLM → "Delegate scan_market to Scanner" → Scanner.llm → calls tool → returns → Manager.llm → "Delegate to Strategist" → ...
```

The `crews/` directory already has crew definitions for this pattern: `ta_crew.py` (TradeValidator + ComplianceReporter), `om_crew.py`, `pm_crew.py`, etc.

---

## 2. The Four Test Layers

| Layer | What Runs | LLM? | Speed | Deterministic | What It Validates |
|-------|-----------|------|-------|---------------|-------------------|
| **L1: Engine-Only** | `RiskGuardEngine.full_check()`, `AuditorEngine`, `ReEntryTracker` directly | No | <1ms | Yes | Capital math, audit aggregation, counter logic |
| **L2: Tool-Only** | `scan_market.func()`, `generate_trade_plan.func()` etc. called directly | No | <1ms | Yes | Individual tool logic, state mutations |
| **L3: Mocked CrewAI** | `crew.kickoff()` with `MockLLM` injected into agent | Canned | <10ms | Semi | Tool-calling sequence, state after full session |
| **L4: Real LLM (UAT)** | `crew.kickoff()` with real DeepSeek API | Yes | 5-30s | No | End-to-end agent behavior, fuzzy assertions |

**Current status in Antariksh:**

- L1: 19 tests, all passing (zero LLM, pure math)
- L2: 0 tests (tools exist but are only tested indirectly)
- L3: **BROKEN** — `MockLLM` class exists at `tests/fixtures/mock_llm.py:9` but is never wired into the agent. `_build_crew()` at `crew_structure.py:769` has no LLM injection point.
- L4: 0 tests (crew_test.py runs against real LLM ad-hoc, not in pytest)

### Gap: L3 is the bridge between "the math is right" (L1) and "the agent behaves correctly" (L4). Without it, 13/32 ScenarioRunner tests are blocked.

---

## 3. L3 Implementation — Mocking the LLM in CrewAI

### The Core Problem

`crew_structure.py:357` binds `deepseek_llm` to the agent at module import time:

```python
orchestrator = Agent(
    role="Orchestrator",
    ...
    llm=deepseek_llm,          # <-- hardcoded, no override
    tools=[scan_market, ...],
)
```

Patching `deepseek_llm` after import won't affect the already-constructed agent. CrewAI agents copy the LLM reference at construction time.

### The Fix: Injection Point in `_build_crew()`

```python
# crew_structure.py:769 — CURRENT
def _build_crew():
    global _crew_cache
    if _crew_cache is None:
        _crew_cache = Crew(
            agents=[orchestrator],
            tasks=[run_session_task],
            process=Process.sequential,
            verbose=True,
        )
    return _crew_cache

# crew_structure.py:769 — FIXED
def _build_crew(llm_override=None):
    """
    Build the crew. If llm_override is provided, create a fresh agent
    with the mock LLM instead of deepseek_llm.
    """
    global _crew_cache
    if _crew_cache is None:
        agent = orchestrator
        if llm_override is not None:
            agent = Agent(
                role=orchestrator.role,
                goal=orchestrator.goal,
                backstory=orchestrator.backstory,
                tools=orchestrator.tools,
                llm=llm_override,
                verbose=False,
                allow_delegation=False,
            )
        _crew_cache = Crew(
            agents=[agent],
            tasks=[run_session_task],
            process=Process.sequential,
            verbose=False,
        )
    return _crew_cache
```

### Wiring MockLLM

The `MockLLM` class at `tests/fixtures/mock_llm.py:9` returns a CrewAI-compatible completion object. It needs one addition — a `call()` method matching CrewAI's LLM interface:

```python
# tests/fixtures/mock_llm.py — add to MockLLM class
def call(self, messages, **kwargs):
    """
    CrewAI-compatible call interface.
    Inspects messages to detect which tool the agent is considering,
    returns canned response from response_map.
    """
    # Detect agent role from message content
    role = "default"
    for msg in reversed(messages):
        content = str(msg.get("content", "")).lower()
        if "scanner" in content or "scan_market" in content:
            role = "scanner"; break
        elif "strategist" in content or "trade_plan" in content:
            role = "strategist"; break
        elif "executor" in content or "execute_trade" in content:
            role = "executor"; break
        elif "sentinel" in content or "monitor_positions" in content:
            role = "sentinel"; break
        elif "risk guard" in content or "check_risk" in content:
            role = "risk_guard"; break
        elif "auditor" in content or "log_audit" in content:
            role = "auditor"; break
        elif "orchestrator" in content:
            role = "orchestrator"; break

    response = self.response_map.get(role, self.response_map.get("default", "OK"))
    self.calls.append({"role": role, "response": response[:200], "canned": True})

    # Return CrewAI-compatible response object
    return type("LLMResponse", (), {
        "choices": [type("Choice", (), {
            "message": type("Message", (), {
                "content": response,
                "role": "assistant"
            })()
        })()],
        "usage": type("Usage", (), {
            "total_tokens": 100,
            "prompt_tokens": 70,
            "completion_tokens": 30
        })(),
    })()
```

---

## 4. Handoff Validation via `step_callback`

### Why step_callback is the Gold Standard

CrewAI's `Crew(step_callback=...)` fires **after every LLM reasoning step**. This gives you a trace of exactly which tool was called and in what order. No other assertion can prove "the agent followed the sequence" — state assertions only prove side effects happened, not who caused them or in what order.

### Implementation

```python
# crew_structure.py:769 — add step_callback support
_step_trace = []  # module-level for test access

def _on_step(step_output):
    """Record every tool invocation during crew execution."""
    for msg in getattr(step_output, 'messages', []):
        tool_calls = getattr(msg, 'tool_calls', None) or []
        for tc in tool_calls:
            _step_trace.append({
                "tool": tc.function.name,
                "args": json.loads(tc.function.arguments),
            })

def _build_crew(llm_override=None):
    global _crew_cache, _step_trace
    _step_trace = []  # reset on each build
    if _crew_cache is None:
        ...
        _crew_cache = Crew(
            agents=[agent],
            tasks=[run_session_task],
            process=Process.sequential,
            step_callback=_on_step,
            verbose=False,
        )
    return _crew_cache
```

### Assertion Pattern

```python
def test_HP_01_clean_win():
    """HP-01: Verify the agent calls tools in the CORRECT sequence."""
    with ScenarioRunner("HP-01") as sc:
        sc.set_market(vix=14.0, nifty=24500.0)
        sc.inject_llm_responses({
            "scanner": '{"vix": 14.0, "nifty_spot": 24500, "gate_pass": true}',
            "strategist": '{"status": "generated", "atm_strike": 24500, ...}',
            "risk_guard": '{"passed": true, "halt": false}',
            "executor": '{"status": "executed", "legs_executed": 4}',
            "sentinel": '{"session_pnl": 1000, "target_hit": true}',
            "auditor": '{"verdict": "passed", "mtd_pnl": 1000}',
        })
        sc.run()

        # THE KEY ASSERTION: did the LLM follow the sequence?
        expected_sequence = [
            "scan_market",
            "generate_trade_plan",
            "check_risk",
            "execute_trade",
            "monitor_positions",
            "log_audit",
        ]
        actual_sequence = [s["tool"] for s in crew_structure._step_trace if s.get("tool")]
        assert actual_sequence == expected_sequence, \
            f"Tool call order mismatch.\nExpected: {expected_sequence}\nActual:   {actual_sequence}"
```

### What step_callback Catches That State Assertions Miss

| Handoff failure | Caught by `step_callback`? | Caught by `market_state` assertions? |
|---|---|---|
| Agent calls tools in wrong order | Yes — sequence mismatch | No — state ends up same |
| Agent skips a tool | Yes — missing in trace | Maybe — if tool has side effect |
| Agent calls a tool twice | Yes — duplicate in trace | No — idempotent side effect |
| Agent delegates to wrong sub-agent (multi-agent) | Yes — `step_output.agent` field | No — state doesn't track agent |
| LLM hallucinates tool name | Yes — trace shows unexpected tool | Maybe — tool never runs |

---

## 5. Multi-Agent Delegation Assertions (Future Phase)

When the system expands to hierarchical crews with 2+ agents per crew:

### Pattern: Assert Which Agent Ran Each Task

```python
def test_ta_crew_delegation():
    """TA Crew: Verify manager delegates to correct agents."""
    result = ta_crew.kickoff(inputs={"trade": mock_trade})

    # Which agents actually executed tasks?
    agents_used = {t.agent for t in result.tasks_output}

    assert agents_used == {"TradeValidator", "ComplianceReporter"}, \
        f"Expected both agents to run, got: {agents_used}"

    # Did the Validator run BEFORE the Reporter? (tasks_output is ordered)
    assert result.tasks_output[0].agent == "TradeValidator"
    assert result.tasks_output[1].agent == "ComplianceReporter"

    # Did Validator's output feed into Reporter? (check raw content)
    validator_output = result.tasks_output[0].raw
    assert "valid" in validator_output.lower()
```

### Pattern: Assert Manager Didn'T Hog All Tasks

```python
def test_ta_crew_manager_delegates_properly():
    """Manager should delegate, not execute everything itself."""
    result = ta_crew.kickoff(inputs={...})

    agents_used = {t.agent for t in result.tasks_output}
    assert "Orchestrator" not in agents_used, \
        "Manager agent should delegate tasks, not execute them directly"
```

### Pattern: Cross-Crew Handoff (OM → PM → TA)

When you chain crews (`om_crew` feeds output into `pm_crew`), validate the contract:

```python
def test_om_to_pm_handoff():
    """OM crew output matches PM crew input contract."""
    om_result = om_crew.kickoff(inputs={"session": "entry"})
    om_raw = om_result.raw  # should contain gate_pass, vix, nifty

    # Parse OM output and feed into PM
    pm_input = json.loads(om_raw)
    pm_result = pm_crew.kickoff(inputs={"market_data": pm_input})

    # PM should generate a strategy spec
    assert "strategy_spec" in pm_result.raw or "trade_plan" in pm_result.raw
```

---

## 6. Full ScenarioRunner — L3+Handoff Combined

### Updated ScenarioRunner with LLM Injection + step_callback

```python
# tests/scenario_runner.py — UPDATED
class ScenarioRunner:
    def __init__(self, scenario_id: str):
        self.scenario_id = scenario_id
        self._tempdir = tempfile.mkdtemp(prefix=f"antariksh_{scenario_id}_")
        self._log_dir = Path(self._tempdir) / "logs"
        self._log_dir.mkdir(exist_ok=True)
        self._patches = []
        self._llm_responses = {}
        self.tool_call_trace = []

    def __enter__(self):
        os.environ.setdefault("ANTARIKSH_MOCK_MODE", "1")
        crew_structure.AuditorEngine.AUDIT_DIR = self._log_dir
        crew_structure.market_state.clear()
        crew_structure.market_state.update({ ... })  # reset
        return self

    def inject_llm_responses(self, response_map: Dict[str, str]):
        """Provide canned LLM responses keyed by agent/role name."""
        self._llm_responses = response_map

    def run(self) -> Dict:
        """Execute full CrewAI session with mock LLM and step_callback."""
        os.environ["ANTARIKSH_MOCK_MODE"] = "1"

        # Build mock LLM from response map
        mock_llm = MockLLM(self._llm_responses)

        # Build crew with mock LLM + step callback
        crew_structure._crew_cache = None  # bust cache
        crew = crew_structure._build_crew(llm_override=mock_llm)
        # WARNING: _build_crew needs to accept llm_override (see Section 3)

        crew_structure.initialize_session()
        result = crew.kickoff(inputs={
            "session_type": "full",
            "mock_mode": True,
        })

        # Capture tool call trace from step_callback
        self.tool_call_trace = list(crew_structure._step_trace)

        self.results = dict(crew_structure.market_state)
        self.results["crew_output"] = result
        return result

    def assert_tool_sequence(self, expected: List[str]):
        """Assert tools were called in exact order."""
        actual = [s["tool"] for s in self.tool_call_trace if s.get("tool")]
        assert actual == expected, \
            f"{self.scenario_id}: Tool sequence mismatch.\n  Expected: {expected}\n  Actual:   {actual}"

    def assert_agent_executed(self, agent_role: str, task_outputs):
        """Assert a specific agent was delegated at least one task."""
        agents_used = {t.agent for t in task_outputs}
        assert agent_role in agents_used, \
            f"{self.scenario_id}: Agent '{agent_role}' never executed. Agents used: {agents_used}"

    def assert_state(self, expected: Dict):
        errors = []
        for key, val in expected.items():
            actual = crew_structure.market_state.get(key)
            if actual != val:
                errors.append(f"{key}: expected {val}, got {actual}")
        assert not errors, f"State mismatch: {'; '.join(errors)}"
```

---

## 7. UAT Acceptance for CrewAI Behavior

For each crew/session type, the UAT gate should verify these 4 dimensions:

### Dimension 1: Tool Sequence Integrity

```python
def test_UAT_tool_sequence_happy_path():
    """UAT-01: On clean market, agent follows canonical sequence."""
    with ScenarioRunner("UAT-01") as sc:
        sc.set_market(vix=14.0, nifty=24500.0)
        sc.inject_llm_responses(make_mock_responses())
        sc.run()
        sc.assert_tool_sequence([
            "scan_market", "generate_trade_plan", "check_risk",
            "execute_trade", "monitor_positions", "log_audit",
        ])
```

### Dimension 2: Gate-Skip Integrity

```python
def test_UAT_gate_skip_skips_execution():
    """UAT-02: On VIX > 20, agent skips execution tools entirely."""
    with ScenarioRunner("UAT-02") as sc:
        sc.set_market(vix=22.0, nifty=24500.0)
        sc.inject_llm_responses({
            "scanner": '{"vix": 22.0, "gate_pass": false, "gate_reason": "VIX > 20"}',
            "strategist": '{"status": "skipped"}',
            "auditor": '{"verdict": "no_trade", "mtd_pnl": 0}',
        })
        sc.run()

        # Execution tools must NOT be called
        actual = [s["tool"] for s in sc.tool_call_trace if s.get("tool")]
        assert "execute_trade" not in actual, \
            f"execute_trade called despite gate_pass=False! Trace: {actual}"
        assert "monitor_positions" not in actual, \
            f"monitor_positions called despite gate_pass=False! Trace: {actual}"
```

### Dimension 3: Halt Integrity

```python
def test_UAT_risk_halt_blocks_execution():
    """UAT-03: On SL breach, agent halts before execute_trade."""
    with ScenarioRunner("UAT-03") as sc:
        sc.set_market(vix=14.0, nifty=24500.0)
        sc.inject_llm_responses({
            "scanner": '{"vix": 14.0, "gate_pass": true}',
            "strategist": '{"status": "generated", "atm_strike": 24500}',
            "risk_guard": '{"passed": false, "halt": true, "violations": ["Daily SL breached"]}',
            "auditor": '{"verdict": "halted", "mtd_pnl": -3500}',
        })
        sc.run()

        actual = [s["tool"] for s in sc.tool_call_trace if s.get("tool")]
        assert "execute_trade" not in actual, \
            f"execute_trade called despite halt=True! Trace: {actual}"
```

### Dimension 4: Silent Drift Detection

Each UAT cycle compares the Plan's specified sequence against what the agent actually did. If the agent started deviating (e.g., calling `check_risk` before `generate_trade_plan`), the UAT catches it immediately — this is the "Unify" step from a PAUL cycle baked into the test:

```python
def test_UAT_no_silent_drift():
    """
    PAUL Unify: After N iterations, verify the agent hasn't drifted
    from the canonical tool-calling sequence specified in the Plan.
    """
    expected = [...]  # from PLAN.md or the agent's system prompt
    for iteration in range(10):
        with ScenarioRunner(f"drift-check-{iteration}") as sc:
            sc.set_market(vix=random.uniform(12, 19), nifty=random.uniform(24400, 24600))
            sc.inject_llm_responses(make_mock_responses())
            sc.run()
            sc.assert_tool_sequence(expected)
```

---

## 8. Implementation Checklist

### Today (unblock L3 testing)

- [ ] Add `llm_override` parameter to `_build_crew()` in `crew_structure.py:769`
- [ ] Add `step_callback` recording to `_build_crew()` (module-level `_step_trace`)
- [ ] Fix `MockLLM.call()` to match CrewAI's LLM interface
- [ ] Wire `MockLLM` into `ScenarioRunner.inject_llm_responses()`
- [ ] Add `assert_tool_sequence()` to ScenarioRunner
- [ ] Run one test: `test_HP_01` with mocked LLM + tool sequence assertion

### This weekend (L3+L4 coverage)

- [ ] Write L3 tests for all 13 pending scenarios using mock LLM
- [ ] Write L4 tests for 4 critical UAT scenarios using real DeepSeek
- [ ] Integrate UAT drift checks into daily schedule

### Phase 3 (multi-agent crews)

- [ ] Add `assert_agent_executed()` to ScenarioRunner
- [ ] Write delegation tests for `ta_crew.py`, `om_crew.py`
- [ ] Write cross-crew handoff tests (OM → PM → TA)

---

## 9. GSD vs PAUL on Handoff Validation

| Concern | GSD Approach | PAUL Approach | Best Fit |
|---------|-------------|---------------|----------|
| Context-rot | Static docs (`TESTING_INFRASTRUCTURE.md`, `SCENARIO_TEST_PLAN.md`) that rot after each code change | Each Plan→Apply→Unify cycle refreshes the expected sequence from live agent output | PAUL (self-refreshing) |
| Silent drift | CONCERNS.md documents drift as "PRODUCTION GAP" | `assert_tool_sequence()` catches drift immediately in Unify phase | PAUL (enforcement, not documentation) |
| UAT acceptance | REQ-IDs → scenario tests → verifier; advisory, not blocking | UAT is the gate: cycle doesn't advance until Unify confirms output matches Plan | GSD (traceability) + PAUL (enforcement) |
| Handoff trace | step_callback trace (identical in both) | step_callback trace (identical in both) | Tie (same mechanism) |

---

## 10. Key Files Reference

| File | Lines | Role |
|------|-------|------|
| `crew_structure.py` | 966 | Agent, tools, crew builder — **needs llm_override + step_callback** |
| `tests/scenario_runner.py` | 166 | Mock injection context manager — **needs MockLLM wiring** |
| `tests/fixtures/mock_llm.py` | 66 | Canned LLM responses — **needs CrewAI call() interface** |
| `tests/test_scenarios.py` | 323 | 32 scenario tests — **13 pending need L3 mock path** |
| `crew_test.py` | 261 | Manual ad-hoc tests — **ad-hoc, not in pytest pipeline** |
| `TESTING_INFRASTRUCTURE.md` | 1159 | General testing infrastructure doc |
| `SCENARIO_TEST_PLAN.md` | 958 | What to test (scenario catalog) |
| `CRITICAL_FIXES_REQUIRED.md` | 401 | 3 blockers preventing L3 testing |

---

**Author:** Claude (interim CEO)
**Status:** Design document — awaiting chairman approval before implementation
**Next step:** Implement L3 injection point (Section 3), then run mock-crew test to verify tool sequence
