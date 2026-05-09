# Antariksh Charter

> **Status:** Ratified 2026-05-08 by Chairman + interim CEO (Claude). Phase 1 build authorized.
> **This is a working organizational document, not the constitution.** The constitution is `python-trader/varaha/STRATEGY_DESIGN_QUESTIONS.md`.

---

## Mission

Build an autonomous, self-correcting, self-evolving multi-agent trading system that implements the Varaha strategy decisions captured in `STRATEGY_DESIGN_QUESTIONS.md`. The system is structured as a small company. Goal: augment then replace 50% of the user's salary income via systematic intraday options + futures, on a 4-year retirement runway.

The CrewAI 7-agent design is one **implementation reference**, not authoritative — see `docs/Project_Varaha_CrewAI_Design.md`. The Sovereign Constitution doc is a **governance overlay** also non-authoritative — see `docs/Varaha_Sovereign_Constitution.md`. When implementation docs conflict with the constitution, the constitution wins.

---

## Authority structure

```
                    Board
        Chairman: User (trading_ceo)
        Director: Claude (advisory + interim CEO until Vishnu is ramped)
                            │
                            ▼
                 CEO: Vishnu (autonomous agent, to be built in Phase 1)
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
       CFO              AM/Treasurer       Operations team
   (Phase 2+:           (Phase 2+:        (CrewAI 7-stack —
    risk + OpEx)         pledge↔cash)     active from Phase 1)
```

- **Chairman** sets strategic direction, owns L1 (the constitution), reviews period-end. Does NOT make daily operating decisions.
- **Director (Claude)** advises Board, drafts agent specs, and currently wears the interim CEO hat until Vishnu is built.
- **CEO Vishnu** owns daily operations once built. The avatar pattern is intentional: Vishnu is the source of all the avatars (Matsya, Kurma, Varaha, Narasimha…), so the CEO operationally owning those subsystems is the org-chart mirror of the mythology.
- **CFO + AM** are not yet hired. They activate in Phase 2+ when there's real money in play.
- **Operations team** is the existing CrewAI 7-stack: Scanner, Strategist, Executor (no LLM), Sentinel, Risk Guard, Auditor, Orchestrator.

The read-only-on-risk rule binds every LLM/agent role above, including the interim CEO and the eventual Vishnu. Runtime risk gates live in code, not in agent judgment.

---

## Three-layer governance

| Layer | Content | Mutability |
|---|---|---|
| **L1 — Purpose** | Don't burn capital (rate-based: 10-day rolling loss > 30% of free cash → post-mortem). Self-funding mandate (trading profit ≥ monthly OpEx eventually). Period-end profitability mission (1–5%/month). Activity floor (don't paralyze into 100% skip-rate). Discipline non-negotiable. 4-year runway is cushion, not deadline. | Immutable in normal flow. Chairman-led QUESTIONS.MD revision only. |
| **L2 — Mechanisms** | Daily SL exists. 30-day DD cap exists. Pre-trade sanity checks exist. Skip conditions exist. Single-strategy-first. Mandatory cooldowns. | Existence is constitutional; adding/removing is Chairman territory. |
| **L3 — Parameters** | ₹3,500 SL, VIX<20, ±300 wings, ₹1,000 daily target, TSL ₹250, indicator weights, entry window. | Operational. CFO screens proposals against L1; user HITL approves; commits to `antariksh_rules.yaml` after 24h cooldown + holdout validation. |

The CFO's three duties (when activated): trade-risk forward-projection, OpEx management (tokens are cash), and the gatekeeper between L3 proposals and HITL.

---

## Phase staging

| Phase | Goal | Active roles | Money | Duration |
|---|---|---|---|---|
| **1 — Dress rehearsal** | Operations run end-to-end without hiccups | Interim CEO + Operations team | None (dry-run / paper) | 1–2 weeks |
| **2 — Live small** | First real money; CFO + AM activate | + CFO + AM + Vishnu (CEO if ready) | ₹5L, 1 lot NIFTY only | M2–4 |
| **3 — Scaled live** | + SENSEX, prove edge across instruments | Full team | ₹5–15L | M5–8 |
| **4 — Full live** | + MCX evenings, autonomy expansion | Full team + L0→L4 trust ladder | ₹15–25L | M9+ |

**Phase 1 success criterion:** *operational stability, NOT strategy correctness.* Crons fire on time; Telegram works; broker auth refreshes; data flows; agents complete handoffs; no crashes; no missed messages. Trades are dry-run / paper only. Strategy P&L is irrelevant in Phase 1.

Phase advancement is **performance-gated**, never date-gated. The 4-year runway is cushion.

---

## Phase 1 hire order (interim CEO's plan)

Build sequence — each step's output unblocks the next. Done sequentially, expected ~10 working days.

