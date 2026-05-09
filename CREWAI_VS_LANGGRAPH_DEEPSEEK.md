# CrewAI vs LangGraph — Decision Matrix for Project Antariksh

**Date:** 2026-05-08
**Research Agent:** DeepSeek V4 Pro
**Project:** Antariksh (Varaha Iron Butterfly autonomous options trading)

---

## Quick Summary

| Dimension | CrewAI | LangGraph | Winner for Antariksh |
|---|---|---|---|
| **Paradigm** | High-level role-based agents | Low-level state-graph orchestration | CrewAI |
| **Learning curve** | Low (natural language agent defs) | Steep (graph nodes, edges, state schemas) | CrewAI |
| **State management** | Implicit via shared `market_state` dict | Explicit typed `StateGraph` with persistence | LangGraph |
| **Durable execution** | None (cron-driven, stateless) | Built-in checkpoint/resume after failure | LangGraph |
| **Human-in-the-loop** | Manual (Telegram bridge shim) | Native `interrupt()` / `Command` | LangGraph |
| **Parallel agents** | Sequential task execution (hierarchical) | Native fan-out/parallel branches | LangGraph |
| **Risk Guard hard veto** | Works but hacky (shared dict) | Compile-time graph guardrails | LangGraph |
| **Current codebase** | Already implemented (`crew_structure.py`) | Not started | CrewAI |
| **Cost** | Per-agent LLM calls (even for deterministic tasks) | You control when LLM is called per node | LangGraph |

---

## Framework Overviews

### CrewAI

CrewAI is a high-level multi-agent framework with two core concepts:
- **Crews**: Teams of role-playing agents that collaborate on tasks. Agents have natural-language backstories and goals.
- **Flows**: Stateful, event-driven workflows that orchestrate crews. Added in recent versions for production use.

**Key features**: Hierarchical process mode (manager delegates tasks), allow_delegation, per-agent LLM assignment, task dependency chaining.

**Best for**: Systems where agents need to *reason conversationally* about their domain. Pre-market analysis, strategy generation, audit narrative.

### LangGraph

LangGraph is a low-level orchestration runtime by LangChain Inc. Focused entirely on agent orchestration — not prompts or architecture.

**Key features**: Durable execution (checkpoint/resume), native human-in-the-loop via `interrupt()`, parallel node execution, typed state schemas, compile-time graph validation.

**Best for**: Production systems needing resilience, parallelism, HITL gates, and cost control. Real-time monitoring loops, safety-critical veto paths.

---

## Deep Dive Per Dimension

### 1. State Management

**CrewAI** uses an implicit shared dict (`market_state`) that agents read/write via natural language task descriptions. No type safety, no persistence across restarts. Works for Phase 2 dry-run but fragile at scale.

**LangGraph** uses typed `TypedDict`/`Pydantic` state schemas with built-in checkpointing via `SqliteSaver` or `PostgresSaver`. State survives VPS reboots. The compiler validates that state keys exist before runtime.

### 2. Parallel Execution

**CrewAI** tasks execute sequentially in hierarchical mode. There is no way to run the Sentinel P&L loop concurrently with Risk Guard's hard-limit watchdog — they must take turns. This is the biggest gap for live trading.

**LangGraph** supports `Send()` API for fan-out to parallel nodes. The graph:
```
[Entry Gate] → [Executor + Sentinel + Risk Guard (parallel)] → [Audit]
```
…is a natural fit. Sentinel and Risk Guard can run concurrently, with Risk Guard's HALT instantly canceling the other branches.

### 3. Human-in-the-Loop

**CrewAI** has no native HITL. Antariksh shims it via Telegram bridge writing to `/tmp/antariksh_telegram.txt` with picoclaw relay. Manual, fragile, no timeout.

**LangGraph** has first-class `interrupt()` that pauses graph execution until a human sends a `Command(resume=...)`. This maps directly to the Two-Message Protocol: interrupt at gate check → wait for Telegram GO/SKIP → resume or abort. Timeout logic is built-in.

### 4. Risk Guard Veto Power

**CrewAI**: The CREW_SPEC states "Risk Guard's HALT is absolute… no agent can override." But this is a *convention*, not enforced by the framework. The Orchestrator's `allow_delegation=True` means it could theoretically delegate around Risk Guard. The guard exists in natural language task descriptions only.

**LangGraph**: Risk Guard is a conditional edge at the graph level:
```python
graph.add_conditional_edges("risk_guard", lambda state: END if state["halt"] else "executor")
```
No node can bypass this — it's compiled into the graph structure. This matches the constitutional requirement (L1 capital preservation) at the architectural level.

