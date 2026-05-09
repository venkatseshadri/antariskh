# Antariksh — Autonomous Intraday Options Trading System

## What This Is

Antariksh is a multi-crew, multi-agent autonomous intraday options trading system implementing the Varaha Iron Butterfly + Credit Spread strategies on NIFTY via Shoonya/Flattrade brokers. Built with CrewAI hierarchical governance under Ralph Loop PRD-driven verification. Goal: generate ₹36L/year passive income for retirement at 50.

## Core Value

Don't burn capital. Every trade decision passes through hard runtime risk gates (₹3,500 daily SL, ₹4,500 portfolio SL, VIX<20 skip) enforced in code, not agent judgment.

## Requirements

### Validated

- ✓ Session orchestrator with 9:30 AM / 2:35 PM cron — Phase 1, operational
- ✓ Event calendar (22 NSE holiday/RBI dates, 2 scheduled shutdowns) — Phase 1
- ✓ Token refresh (Shoonya + Flattrade dual-broker) — Phase 1
- ✓ Telegram bridge (PicoClaw: Kubera/Minimax) with HITL gates — Phase 1
- ✓ Executor reports (JSON) with Two-Message Protocol — Phase 1
- ✓ 32/32 scenario tests passing (engine-only, mock LLM/market) — Phase 1
- ✓ Ralph Loop constitution (vision, mission, goals, resource limits, authority) — Phase 2 foundations
- ✓ 6 PRDs (CEO, PM, OM, TA, AM, PA) with min_samples conditions — Phase 2 foundations
- ✓ Ralph Loop engine (8 classes: RalphLoop, CrewAIRalphLoop, PRDRalphLoop, RalphScheduler, etc.) — Phase 2 foundations
- ✓ GSD codebase map (7 docs: STACK, ARCHITECTURE, STRUCTURE, CONVENTIONS, TESTING, INTEGRATIONS, CONCERNS) — Phase 2

### Active

- [ ] OPS-01: Operations Manager crew (infra health: token refresh, code verification, data capture, disk, network, crons) with 17 tests
- [ ] TRA-01: Trading Analyst crew (execution validation: every trade matches PM spec) with 15 tests
- [ ] PM-01: Portfolio Manager crew (strategy: IB/Credit Spread selection, indicator weights, ATM rules) with 12 tests
- [ ] AM-01: Asset Manager crew (financials: cumulative P&L, margin, broker costs, burn trends) with 11 tests
- [ ] PA-01: Post-Mortem Analyst crew (trade reviews, counterfactuals, improvement recommendations) with 14 tests
- [ ] CEO-01: CEO crew (alignment guardian, crew performance oversight, board reporting) with 20 tests
- [ ] GA-01: Governance & Alignment tests (15 tests)
- [ ] INT-01: Inter-crew communication (design decision pending: file-based vs shared state vs call chain) with 12 tests
- [ ] RL-01 to RL-04: Ralph Loop infrastructure tests (scheduled PRD check, YAML loading, auto-escalation, PRD evolution)

### Out of Scope

- MCX evening trading — deferred to Phase 3-4
- SENSEX instruments — deferred to Phase 3
- Full autonomy (L4 trust ladder) — deferred to Phase 4
- Multi-strategy simultaneous execution — resource limit caps at 2 strategies
- Live money — Phase 2 is shadow/dry-run parallel to Phase 1

## Context

**Technical environment:** Python 3.9+, CrewAI multi-agent framework, DeepSeek LLM for agent cognition, Shoonya + Flattrade broker APIs, DuckDB for market data storage, PicoClaw for Telegram integration, systemd cron scheduling.

**Architecture:** 4-crew hierarchical organization under CEO governance + Ralph Loop PRD verification layer. Portfolio Manager (strategy) → Trading Analyst (execution validation) → Asset Manager (financials). Operations Manager (infra watchdog). Post-Mortem Analyst (trade review feedback to PM). CEO + Ralph Loop provide governance overlay.

**Design philosophy:** TDD mandatory. Write tests first, get user review, then build. Do not move to next step without passing tests. Deterministic code in tools, LLM cognition only for decisions requiring judgment. PRD min_samples pattern prevents false FAIL on immature metrics.

**Prior work:** Phase 1 collapsed 7-agent design into 1 agent + 6 deterministic tools (reduced LLM calls by 90%). User criticized as "trivial" — Phase 2 corrects this with proper multi-crew architecture.

## Constraints

- **Tech stack:** Python 3.9+, CrewAI, DeepSeek LLM, YAML configs, pytest — Must run on existing Ubuntu server
- **Timeline:** Phase 1 live Monday (dry-run); Phase 2 timeline TBD
- **Budget:** DeepSeek API costs (LLM calls), Shoonya/Flattrade broker APIs (free), Telegram (free via PicoClaw)
- **Dependencies:** Broker APIs must be reachable; DeepSeek API key must be valid; cron must be running
- **Performance:** LLM context windows must stay under limits (subagent parallel execution preserves context)
- **Security:** API keys must never be hardcoded (env vars only); repo is private on GitHub
- **Compatibility:** Must coexist with Phase 1 (parallel run: Phase 1 = live, Phase 2 = shadow)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 4-crew hierarchy + CEO (not 7-agent flat) | Proper separation of concerns; PM owns strategy, TA validates execution, AM owns financials | — Pending |
| Ralph Loop PRD verification (not inside any crew) | Meta-governance layer above CrewAI; each crew maintains separate memory | — Pending |
| TDD with 120 tests before any crew code | Enforces "don't burn capital" at architectural level; catches design flaws early | — Pending |
| Start with OM + TA first | Immediate needs: infra health + trade validation; PM/AM/PA/CEO follow | — Pending |
| Inter-crew comms deferred | "Figure out separately, finish tests first" | — Pending |
| min_samples pattern for PRD verification | ~75% of PRDs Day-1 verifiable; immature metrics get DATA_IMMATURE status | — Pending |
| Dual-broker (Shoonya + Flattrade) | Redundancy; Shoonya primary, Flattrade backup | — Pending |
| DeepSeek LLM over GPT-4 | Cost efficiency for 90% reduced LLM calls | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition:**
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone:**
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state (users, feedback, metrics)

---
*Last updated: 2026-05-09 after GSD initialization*
