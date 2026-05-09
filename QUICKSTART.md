# Antariksh Phase 1 MVS — Quick Start

## 30-Second Overview

**Antariksh** is an autonomous NIFTY options trading system. **Phase 1 MVS** is a minimal working version that:
- Checks a 3-layer gate every trading day (VIX, events, entry window)
- If gate passes → generates Iron Butterfly trade plan
- Sends two Telegram messages: 9:30 AM (entry decision) + 2:35 PM (exit report)
- Runs dry-run (real data, no broker execution)
- Logs everything for CFO audit

## Today — Get It Running

### 1. Manual Test (5 min)

```bash
cd /home/trading_ceo/antariksh
python3 phase1_mvs.py
```

Expected output: Gate decision + Telegram messages. (Will skip if outside entry window.)

### 2. Check Logs

```bash
# Session log
cat logs/phase1_20260508.log

# CFO audit (machine-readable)
cat logs/cfo_audit_20260508.jsonl | python3 -m json.tool
```

### 3. Set Up Cron (Production)

```bash
# Read setup guide
cat SETUP_CRON.md

# Edit crontab
crontab -e

# Add:
# 30 09 * * 1-5 /home/trading_ceo/antariksh/scheduler/run_phase1_9am.sh
# 35 14 * * 1-5 /home/trading_ceo/antariksh/scheduler/run_phase1_2pm.sh

# Verify
crontab -l
```

## Architecture

```
9:30 AM (Entry)
  ↓
Gate Check: VIX < 20? Event day? Entry window?
  ↓
PASS → Generate trade plan (Iron Butterfly: 4 legs, SL, TP)
SKIP → Log and move on
  ↓
Send Telegram (9:30 message)
  ↓
---
  ↓
2:35 PM (Exit)
  ↓
Backtest trade (if gate passed)
  ↓
Send Telegram (2:35 message with P&L)
  ↓
Log to CFO audit
```

## Key Files

| File | Purpose |
|------|---------|
| `phase1_mvs.py` | Main orchestrator (entry point) |
| `config/antariksh_rules.yaml` | L3 parameters (SL, VIX gate, etc.) — locked |
| `logs/phase1_YYYYMMDD.log` | Session logs (readable) |
| `logs/cfo_audit_YYYYMMDD.jsonl` | CFO audit trail (machine-readable) |
| `scheduler/run_phase1_9am.sh` | Cron wrapper (9:30 AM) |
| `scheduler/run_phase1_2pm.sh` | Cron wrapper (2:35 PM) |

## Governance (Read-Only)

**L1 (Immutable):** Don't burn capital. ₹1,000/day target. Duty: Chairman (you).

**L2 (Constitutional):** Mechanisms exist (gate, SL, DD cap, skip conditions).

**L3 (Operational):** Parameter values (₹3,500 SL, VIX<20, ±300 wings). Duty: CFO (governance) + CEO (operations).

**CFO in Phase 1:** Audits token usage + capital impact. Learns the L1 projection logic before Phase 2 (real money).

## What's Next

### This Week
- [ ] Test manual run during market hours (10:30–11:30 AM IST)
- [ ] Set up cron jobs
- [ ] Verify Telegram message delivery
- [ ] Monitor logs for errors

### Next Week
- [ ] Integrate real market data (VIX, NIFTY spot, events)
- [ ] Implement Layer 2–3 gate signals
- [ ] Run soak-test for 10–15 trading days
- [ ] If all operational: Phase 2 approval (real money)

## Documentation

| File | Content |
|------|---------|
| `PHASE1_README.md` | Full architecture, TODOs, design philosophy |
| `SETUP_CRON.md` | Cron job setup + troubleshooting |
| `CHARTER.md` | Org chart, governance, phase staging |
| `config/antariksh_rules.yaml` | L1/L2/L3 rules + LLM provisioning |

## Troubleshooting

**Gate always skips:**
- Check system time (should be 10:30–11:30 AM IST on weekdays)
- Check if event day logic is implemented (currently stubbed)

**No Telegram messages:**
- Telegram bridge is currently stubbed (logs to console)
- Will be connected to picoclaw in next iteration

**Cron not running:**
- See `SETUP_CRON.md` troubleshooting section
- Verify script is executable: `ls -la scheduler/run_phase1_*.sh`

## Questions?

Refer to:
- **Strategy details:** `../python-trader/varaha/STRATEGY_DESIGN_QUESTIONS.md`
- **Governance:** `CHARTER.md`
- **Configuration:** `config/antariksh_rules.yaml`
- **Phase 1 scope:** `PHASE1_README.md`

---

**Ready to run. Iterate fast.**