### 5. Deterministic Nodes & Token Cost

**CrewAI** requires every agent to have an LLM assigned. Even the Executor (which the design doc says should be "deterministic, NO LLM") currently loads `deepseek_llm` in `crew_structure.py:148`. Risk Guard also burns tokens on an LLM it doesn't need (hard checks are supposed to be deterministic).

**LangGraph** lets you define nodes as plain Python functions with no LLM. Only Scanner and Strategist call an LLM. The rest (Executor, Risk Guard, Sentinel) are pure Python. This reduces per-session token cost significantly.

### 6. Durability & Recovery

**CrewAI** is stateless. If the VPS reboots mid-session, the crew restarts from scratch. There's no concept of resuming from where it left off. EOD exit could be missed entirely.

**LangGraph** checkpoints after every node execution. A crash at 14:25 IST resumes from after the last successful node — preserving position state, P&L tracking, and ensuring EOD exit still fires.

### 7. Debugging & Observability

**CrewAI** offers verbose logging and `crewai.telemetry`. Tracing is basic — you see which agent was called and what it returned, but not the full execution graph.

**LangGraph** integrates with LangSmith for full execution tracing, state snapshots at each step, and visualization of the graph with node/edge highlighting. Commercial LangSmith deployment handles long-running agent state.

---

## When CrewAI Wins

- **Phase 2 is already built** — `crew_structure.py` has all 7 agents + 6 tasks wired. Switching now costs reimplementation time.
- **Conversational agents are the right pattern** for Scanner (market narrative), Strategist (trade reasoning), and Auditor (audit narrative). You want the Strategist to *think about* wing width, not just call a function.
- **Faster to prototype** — The daily session flow (scan → gate → plan → risk-check → execute → monitor → audit) maps directly to `Task` definitions with natural-language descriptions. New agents or tasks can be added in minutes.
- **Hierarchical process mode** provides a clean manager-worker pattern that matches the Antariksh org chart (CEO/Orchestrator manages subordinate agents).

## When LangGraph Wins

- **Sentinel + Risk Guard parallelism** is non-negotiable for live trading. A 2-second P&L monitoring loop cannot share a thread with hard-limit checks.
- **Durable execution** prevents session loss on VPS reboot — critical when real money is deployed.
- **Compile-time Risk Guard** enforces L1 capital preservation at the architecture level, not as a convention.
- **Zero-token deterministic nodes** reduce costs for Executor and Risk Guard by 100% (they never needed LLMs).
- **Native HITL gates** eliminate the picoclaw shim for the Two-Message Protocol.

---

## Recommendation

### Phase 2 (current): Stick with CrewAI
The sequential execution is fine for the 9:30 AM entry session where tasks are linear (scan → gate → plan → execute). Agent backstories help reason about market conditions conversationally. No need to rebuild what's working.

### Phase 3+: Migrate to LangGraph
When live trading with real money begins, the following become requirements that CrewAI cannot satisfy:

1. **Parallel Sentinel + Risk Guard** — graph with fan-out branches
2. **Durable execution** — checkpoint/resume on VPS failure
3. **Compile-time safety** — Risk Guard HALT as a graph guardrail, not a convention
4. **Cost control** — deterministic nodes for Executor and Risk Guard
5. **Native HITL** — `interrupt()` for Two-Message Protocol with timeout fallbacks

### Hybrid Option (Bridge Strategy)
Use LangGraph as the top-level orchestrator (state, scheduling, HITL, durability) that spawns a CrewAI crew for the morning reasoning tasks. This gets you LangGraph's resilience + CrewAI's conversational pre-market analysis.

```
LangGraph Graph:
  [Cron Trigger] → [CrewAI Morning Crew (scan + strategize)] → [HITL Gate] → [Sentinel ║ Risk Guard ║ Executor] → [Audit]
```

---

## File References

- Current CrewAI implementation: `crew_structure.py` (7 agents, 6 tasks, hierarchical crew)
- Crew spec & agent roster: `CREW_SPEC.md` (entry/exit session flow diagrams)
- Original design doc: `docs/Project_Varaha_CrewAI_Design.md` (3-crew daily operation, risk register, autonomy levels)
- Phase 1 architecture: `PHASE1_README.md`

---

*Research conducted via documentation review of crewai.com and docs.langchain.com. Antariksh project files analyzed from local codebase.*
