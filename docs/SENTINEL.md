# SENTINEL — Rule-Based Validation (ATOM+)
# Created: 2026-07-24

Project:    SENTINEL
Role:       Deterministic rule-based validator for ATOM+ trading system
Owner:      algo_validator
Location:   /home/algo_validator/
Script:     sentinel.py
Cron:       */5 9-23 * * 1-5  (every 5 min, Mon-Fri market hours)

Log formats parsed:
  ATOM+ Paper (atom_paper_YYYYMMDD.log):
    Block-based — cycles delimited by "----- YYYY-MM-DD HH:MM:SS -----"
    Actions: OPEN_IRON_FLY, HOLD, EXIT, STAND_DOWN (reason)
    FSM states: FLAT → IRON_FLY → FLAT
    Config line: "MODULE 16 CONFIG: frozen v12:hash (APPROVED)"
  ATOM+ MCX (atom_mcx_YYYYMMDD.log):
    Block-based — same delimiter
    Actions as dicts: {'action': 'OPEN'|'EXIT'|'HOLD'|'STAND_DOWN'}
    FSM via 'fsm_state' key
    Tracks instrument, PnL, bar_ts, age_sec

Mode: Each run re-reads today's full log file (~100KB at EOD)
State: .sentinel_state.json tracks fired alert keys per day (dedup)

Market hours (IST, Mon-Fri):
  NIFTY/SENSEX: 9:15-15:30
  MCX:          9:00-23:30

Validation checks:
  🚨 OPEN while FSM≠FLAT       Double-entry bug / orphaned position
  🚨 Not FLAT at EOD            Position left open past market close
  🚨 >6 SL hits/day             Strategy drift / whipsaw
  🚨 Dev config running         "-dev" version in frozen config line
  🚨 Unapproved config          "APPROVED" keyword missing from config line
  ⚠️  12+ stale_feed in a row   Data feed outage during market hours
  ⚠️  Zero trades in market      Strategy silently inactive
  ℹ️  EOD summary                Daily per-strategy digest

Alert channel: Telegram (direct Bot API via urllib.request, stdlib only)
