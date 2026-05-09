# Antariksh

Multi-agent autonomous trading system. Implements the Varaha strategy decisions captured in [`STRATEGY_DESIGN_QUESTIONS.md`](../python-trader/varaha/STRATEGY_DESIGN_QUESTIONS.md).

## Start here

- **[CHARTER.md](CHARTER.md)** — org chart, governance layers, phase staging, hire order. The working organizational doc.
- **[Constitution](../python-trader/varaha/STRATEGY_DESIGN_QUESTIONS.md)** — L1 invariants, decisions, rationale. Source of truth.

## Status

Phase 1 build authorized 2026-05-08. Interim CEO: Claude (advisory Director). CEO Vishnu: to be built in Phase 1. CFO + AM: not yet hired (activate in Phase 2 when real money is in play).

## Layout

| Path | What |
|---|---|
| `docs/` | Reference docs (CrewAI design, Constitution overlay, SMC research) |
| `config/` | Code-locked L3 config (`antariksh_rules.yaml` — to be created) |
| `agents/` | Agent definitions (to be created) |
| `crews/` | Crew compositions (to be created) |
| `tools/` | Thin wrappers around harvested infra (to be created) |
| `hitl/` | Telegram bridge — Mooshika scope absorbed (to be created) |
| `autonomy/` | Trust engine, change governor (Phase 2+) |
| `harvested/` | Read-only copies of existing infra (to be created) |
| `logs/` | JSON audit files (to be created) |