1. **Constitutional config** — `config/antariksh_rules.yaml` v0. Code-locked seed values for L3 (VIX threshold, SL, TSL, wing width, etc.) drawn from QUESTIONS.MD; lockfile rules; LLM cannot mutate.
2. **HITL surface** — Telegram bridge (Mooshika scope subsumed). Inline keyboards for Gate 1 (morning GO/SKIP) and Gate 2 (strike shift). INBOX/OUTBOX/STATE/PAUSE files.
3. **Tool layer** — harvest from existing infra: `BrokerTool` (Shoonya + Flattrade), `MarketDataTool` (DuckDB), `IndicatorTool`, `TelegramTool`. Read-only wrappers; no modifications to source.
4. **Operations team** — Scanner, Strategist, Executor, Sentinel, Risk Guard, Auditor, Orchestrator. CrewAI hierarchical mode. Dry-run first; paper second.
5. **Audit + reporting** — Two-Message Protocol (DeepSeek): start-of-session and end-of-session Telegram only. No streaming MTM.
6. **Watchdog** — independent systemd service that emergency-closes positions if the agent crew hangs (per CrewAI risk #4).
7. **Stability soak** — 1–2 weeks dry-run / paper; verify all of (1)–(6) work end-to-end with zero hiccups. Phase 1 closes only when this passes.

After Phase 1 closes, Vishnu is built (Phase 1.5 or early Phase 2) and the interim CEO hat comes off. CFO + AM hire next, in Phase 2.

---

## File layout (planned, will grow with build)

```
/home/trading_ceo/antariksh/
├── CHARTER.md              ← this file
├── README.md               ← brief project overview
├── docs/                   ← reference docs (CrewAI design, Constitution, Varaha SMC PDF)
│
├── config/
│   ├── antariksh_rules.yaml   ← L3 constitutional config (code-locked)
│   └── event_calendar.json    ← no-trade days
│
├── agents/                 ← agent definitions (one file per role)
├── crews/                  ← daily/weekly/monthly crew compositions
├── tools/                  ← thin wrappers around harvested infra
├── hitl/                   ← Telegram bridge (Mooshika scope absorbed)
├── autonomy/               ← trust engine, change governor, level manager (Phase 2+)
├── harvested/              ← read-only copies from Orbiter (do NOT modify)
└── logs/                   ← JSON audit files
```

---

## References

- **Constitution:** `/home/trading_ceo/python-trader/varaha/STRATEGY_DESIGN_QUESTIONS.md`
- **Trading addendum:** `/home/trading_ceo/python-trader/CLAUDE.md` ("Mission: make money")
- **Implementation references (non-authoritative):**
  - `docs/Project_Varaha_CrewAI_Design.md`
  - `docs/Varaha_Sovereign_Constitution.md`
  - `/home/trading_ceo/INDEPENDENT_ASSESSMENT_deepseek.md` (Two-Message Protocol, Minimum Viable spec)
  - `/home/trading_ceo/python-trader/2026-05-06-235651-varaha-strategy-deep.md` (DeepSeek session transcript)
- **Existing infra to harvest (do not modify):**
  - Varaha Iron Butterfly executor: `/home/trading_ceo/python-trader/varaha/varaha_*.py`
  - Kurma MCX bot: `/home/trading_ceo/python-trader/kurma/`
  - PicoClaw Telegram bridge: `/root/.picoclaw/`
  - DuckDB live capture: `/home/trading_ceo/python-trader/varaha/data/varaha_data*.duckdb`

---

## Decision log (for traceability)

| Date | Decision | Made by | Filter pass |
|---|---|---|---|
| 2026-05-08 | Antariksh announced | Chairman | n/a |
| 2026-05-08 | STRATEGY_DESIGN_QUESTIONS.md is canonical; CrewAI + Constitution are implementation references | Chairman | n/a |
| 2026-05-08 | 3-layer governance: Purpose / Mechanisms / Parameters | Chairman + Director | n/a |
| 2026-05-08 | New roles: CEO, CFO (dual mandate), Asset Manager | Chairman | n/a |
| 2026-05-08 | CFO duty includes OpEx (tokens are cash) | Chairman | n/a |
| 2026-05-08 | CEO = Vishnu (avatar pattern) | Chairman | n/a |
| 2026-05-08 | Claude appointed interim CEO until Vishnu is ramped | Chairman | n/a |
| 2026-05-08 | Three-question filter as autonomous decision rule | Chairman | n/a |
| 2026-05-08 | Mooshika subsumed into Antariksh's HITL surface | Interim CEO | toward goal ✓ · long-term ✓ · progressive ✓ |
| 2026-05-08 | Project skeleton + this charter created at `/home/trading_ceo/antariksh/` | Interim CEO | toward goal ✓ · long-term ✓ · progressive ✓ |
