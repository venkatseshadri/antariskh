# DeepSeek CrewAI Phase 2 Build Handoff

**Date:** 2026-05-08  
**Status:** Claude Haiku approaching rate limit. Switching to DeepSeek for Phase 2 CrewAI build.  
**Handoff Time:** ~22:40 IST  
**Resume Time:** Claude resumes after cooldown (~2-3 hours)

---

## Mission

Build the **CrewAI multi-agent framework** for Phase 2 of Antariksh trading system. This work runs **in parallel with Phase 1 MVP** (which is complete and ready for weekend testing).

**Outcome Expected:**
- `crew_structure.py` — CrewAI Agent + Task definitions (3 files)
- `crew_test.py` — Mock crew dry-run test
- `CREW_SPEC.md` — Agent role specs + task flow diagram
- Progress report (see "Reporting Back" section)

**Timeline:** Build during Claude's cooldown (~2-3 hours). Claude resumes to integrate + validate.

---

## Context: What Has Been Done

### Phase 1 MVP (100% Complete)

Phase 1 is a **standalone, non-autonomous system** running with Claude as interim CEO:
- Entry gate (9:30 AM): VIX < 20, entry window check → trade plan → Telegram
- Exit (2:35 PM): backtest → P&L → CFO audit → Telegram
- CFO auditor: reads-only, logs L1 invariants, **does NOT make autonomous decisions**
- Broker manager: Shoonya (primary data) + Flattrade (₹0 brokerage execution)
- Backtester: Black-Scholes P&L for iron fly
- Mock mode: Fully tested with VIX/NIFTY/TIME env vars

**Phase 1 runs Monday 9:30 AM** with live data. Phase 1 is **not your concern** — it works standalone.

### Relevant Files to Read (in order)

1. **`/home/trading_ceo/antariksh/STRATEGY_DESIGN_QUESTIONS.md`**
   - 22 strategic decisions + L1/L2/L3 governance layers
   - Agent roles hinted at ("who decides what")
   - Read this FIRST to understand the system

2. **`/home/trading_ceo/.planning/ROADMAP.md`**
   - Phase definitions (Phase 1 = MVP, Phase 2 = money in play, Phase 2+ = self-evolution)
   - Phase 2 scope: autonomous multi-agent system, real capital

