# Project Varaha × CrewAI — Full Design Document

> Exported from Claude conversation · May 2026  
> Covers: multi-agent architecture, broker integration, autonomy progression, analyzer system, risk register

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack Decisions](#2-tech-stack-decisions)
3. [Existing Infrastructure to Harvest](#3-existing-infrastructure-to-harvest)
4. [System Architecture — Three Layers](#4-system-architecture--three-layers)
5. [Agent Roster](#5-agent-roster)
6. [Three Crews — Daily Operation](#6-three-crews--daily-operation)
7. [HITL Gate Design](#7-hitl-gate-design)
8. [Analyzer System — Three Timeframes](#8-analyzer-system--three-timeframes)
9. [Autonomy Progression — L0 to L4](#9-autonomy-progression--l0-to-l4)
10. [Trust Engine Implementation](#10-trust-engine-implementation)
11. [File Structure](#11-file-structure)
12. [DuckDB Schema](#12-duckdb-schema)
13. [Cron Schedule](#13-cron-schedule)
14. [Build Phases](#14-build-phases)
15. [Risk Register](#15-risk-register)
16. [Pre-Live Checklist](#16-pre-live-checklist)

---

## 1. Project Overview

**Project Varaha** is an automated Iron Butterfly options trading system for Nifty/Sensex weekly expiry, built on a Python algo engine with CrewAI providing the intelligence layer on top.

### Strategy
| Parameter | Value |
|---|---|
| Strategy | Short ATM Iron Butterfly |
| Instruments | Nifty (Mon/Tue/Fri) + Sensex (Wed/Thu) |
| Lots | 4 lots standard |
| Wing width | ±300 pts standard, ±350 on VIX > 15 |
| Entry time | 9:20 AM standard, 9:30 AM if gap > 0.5% |
| Daily target | ₹1,500 net |
| Max daily loss | −₹2,200 |
| TSL step | ₹250 step-based |
| Capital | ₹6,00,000 |

### Capital deployed
- **Primary broker**: Shoonya (Finvasia) — NorenAPI
- **Failover broker**: Flattrade — free API
- **Infrastructure**: Hostinger VPS
- **LLM**: Claude Pro (primary) + DeepSeek (cost-efficient tasks) + MiniMax

---

## 2. Tech Stack Decisions

### Communication: Telegram (chosen over Discord)

**Why Telegram won:**
- Bot API is simple HTTP POST — no Gateway WebSocket complexity
- Inline keyboard buttons are perfect for approve/reject HITL flows
- 30 msg/s rate limit (vs Discord's 5 msg/s)
- India trading community already heavily uses Telegram
- `python-telegram-bot` v20 is async-native

**Discord trade-off**: Better for multi-user team setups with structured channels. Rich embeds look more polished. Rate limits are stricter. Use Discord if building for a team, not personal use.

### LLM Cost Strategy

| Agent | LLM | Reason |
|---|---|---|
| Orchestrator | Claude Sonnet | Critical decisions |
| Scanner | DeepSeek | Pattern matching, cost-efficient |
| Strategist | Claude Sonnet | Options reasoning |
| Sentinel | Claude Sonnet | Real-time position logic |
| Risk Guard | Claude Sonnet | Safety-critical |
| Auditor | DeepSeek | Bulk data analysis |

**Fallback**: If DeepSeek API is unavailable → Claude Haiku (~80% cost reduction vs Sonnet).

---

## 3. Existing Infrastructure to Harvest

### What exists today
```
Data Capture ──→ 1-min candles, indicators, ATM prices (DuckDB, live during market hours)
Orbiter      ──→ Shoonya + Flattrade broker code (working in test files)
Orbiter      ──→ Weighted indicator system (RSI, VWAP, VIX, EMA, Bollinger, ATR, OI, PCR, Max Pain)
PicoClaw     ──→ Miniature OpenClaw — HITL via Telegram (working today)
Linux Cron   ──→ Scheduler for deterministic trading runs
```

### What to harvest from Orbiter
1. `shoonya_client.py` + `flattrade_client.py` → copy to `varaha/harvested/`, wrap as `BrokerTool`
2. Weighted indicator scoring function → `varaha/harvested/indicators.py`, wrap as `IndicatorTool`
3. **Do not modify** harvested files — treat as read-only dependencies

### DuckDB data already captured (1-min candles during market hours)
- Index spot values (Nifty, Sensex)
- ATM option prices
- Indicators: RSI, VWAP, India VIX, EMA(20), Bollinger Bands, ATR, OI data, PCR, Max Pain

**Key insight**: CrewAI agents are purely additive. They sit on top of existing infrastructure. No rebuilding of broker code, data pipeline, or Telegram connectivity.

---

## 4. System Architecture — Three Layers

```
┌─────────────────────────────────────────────────────┐
│                   Hostinger VPS                      │
│                                                      │
│  ┌─ Interface Layer ──────────────────────────────┐  │
│  │  PicoClaw (extend with inline keyboards)       │  │
│  │  Telegram HITL · You (the human)               │  │
│  └────────────────────────────────────────────────┘  │
│                          ↕                           │
│  ┌─ CrewAI Intelligence Layer ───────────────────┐   │
│  │  Orchestrator · Scanner · Strategist          │   │
│  │  Executor · Sentinel · Risk Guard · Auditor   │   │
│  └────────────────────────────────────────────────┘  │
│                          ↕                           │
│  ┌─ Tool Layer (harvested from Orbiter) ─────────┐   │
│  │  MarketDataTool · BrokerTool                  │   │
│  │  IndicatorTool · TelegramTool · AuditTool     │   │
│  └────────────────────────────────────────────────┘  │
│                          ↕                           │
│  ┌─ Infrastructure (existing, untouched) ────────┐   │
│  │  DuckDB (1-min candles + indicators + ATM)    │   │
│  │  Shoonya NorenAPI (primary)                   │   │
│  │  Flattrade API (failover)                     │   │
│  │  Linux Cron · run_varaha.sh · Holiday shield  │   │
│  └────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

## 5. Agent Roster

| # | Agent | LLM | Crew | Role |
|---|---|---|---|---|
| 1 | **Orchestrator** | Claude Sonnet | Morning | Master coordinator, hierarchical manager |
| 2 | **Scanner** | DeepSeek | Morning | Pre-market VIX + gap + event analysis |
| 3 | **Strategist** | Claude Sonnet | Morning | Strike selection, wing width, lot sizing |
| 4 | **Executor** | None (deterministic) | Trading | Order sequencing — no LLM in critical path |
| 5 | **Sentinel** | Claude Sonnet | Trading | TSL step management, shift trigger, exits |
| 6 | **Risk Guard** | Claude Sonnet | Trading | Broker failover, kill switch, always-on watchdog |
| 7 | **Auditor** | DeepSeek | Evening | P&L analysis, trade scoring, Drive sync |

**Important**: Executor is deliberately LLM-free. Order execution is deterministic — buy wings first, 1.5s delay, sell ATM. An LLM adding latency during execution is a liability.

---

## 6. Three Crews — Daily Operation

### Daily Flow

```
Cron 8:55 AM
    ↓
Morning Crew (Scanner → Strategist → Orchestrator)
    ↓
HITL Gate 1 — Telegram: GO / SKIP / Modify
    ↓
Trading Crew (Executor → Sentinel + Risk Guard in parallel)
    ↓
HITL Gate 2 — Strike shift approval (30s timeout)
    ↓
Evening Crew (Auditor → Drive sync) at 3:35 PM
```

### Morning Crew (`varaha/crews/morning_crew.py`)
**Trigger**: Cron 8:55 AM  
**Output**: `trade_config.json` written to `/tmp/varaha/`

Tasks:
1. Scanner queries DuckDB: VIX, overnight gap %, event calendar, PCR
2. Strategist selects: instrument (Nifty/Sensex by day), ATM strike, wing width, lots, entry time
3. Orchestrator synthesises → final `trade_config.json`

### Trading Crew (`varaha/crews/trading_crew.py`)
**Trigger**: Cron 9:18 AM (only if Gate 1 = GO)  

- **Executor**: Deterministic hedge-first order sequencing
- **Sentinel**: Monitoring loop every 2s — TSL steps, shift trigger, target/SL/EOD exits
- **Risk Guard**: Independent parallel watchdog — broker failover, API monitoring

**Hard rule**: Zero LLM calls after 3:25 PM. Final 5 minutes are pure deterministic Python.

### Evening Crew (`varaha/crews/evening_crew.py`)
**Trigger**: Cron 3:35 PM

- Reads `varaha_audit.json` (day's trades and events)
- Calculates net P&L, trade quality score (0-10), anomaly detection
- Syncs `daily_summary_{date}.json` to Google Drive `Varaha/Logs/`
- Sends Telegram daily summary

---

## 7. HITL Gate Design

### Gate 1 — Morning Go/No-Go (8:55–9:18 AM)

```
Varaha Morning Brief

Instrument: NIFTY
VIX: 13.4 | Gap: 0.2%
Strategy: Iron Fly @ 24000 ± 300
Lots: 4 | Entry: 09:20
Scout says: *GO*

[GO]  [SKIP today]  [Modify]
```

No trade fires unless you tap GO. Cron at 9:18 checks `gate1_decision.txt` for "GO" before starting Trading Crew.

### Gate 2 — Strike Shift Approval (during session)

```
Strike Shift Recommended

Spot moved 0.6% from entry
Current: 24000 → Proposed: 24050
Est. extra premium: ₹840

Auto-approving in 30s if no response.

[Approve]  [Reject]
```

**Critical safety rule**: If VIX spiked >15% in last 5 min OR spot moved >0.7% in last 3 candles → timeout defaults to **REJECT** (not approve). High volatility = fail safe.

---

## 8. Analyzer System — Three Timeframes

### Analyzer Pyramid

```
Monthly Strategist (month-end Friday 4:30 PM)
    ↑ reads 4 weekly reviews
Weekly Reviewer (every Friday 3:45 PM)
    ↑ reads 5 EOD post-mortems
EOD Post-Mortem (daily 3:35 PM)
    ↑ reads DuckDB + audit logs
```

### EOD Post-Mortem (`varaha/crews/evening_crew.py`)

**5 agents**: Trade Reviewer · Opportunity Hunter · Pattern Analyst · Logic Synthesizer · Report Writer

**Output per session**:
- Trade quality score (0-10) with entry/exit/TSL breakdown
- Missed opportunities (type, ₹ estimate, confidence %)
- Max 3 proposed config changes with evidence + backtest impact
- All proposals written to `varaha_params_history` with `status='PENDING_APPROVAL'`
- Telegram summary sent with inline keyboard: `[Approve all]` `[Review one by one]` `[Reject all]`

### Weekly Trade Analyzer (`varaha/crews/weekly_crew.py`)

**Trigger**: Every Friday 3:45 PM  
**4 agents**: Week Summarizer · Indicator Auditor · Regime Analyst · Weekly Tactician

**Output**:
- Week grade (A–F) and quality score
- Indicator effectiveness per indicator (0-10 per indicator, verdict: increase/keep/decrease/remove weight)
- Strategy regime fit (excellent/good/moderate/poor) + alternative if poor
- Tactical changes for next week (high/medium/low priority)
- Suggested new indicators (with complexity + expected edge)

**Safeguard**: Indicator weight changes allowed max once per month (not weekly). Changes validated against 30-session holdout before applying.

### Monthly Strategy Analyzer (`varaha/crews/monthly_crew.py`)

**Trigger**: Last Friday of month, 4:30 PM  
**4 agents**: Performance Analyst · Opportunity Scout (with web search) · Risk Evaluator · Monthly Strategist

**Output**:
- Monthly grade + ROI assessment vs capital benchmark
- Iron Butterfly refinements (specific before/after param changes)
- Indicator suite audit (drop/keep/add with data sources)
- New revenue opportunities assessed:
  - MCX Gold/Silver mini (evening session)
  - Individual stock F&O (top liquid NSE stocks)
  - Currency derivatives (USDINR)
  - Crypto derivatives (legally accessible from India)
- Next month 4-week playbook
- Revised monthly target if warranted

**Opportunity Scout uses web search** to research current market conditions, strategy popularity, and new instrument viability before generating recommendations.

---

## 9. Autonomy Progression — L0 to L4

### Overview

| Level | Name | Duration | Core unlock |
|---|---|---|---|
| L0 | Manual | Weeks 1–2 | 10 paper sessions, zero API errors |
| L1 | Partial | Weeks 3–4 | entry_decision trust > 0.65 |
| L2 | Semi | Month 2 | exit_decision trust > 0.75 |
| L3 | Supervised | Month 3–4 | All core trust scores > 0.80 |
| L4 | Autonomous | Month 6+ | All trust scores > 0.85, 3 months consistent |

### Capability matrix

| Capability | L0 | L1 | L2 | L3 | L4 |
|---|---|---|---|---|---|
| Pre-market scan | You | Bot | Bot | Bot | Bot |
| Entry decision | You | Gate 1 | Auto | Auto | Auto |
| Exit (target/SL) | You | You | Auto | Auto | Auto |
| Strike shift | You | Gate 2 | Gate 30s | Auto | Auto |
| EOD low-risk params | You | You | Gate | Auto | Auto |
| EOD high-risk params | You | You | Gate | Gate | Auto |
| Weekly indicator weights | You | You | Gate | Auto | Auto |
| Lot scaling | Fixed | Fixed | Fixed | Gate | Auto |
| New revenue ops | You | You | Read | Gate | Paper |

**Key principle**: You never get pushed to the next level automatically. The system earns it and notifies you. You tap to unlock. You can stay at any level indefinitely.

**Level-up notification example**:
```
Varaha is ready for L2

Trust scores across 10 sessions:
Entry: 71%  |  Exit: 78%  |  Strike shift: 64%

Ready to unlock: Semi-Autonomous
New capability: Autonomous exits (target/SL/EOD)

[Unlock L2]  [Stay at L1]
```

---

## 10. Trust Engine Implementation

### Core logic (`varaha/autonomy/trust_engine.py`)

```python
class VarahaTrustEngine:
    
    # Trust is bucketed by VIX regime — calm market trust ≠ volatile market trust
    VIX_BUCKETS = [(0, 14), (14, 18), (18, 25), (25, 999)]
    
    THRESHOLDS = {
        "entry_decision":    {"l2": 0.65, "l3": 0.80, "l4": 0.85},
        "exit_decision":     {"l2": 0.75, "l3": 0.85, "l4": 0.90},
        "strike_shift":      {"l2": 0.60, "l3": 0.80, "l4": 0.85},
        "param_low_risk":    {"l2": 0.60, "l3": 0.75, "l4": 0.85},
        "param_high_risk":   {"l4": 0.90},
        "lot_scaling":       {"l3": 0.80, "l4": 0.90},
    }
    
    def record_outcome(self, capability, was_correct, current_vix):
        bucket = self.get_vix_bucket(current_vix)
        key = f"{capability}_b{bucket}"
        # Exponential moving average — recent sessions weighted 70%
        s = self.scores[key]
        s["sessions"] += 1
        if s["sessions"] >= 5:
            s["score"] = s["score"] * 0.7 + (0.3 if was_correct else 0.0)
        else:
            s["correct"] += (1 if was_correct else 0)
            s["score"] = s["correct"] / s["sessions"]
        self._save()
    
    def can_auto(self, capability, target_level, current_vix):
        bucket = self.get_vix_bucket(current_vix)
        key = f"{capability}_b{bucket}"
        score = self.scores.get(key, {}).get("score", 0.0)
        sessions = self.scores.get(key, {}).get("sessions", 0)
        if sessions < 5:           # minimum 5 sessions in this VIX bucket
            return False
        threshold = self.THRESHOLDS.get(capability, {}).get(f"l{target_level}", 1.0)
        return score >= threshold
```

### Parameter change governor (`varaha/autonomy/change_governor.py`)

```python
class ChangeGovernor:
    MAX_CHANGES_PER_WEEK = 1
    HIGH_RISK_PARAMS = ["daily_sl_amount", "max_lots", "tsl_step_size"]
    
    def can_apply_change(self, proposed_change):
        if self.count_changes_this_week() >= self.MAX_CHANGES_PER_WEEK:
            return False, "Weekly budget exhausted"
        holdout_result = self.backtest_on_holdout(proposed_change)
        if holdout_result < -500:
            return False, f"Holdout failed: ₹{holdout_result}"
        if proposed_change["param"] in self.HIGH_RISK_PARAMS:
            return False, "High-risk param — human approval required"
        return True, "Approved"
```

---

## 11. File Structure

```
varaha/
├── crews/
│   ├── morning_crew.py
│   ├── trading_crew.py
│   ├── evening_crew.py
│   ├── weekly_crew.py
│   └── monthly_crew.py
├── agents/
│   ├── orchestrator.py
│   ├── scanner.py
│   ├── strategist.py
│   ├── executor.py          # deterministic, NO LLM
│   ├── sentinel.py
│   ├── risk_guard.py
│   └── auditor.py
├── tools/
│   ├── market_data_tool.py  # DuckDB SQL queries
│   ├── broker_tool.py       # Shoonya + Flattrade + SEBI algo tag
│   ├── indicator_tool.py    # Orbiter weighted system wrapper
│   ├── telegram_tool.py     # PicoClaw extension (inline keyboards)
│   ├── event_calendar_tool.py
│   └── audit_tool.py        # JSON log writer + Drive sync
├── hitl/
│   ├── gate1.py             # Morning go/no-go
│   ├── gate2.py             # Strike shift (context-aware timeout)
│   └── telegram_bot.py      # Main bot handler
├── autonomy/
│   ├── trust_engine.py      # VIX-bucketed trust scores
│   ├── level_manager.py     # Level-up notifications
│   └── change_governor.py   # Parameter change safety
├── harvested/               # Orbiter code — do NOT modify
│   ├── shoonya_client.py
│   ├── flattrade_client.py
│   └── indicators.py
├── sentinel_watchdog.py     # Systemd service — independent of CrewAI
├── config/
│   ├── varaha_config.yaml   # Active config (versioned)
│   ├── varaha_config_v0.yaml # Frozen original — never modify
│   └── event_calendar.json
├── logs/                    # JSON audit files
├── varaha_main.py
└── run_varaha.sh
```

---

## 12. DuckDB Schema

```sql
-- Existing tables (from data capture — do not modify)
-- market_data: 1-min candles with all indicators
-- (your existing schema here)

-- New Varaha tables
CREATE TABLE varaha_trades (
    trade_date      DATE,
    instrument      VARCHAR,
    atm_strike      INTEGER,
    wing_width      INTEGER,
    lots            INTEGER,
    entry_time      TIMESTAMP,
    exit_time       TIMESTAMP,
    exit_reason     VARCHAR,    -- TARGET / SL / EOD / MANUAL
    gross_pnl       DECIMAL,
    brokerage       DECIMAL,
    net_pnl         DECIMAL,
    adjustments     INTEGER,
    trade_score     DECIMAL     -- auditor quality score 0-10
);

CREATE TABLE varaha_sentinel_log (
    ts              TIMESTAMP,
    event_type      VARCHAR,    -- TSL_MOVE / SHIFT_TRIGGER / TARGET / SL / EOD
    net_pnl         DECIMAL,
    current_sl      DECIMAL,
    spot            DECIMAL,
    details         JSON
);

CREATE TABLE varaha_params_history (
    changed_at      TIMESTAMP,
    param_name      VARCHAR,
    old_value       VARCHAR,
    new_value       VARCHAR,
    changed_by      VARCHAR,    -- AGENT_SUGGESTION / USER_OVERRIDE
    approved_by     VARCHAR,
    status          VARCHAR,    -- PENDING_APPROVAL / APPROVED / REJECTED / APPLIED / ROLLED_BACK
    applied_at      TIMESTAMP,
    backtest_pnl    DECIMAL
);

CREATE TABLE varaha_postmortem (
    session_date      DATE PRIMARY KEY,
    overall_grade     VARCHAR(1),
    trade_score       DECIMAL,
    missed_opp_count  INTEGER,
    missed_opp_value  DECIMAL,
    proposals_count   INTEGER,
    report_path       VARCHAR,
    drive_synced      BOOLEAN
);

CREATE TABLE varaha_trust_snapshots (
    snapshot_ts     TIMESTAMP,
    capability      VARCHAR,
    vix_bucket      INTEGER,
    score           DECIMAL,
    sessions        INTEGER,
    current_level   INTEGER
);
```

---

## 13. Cron Schedule

```bash
# /etc/cron.d/varaha

# Morning crew — pre-market scan
55 8 * * 1-5   varaha /home/varaha/run_varaha.sh --crew morning

# Trading crew — entry + sentinel
18 9 * * 1-5   varaha /home/varaha/run_varaha.sh --crew trading

# Evening crew — audit + Drive sync
35 15 * * 1-5  varaha /home/varaha/run_varaha.sh --crew evening

# Weekly review — every Friday after close
45 15 * * 5    varaha /home/varaha/run_varaha.sh --crew weekly

# Monthly review — last Friday of month
30 16 * * 5    varaha /home/varaha/run_varaha.sh --crew monthly_if_last_friday
```

**Safety check in `run_varaha.sh`**: Trading crew validates morning crew output is fresh (< 45 minutes old) before proceeding. Stale or missing config → abort + Telegram alert.

---

## 14. Build Phases

### Phase 1 — Core Engine (Weeks 1–2)
**Goal**: Varaha executes an Iron Butterfly autonomously. L0 operation. No intelligence yet.

- [ ] Register algo with Shoonya + Flattrade compliance (SEBI requirement)
- [ ] Harvest `shoonya_client.py` + `flattrade_client.py` → `BrokerTool` with SEBI algo tag
- [ ] Build `MarketDataTool` (DuckDB queries for spot, ATM price, VIX)
- [ ] Build `Executor` agent (deterministic, wraps BrokerTool)
- [ ] Build `Sentinel` agent (TSL loop + shift trigger)
- [ ] Build `Risk Guard` (broker failover + kill switch)
- [ ] Build `sentinel_watchdog.py` as systemd service
- [ ] Extend PicoClaw Telegram → inline keyboard for Gate 2
- [ ] Monthly loss circuit breaker in config
- [ ] DuckDB WAL mode + daily backup
- [ ] Paper trade 10 sessions at 1 lot

### Phase 2 — Intelligence Layer (Weeks 3–4)
**Goal**: Agents make pre-market decisions. You only approve, don't configure.

- [ ] Build `Scanner` agent + `EventCalendarTool`
- [ ] Build `Strategist` agent + `IndicatorTool` from Orbiter
- [ ] Build `Orchestrator` (hierarchical process mode)
- [ ] Build Gate 1 (morning Telegram briefing + GO/SKIP)
- [ ] Build `Auditor` agent + Google Drive sync
- [ ] Gate 2 context-aware timeout (fail safe on high volatility)
- [ ] Trust engine with VIX bucketing
- [ ] Live 1-lot pilot

### Phase 3 — Analyzer Stack (Month 2)
**Goal**: Self-improvement loop running. Analyzers propose changes, you approve.

- [ ] Build EOD Post-Mortem crew (5 agents)
- [ ] Build Weekly Reviewer crew
- [ ] Build Monthly Strategy crew (with web search)
- [ ] v0 baseline config frozen in git
- [ ] Virtual paper portfolio on v0 running in parallel
- [ ] Parameter change governor (max 1/week, holdout validation)
- [ ] /rollback command implemented

### Phase 4 — Autonomy Expansion (Month 3+)
**Goal**: Earn L2/L3 based on proven trust scores in each capability.

- [ ] VIX-bucketed trust scores accumulating
- [ ] Level-up notifications via Telegram
- [ ] Scale to full 4 lots after 10 consistent sessions
- [ ] Graduated autonomy per the capability matrix

---

## 15. Risk Register

### Critical Risks (act before going live)

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | **SEBI Algo Registration** | Account suspension + legal | Register with broker compliance before any live trading. Tag every order with SEBI algo ID. |
| 2 | **LLM Latency at Close** | Position held overnight | Zero LLM calls after 3:25 PM. Pure Python deterministic exit in final 5 minutes. |
| 3 | **Trust Score Regime Blindness** | L3 autonomy in unseen conditions | VIX-bucket trust scores. Trust earned in VIX 12–14 doesn't apply at VIX 22. Auto-demote on regime shift. |
| 4 | **Sentinel Crash = Unmonitored Position** | Full wing loss, no SL | Independent watchdog (systemd service). Heartbeat timeout → emergency close all positions immediately. |
| 5 | **Analyzer Parameter Drift** | Strategy unrecognizable after months | Max 1 change/week. v0 baseline in git. Monthly live vs v0 comparison. /rollback command. |

### High Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 6 | **No Monthly Loss Circuit Breaker** | ₹44,000 potential monthly loss | Hard monthly limit in config (default −₹15,000). Bot goes paper-only. Manual /resume required. |
| 7 | **Brokerage + Tax Understated** | Target unachievable | Measure actual brokerage over 10 paper sessions. STT + stamp duty + SEBI charges can total ₹600–800/session. |
| 8 | **30s Auto-Approve During Black Swan** | Position rolled into moving market | Gate 2 timeout = REJECT (not approve) if VIX spiked >15% or spot moved >0.7% in last 3 candles. |
| 9 | **Multi-Agent Disagreement** | Undefined behavior | Scanner veto is absolute. Scanner NO-GO with confidence > 0.65 overrides all other agents. Hardcoded, not LLM-decided. |
| 10 | **DuckDB File Corruption** | All historical data + trust scores lost | WAL mode. Daily /backup/ + weekly Drive sync. Auditor runs `PRAGMA integrity_check` daily. Trust scores also in separate JSON. |
| 11 | **Margin Spike on High VIX** | Broker rejects entry | Morning crew checks available margin vs required + 20% buffer. Reduce lots or skip if insufficient. |

### Moderate Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 12 | **DeepSeek Geo-Political Risk** | Scanner + Auditor unavailable | Auto-fallback to Claude Haiku if DeepSeek API errors > 3 in 10 minutes. |
| 13 | **Cron Missed on VPS Restart** | Trading with stale config | Trading crew validates morning config freshness (< 45 min). Abort if stale. @reboot cron check. |
| 14 | **Indicator System Overfitting** | Weights tuned to past, fail in next regime | Indicator weights change max once per month. 30-session holdout validation before applying. |
| 15 | **No Baseline Strategy Lock** | Can't measure if self-improvement is working | v0 config frozen. Virtual parallel portfolio. Monthly live vs v0 comparison. |
| 16 | **LLM Token Cost Overrun** | Running cost erodes profit | Token budget per agent. Haiku for Scanner/Auditor. Monthly cost alert at ₹2,000 equivalent. |

---

## 16. Pre-Live Checklist

### Week 0 — Before any code
- [ ] SEBI algo registration with Shoonya compliance desk
- [ ] Confirm Flattrade API terms for automated order generation
- [ ] Calculate real brokerage on a test order (includes STT, stamp duty, exchange fees)
- [ ] Validate ₹1,500 net/day target is achievable after actual brokerage

### Week 1 — Before paper trading
- [ ] Sentinel watchdog as systemd service (independent of Python/CrewAI)
- [ ] Monthly loss circuit breaker: `monthly_loss_limit: -15000` in varaha_config.yaml
- [ ] DuckDB WAL mode enabled + daily backup cron
- [ ] Hard 3:25 PM LLM cutoff rule implemented and tested
- [ ] Emergency /stop Telegram command working

### Week 2 — Before live trading
- [ ] VIX-bucketed trust scores accumulating during paper phase
- [ ] Scanner veto hardcoded (not LLM-delegated)
- [ ] Gate 2 context-aware timeout (fail-safe on high volatility)
- [ ] v0 baseline config frozen in git, never touched again
- [ ] /rollback command tested and working
- [ ] 10 clean paper sessions logged in DuckDB with zero API errors

---

## Appendix: Telegram Commands

| Command | Action | Available at level |
|---|---|---|
| `/start` | Initialize bot, run morning crew if market day | All |
| `/stop` | Emergency close all positions immediately | All |
| `/status` | Current position, P&L, Sentinel status | All |
| `/override` | Manually trigger entry/exit | All |
| `/rollback [version]` | Revert config to specified version | All |
| `/resume` | Resume live trading after monthly loss limit hit | All |
| `/trust` | Show current trust scores per capability | All |
| `/level` | Show current autonomy level + unlock progress | All |
| `/report` | Trigger on-demand EOD post-mortem | All |

---

*Document generated from Claude conversation · Project Varaha × CrewAI Design Session · May 2026*  
*Last updated: see Google Drive modification timestamp*
