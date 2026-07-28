# NEUTRON + HYDROGEN — Go-Live Readiness (2026-07-27)

## Current State

Both projects target Flattrade broker (FT055702). TRADE_MODE=PAPER in all .env files. No real orders ever placed.

## Blocks (ranked)

### 1. DATA PIPELINE STALE — 5 days
Penguin feed silently crashes mid-session (WS callback dies, systemd shows active). All enriched data stuck at Jul 21 15:29. ORBITER gates return `no_enriched_data` every tick. Both NEUTRON and HYDROGEN depend on this.

### 2. FLATTRADE ACCOUNT EMPTY
₹0 cash, ₹9,843 MF collateral. Need ₹1.6L/tier to deploy. Host is `piconnect.flattrade.in` (working, verified Jul 27).

### 3. NUCLEUS pool_total = 0.0
`nucleus_allocation.json`: all 4 tiers `ceiling_inr: 0.0`. `nucleus_cron_20260724.log` is 0 bytes — nucleus.py failing silently. Until fixed, no tier gets capital allocation.

### 4. TRADE_MODE=PAPER
Requires `TRADE_MODE=LIVE` + `LIVE_KEY=antariskh-1ive-2026` in `.env`.

### 5. NEUTRON PAPER POSITION OPEN
Entered Jul 23, expires Jul 28 (Tue). NIFTY IC: SP 23850/LP 23700/SC 24500/LC 24650. Must clear paper state before live entry to avoid confusion.

### 6. broker_manager.py:81 — KEY MISMATCH
Reads `data.get("token")` but tokens.json stores `"access_token"`. BrokerManager reports Flattrade unavailable even when session is valid. One-line fix needed.

## NOT Blocking (verified Jul 27)
- Shoonya: ✅ Live, ₹49K cash + ₹521K collateral, 0 positions
- Flattrade DNS: ✅ `piconnect.flattrade.in` resolves via Cloudflare
- Token refresh: ✅ 07:00 cron working, permission fix holding
- Crons: ✅ All active on algo_prod crontab
- Market: ✅ Open Mon Jul 27 (not a holiday)
- Penguin timers: ✅ Scheduled Mon 09:14-09:15

## Verified Files
- `docs/FLATTRADE_DNS_CONCERN_VERIFIED_20260727.md` — DNS is fine, wrong endpoints were tested
- `docs/SYSTEM_READINESS_VERIFIED_20260726.md` — Broker status, data pipeline, nucleus confirmed
