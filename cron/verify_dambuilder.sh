#!/bin/bash
# DAMBUILDER live verification — cron-driven checks for 2026-06-12
# Matches V1-V9 from DAMBUILDER_STATE.md §live-verification
# Each step logs to ~/antariksh/logs/verify_20260612.log

LOG="/home/trading_ceo/antariksh/logs/verify_20260612.log"  # absolute: at-jobs run as root ($HOME=/root)
mkdir -p "$(dirname "$LOG")"

vcheck() {
    echo "=== $1 ===" >> "$LOG" 2>&1
    echo "--- $(date) ---" >> "$LOG" 2>&1
    shift
    "$@" >> "$LOG" 2>&1
    echo "" >> "$LOG" 2>&1
}

case "$1" in
  V1) # 09:15 — feed alive, ticks flowing
    vcheck "V1" systemctl is-active feed.service
    vcheck "V1-bars" bash -c 'wc -l /home/trading_ceo/antariksh/data/live/NIFTY_1min.log'
    ;;

  V2) # 09:30 — market_data + enriched growing
    vcheck "V2" python3 -c "
import sqlite3
for inst in ('nifty','sensex'):
    db=f'/home/trading_ceo/python-trader/varaha/data/capture_{inst}.sqlite'
    c=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    md=c.execute(\"select count(*) from market_data where substr(timestamp,1,10)=date('now')\").fetchone()[0]
    en=c.execute(\"select count(*) from market_data_enriched where substr(timestamp,1,10)=date('now')\").fetchone()[0]
    print(f'{inst}: market_data={md} enriched={en}')
    c.close()"
    ;;

  V3) # 10:00 — UNICORN researcher works without Redis (import-only check)
    vcheck "V3" python3 -c "
import sys,os
sys.path.insert(0,'/home/trading_ceo/antariksh')
sys.path.insert(0,'/home/trading_ceo/brahmand')
os.environ['MULTITF_SOURCE']='sqlite'
from unicorn_raw_query import UnicornRawQuery
rq = UnicornRawQuery()
result = rq.run('NIFTY')
print(f'Raw query sections: {list(result.keys()) if isinstance(result,dict) else \"string ok\"}')"
    # §8 V3 proper: entry scoring live on new grid — T7/T8/T8b production surface
    vcheck "V3-score_trend" python3 -c "
import sys
sys.path.insert(0,'/home/trading_ceo/antariksh')
from tools.entry_tools import score_trend
s = score_trend('NIFTY')
print({k: s.get(k) for k in ('signal','score','confidence')})
print('reasoning:', s.get('reasoning','')[:160])"
    ;;

  V4) # 10:15 — decision_trace rows from first kickoffs
    vcheck "V4" python3 -c "
import sqlite3
c=sqlite3.connect('file:/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite?mode=ro',uri=True)
rows=c.execute(\"select * from decision_trace where substr(timestamp,1,10)=date('now')\").fetchall()
print(f'decision_trace rows today: {len(rows)}')
if rows: [print(f'  {r[0][11:19]} gate={r[3]} signal={r[5]} go={r[6]} conf={r[7]}') for r in rows[:5]]
c.close()"
    ;;

  V5) # 11:00 — data_health silent while healthy
    vcheck "V5" python3 /home/trading_ceo/brahmand/data_health.py
    ;;

  V6) # 12:00 — option chain + atm_strike populated
    vcheck "V6" python3 -c "
import sqlite3
c=sqlite3.connect('file:/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite?mode=ro',uri=True)
row=c.execute(\"select max(timestamp), india_vix, atm_strike from market_data_enriched where substr(timestamp,1,10)=date('now')\").fetchone()
print(f'enriched: ts={str(row[0])[11:19] if row[0] else None} vix={row[1]} atm={row[2]}')
opts=c.execute(\"select count(*) from option_prices where substr(timestamp,1,10)=date('now')\").fetchone()[0]
print(f'option_prices rows: {opts}')
c.close()"
    ;;

  V7) # 15:35 — clean close, 368-375 bars
    vcheck "V7" python3 -c "
import sqlite3
c=sqlite3.connect('file:/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite?mode=ro',uri=True)
cnt,last=c.execute(\"select count(*),max(timestamp) from market_data where substr(timestamp,1,10)=date('now')\").fetchone()
print(f'market_data: {cnt} bars, last={last}')
c.close()"
    vcheck "V7-status" systemctl is-active feed.service
    ;;

  V8) # 16:10 — unattended cron backfill
    python3 /home/trading_ceo/antariksh/enrichers/eod_backfill.py --both --date "$(date +%Y-%m-%d)"
    vcheck "V8-counts" python3 -c "
import sqlite3
for i in ('nifty','sensex'):
    c=sqlite3.connect(f'file:/home/trading_ceo/python-trader/varaha/data/capture_{i}.sqlite?mode=ro',uri=True)
    rows=[(r[0],r[1]) for r in c.execute(\"select timeframe_min,count(*) from market_data_multitf where substr(timestamp,1,10)=date('now') group by timeframe_min\")]
    print(f'{i}: {rows}')
    c.close()"
    ;;

  V9) # EOD — trade_outcomes check
    vcheck "V9" python3 -c "
import sqlite3
c=sqlite3.connect('file:/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite?mode=ro',uri=True)
rows=c.execute(\"select * from trade_outcomes where substr(entry_time,1,10)=date('now')\").fetchall()
print(f'trade_outcomes today: {len(rows)}')
[print(f'  id={r[0]} exit={r[2]} pnl={r[5]} reason={r[8]}') for r in rows]
c.close()"
    ;;

  *)
    echo "Usage: $0 {V1|V2|V3|V4|V5|V6|V7|V8|V9}"
    echo "  V1 09:15 feed alive"
    echo "  V2 09:30 market_data growing"  
    echo "  V3 10:00 UNICORN researcher"
    echo "  V4 10:15 decision_trace rows"
    echo "  V5 11:00 data_health silence"
    echo "  V6 12:00 option chain enriched"
    echo "  V7 15:35 clean close"
    echo "  V8 16:10 cron backfill"
    echo "  V9 EOD   trade_outcomes"
    exit 1
    ;;
esac