3. **Phase 1 Implementation (reference only, don't modify):**
   - `/home/trading_ceo/antariksh/phase1_mvs.py` — gate logic, trade planning
   - `/home/trading_ceo/antariksh/backtester.py` — P&L calculation
   - `/home/trading_ceo/antariksh/cfo_auditor.py` — L1 audit (read-only in Phase 1)
   - `/home/trading_ceo/antariksh/broker_manager.py` — dual-broker interface
   - `/home/trading_ceo/antariksh/telegram_bridge.py` — async messaging

4. **Project Context:**
   - `/home/trading_ceo/.planning/PROJECT.md` — governance, 4-year runway, capital allocation
   - `/home/trading_ceo/.planning/STRATEGY_REFERENCE.md` — full Varaha strategy spec (optional deep dive)
   - `/home/trading_ceo/.claude/projects/-home-trading_ceo/memory/antariksh_project.md` — project summary

---

## Your Task: Build CrewAI Phase 2 Framework

### What You're Building

A **7-agent crew** that runs autonomously during market hours (9:15 AM–3:30 PM IST).

**Phase 2 Roles (Agents):**

1. **Orchestrator**
   - Role: Coordinator + timing authority
   - Tasks: 
     - Manage entry/exit windows (call Scanner + Strategist at 9:30 AM, call Executor at 2:35 PM)
     - Coordinate handoffs between agents
   - Autonomy: Can pause/resume trades based on Risk Guard alerts

2. **Scanner**
   - Role: Real-time market data ingestion
   - Tasks:
     - Fetch NIFTY spot, VIX, option chain every minute
     - Update shared market state
     - Alert on data failures
   - Integration: Reads from BrokerManager (Shoonya API)

3. **Strategist**
   - Role: Trade plan generation + position management
   - Tasks:
     - Generate entry signals (Layer 2: supertrend_1min, Layer 3: multi-indicator)
     - Calculate position size (1 lot for Phase 2)
     - Recommend re-entry if SL hit + 1 attempt remaining
   - Autonomy: Can suggest trade plan, Executor executes

4. **Executor**
   - Role: Order placement + position tracking
   - Tasks:
     - Place orders (iron fly 4-leg basket) via Flattrade
     - Track open positions
     - Execute SL/target closes
   - Autonomy: Follows Strategist plans, reports fills to Sentinel

5. **Sentinel**
   - Role: Real-time P&L tracking + exit monitoring
   - Tasks:
     - Track MTD P&L (mark-to-market)
     - Monitor SL/target prices
     - Alert Risk Guard if SL breach imminent
   - Integration: Reads positions from Executor, quotes from Scanner

6. **Risk Guard**
   - Role: Capital preservation + hard limits
   - Tasks:
     - Check daily SL (₹3,500), portfolio cumulative (₹4,500), 30-day DD (₹30K)
     - Force close positions if capital floor breached (10-day burn > 30% free cash)
     - Recommend position size reductions
   - Autonomy: **Can autonomously halt trading** if L1 capital rules broken
   - Integration: Reads CFO audit trail from Phase 1, reads positions + P&L from Sentinel

7. **Auditor**
   - Role: Governance logging + L1 invariant validation
   - Tasks:
     - Log every session decision (gate check, trade plan, P&L, verdict)
     - Validate L1 invariants (same checks as Phase 1 CFO auditor)
     - Generate daily/weekly/monthly reports
   - Output: Append to JSONL audit trail (`logs/cfo_audit_YYYY-MM-DD.jsonl`)
   - Read: Can integrate Phase 1 CFO auditor logs (already in JSONL format)

---

## Implementation Guidance

### Tech Stack

- **Framework:** CrewAI (Python)
- **LLM for agents:** DeepSeek (you) for code generation, Opus for reasoning (Strategist + Risk Guard only for cost optimization)
- **Broker API:** Shoonya (primary), Flattrade (execution)
- **Async:** Use CrewAI's native task scheduling + Python asyncio where needed

### File Structure to Create

```
/home/trading_ceo/antariksh/
├── crew_structure.py          # Agent + Task definitions (MAIN FILE)
├── crew_test.py               # Mock crew dry-run test
├── agents/
│   ├── orchestrator.py        # (optional: separate agent logic if complex)
│   ├── scanner.py
│   ├── strategist.py
│   ├── executor.py
│   ├── sentinel.py
│   ├── risk_guard.py
│   └── auditor.py
└── CREW_SPEC.md               # Agent role specs + task flow diagram
```

**Minimum viable output (for your handoff):**
- `crew_structure.py` — All 7 agents + tasks in ONE file (don't over-architect)
- `crew_test.py` — Mock test with Phase 1 mock data
- `CREW_SPEC.md` — 1-page agent summary + sequence diagram

---

## What Crew Structure Should Look Like

### Example Structure (pseudo-code)

```python
from crewai import Agent, Task, Crew
from crewai.llm import LLM

# Market data agent
scanner = Agent(
    role="Market Scanner",
    goal="Provide real-time market data (NIFTY spot, VIX, option chain)",
    backstory="Real-time data ingestion agent...",
    # Use gpt-4 level reasoning
)

# Trade strategy agent
strategist = Agent(
    role="Trade Strategist",
    goal="Generate trade plans with iron fly 4-leg baskets",
    backstory="...",
    # Use Opus for reasoning (cost optimization)
)

# Risk management agent
risk_guard = Agent(
    role="Risk Guard",
    goal="Enforce L1 capital preservation rules",
    backstory="...",
    # Can autonomously halt trading
)

# Tasks
scan_market_task = Task(
    description="Fetch NIFTY spot and VIX every minute...",
    agent=scanner,
)

generate_plan_task = Task(
    description="Generate iron fly trade plan if gate passes...",
    agent=strategist,
    depends_on=[scan_market_task],  # Depends on market data
)

check_capital_task = Task(
    description="Validate capital preservation rules...",
    agent=risk_guard,
)

# Crew
crew = Crew(
    agents=[scanner, strategist, executor, sentinel, risk_guard, auditor, orchestrator],
    tasks=[scan_market_task, generate_plan_task, ...],
    manager_agent=orchestrator,  # Orchestrator coordinates
)
```

---

## Integration Points (What You Need to Know)

### 1. Market Data Input
- **Source:** `broker_manager.BrokerManager.get_vix()` and `get_nifty_spot()`
- **Mock mode:** Set `ANTARIKSH_MOCK_MODE=1` for testing
- **Real mode:** Uses actual Shoonya OAuth session (Monday)

### 2. Order Execution
- **Target:** `broker_manager.BrokerManager.place_order(side, instrument, qty, order_type, price)`
- **Fallback:** Shoonya if Flattrade fails
- **Phase 2 note:** This is currently TODO; Executor agent will need to implement

### 3. Position Tracking
- **Source:** `broker_manager.BrokerManager.get_position(instrument)`
- **What to track:** Iron fly 4-leg position (long PUT, short PUT, short CALL, long CALL)

### 4. CFO Audit Trail
- **Phase 1 logs:** `/home/trading_ceo/antariksh/logs/cfo_audit_YYYY-MM-DD.jsonl` (JSONL format)
- **Auditor task:** Append new session records with same schema as Phase 1
- **Risk Guard reads:** This trail to check cumulative DD + capital preservation

### 5. Telegram Bridge
- **Function:** `telegram_bridge.TelegramBridge.send_entry_gate()`, `send_exit_report()`, `send_alert()`
- **Fallback:** Console logging if picoclaw unavailable
- **Phase 2 use:** Orchestrator sends daily summaries, alerts on Risk Guard violations

### 6. Broker API Details
- **Shoonya:** `broker_manager.NorenApiPy` (already injected with OAuth header)
- **Flattrade:** Uses `broker_manager.Flattrade.load_token()` (₹0 brokerage)
- **Endpoints:** See `broker_manager.py` for token mappings (NIFTY50, INDIAVIX, etc.)

---

## Testing Your Build

### Test 1: Mock Crew Dry-Run
```bash
python3 crew_test.py --mock-mode --vix 18.5 --nifty 24500 --time 10:30
# Expected: Crew runs gate check → trade plan → backtest → audit
```

### Test 2: Task Dependencies
```bash
python3 crew_test.py --trace
# Expected: Scanner → Strategist → Executor → Sentinel → Auditor (in sequence)
```

### Test 3: Risk Guard Halt Scenario
```bash
python3 crew_test.py --capital-floor-breach
# Expected: Risk Guard autonomously halts trading, Orchestrator pauses
```

---

## Confusion? Reference These

**"How do agents communicate?"**
→ CrewAI's `depends_on` for task sequencing; shared state via context dict

**"What if Strategist needs Executor's position data?"**
→ Sentinel tracks positions, shares with Strategist via crew context

**"Should Risk Guard use LLM or hard rules?"**
→ Hard rules for capital thresholds (deterministic). LLM for recommendations only.

**"How do I mock market data for testing?"**
→ Use Phase 1's mock layer: `ANTARIKSH_MOCK_MODE=1`, `ANTARIKSH_MOCK_VIX=`, etc.

**"What if I hit CrewAI API limits?"**
→ Refer to CrewAI docs. For Phase 2, use agent-level LLM assignment (DeepSeek for Executor, Opus for Strategist only).

**"Do I need to implement Executor's order placement?"**
→ No. Create the Agent + Task stub. Claude will wire the actual Flattrade API on resume.

**"Should Auditor read Phase 1 CFO logs?"**
→ Yes. Parse `/home/trading_ceo/antariksh/logs/cfo_audit_YYYY-MM-DD.jsonl` at crew startup to get MTD P&L.

---

## How to Report Back

When you're done (or stuck), create **ONE** summary file:

**File:** `/home/trading_ceo/antariksh/DEEPSEEK_REPORT.md`

**Contents:**

```markdown
# DeepSeek CrewAI Build Report

## Status
- [ ] crew_structure.py created (7 agents + tasks)
- [ ] crew_test.py created (mock dry-run)
- [ ] CREW_SPEC.md created (role specs + diagram)

## What Was Built
1. Agent definitions: [list which agents you created]
2. Task definitions: [list tasks and dependencies]
3. Test harness: [mock scenario you tested]

## What Works
- [e.g., Orchestrator → Scanner → Strategist handoff tested]
- [e.g., Risk Guard halt logic implemented]

## What's TODO (for Claude to pick up)
- [ ] Executor.place_order() wiring to actual Flattrade API
- [ ] Sentinel.mark_to_market() integration with live quotes
- [ ] Auditor logging to Phase 1 CFO trail format
- [other blockers or incomplete items]

## Key Decisions Made
- [e.g., Used CrewAI's native task scheduling instead of custom async]
- [e.g., Risk Guard uses hard rules, not LLM for capital checks]

## Files Created
- /home/trading_ceo/antariksh/crew_structure.py (XX lines)
- /home/trading_ceo/antariksh/crew_test.py (XX lines)
- /home/trading_ceo/antariksh/CREW_SPEC.md

## Confidence Level
- Architecture: [High/Medium/Low]
- Code quality: [High/Medium/Low]
- Ready for Claude integration: [Yes/Partial/No]

## Notes for Claude
[Any gotchas, design choices, or assumptions Claude should know]
```

**Then post the report as a message to the user** so Claude can see it when resuming.

---

## Red Flags (What to Avoid)

❌ **Don't over-architect.** Use 1 file (`crew_structure.py`) for all agents if possible.  
❌ **Don't implement Flattrade order placement.** That's Claude's job (complex OAuth flow).  
❌ **Don't change Phase 1 files.** Phase 1 is locked and works standalone.  
❌ **Don't skip mocking.** Always test with `ANTARIKSH_MOCK_MODE=1` first.  
❌ **Don't ignore L1 rules.** Risk Guard's capital thresholds are non-negotiable (₹3,500 daily SL, etc.).  

---

## Success Criteria

When Claude resumes, they should be able to:

1. Run `python3 crew_test.py` and see a mock crew dry-run complete successfully
2. Read `CREW_SPEC.md` and understand all 7 agent roles + task dependencies in < 5 minutes
3. Read `crew_structure.py` and know exactly what's stubbed vs. complete
4. Pick up Executor.place_order(), Auditor.log_session(), Sentinel.mark_to_market() integration

---

## Questions While Building?

1. **Check STRATEGY_DESIGN_QUESTIONS.md** for strategic context
2. **Check Phase 1 reference files** (phase1_mvs.py, etc.) for patterns
3. **Check CrewAI docs** for task syntax
4. **Ask in DEEPSEEK_REPORT.md** if blocked (Claude will see it on resume)

---

## Timeline for Claude's Resume

- **Build time:** Now (2–3 hours during cooldown)
- **Resume time:** Claude back online
- **Integration:** 30–60 min to wire Flattrade + CFO audit
- **Testing:** Weekend mock validation
- **Monday 9:30 AM:** Phase 1 live with real data
- **Phase 2 launch:** TBD (after Phase 1 stabilizes)

---

**Go build. You've got this. 🚀**
