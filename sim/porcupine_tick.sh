#!/usr/bin/env bash
# PORCUPINE scheduled tick — deterministic health + regression monitor.
# Runs the live trading-system health check + the harness regression gate and
# prints a concise report (picoclaw delivers it to Telegram). Makes NO code
# changes — building PORCUPINE stays human-in-loop. Cron: weekdays 11:00 & 16:00.
set -uo pipefail
cd /home/trading_ceo/antariksh || exit 1
PROD=/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite
ALERT=0
echo "🦔 PORCUPINE tick — $(date '+%F %T %Z')"
echo "────────────────────────────"

# 1) Live trading-system health
echo "LIVE SYSTEM:"
for s in feed consumer-nifty enricher-nifty; do
  act=$(systemctl is-active "$s.service" 2>/dev/null)
  nr=$(systemctl show "$s.service" -p NRestarts --value 2>/dev/null)
  flag=""; [ "$act" != "active" ] && { flag=" ⚠️"; ALERT=1; }
  [ "${nr:-0}" -gt 3 ] 2>/dev/null && { flag="$flag ⚠️restarts=$nr"; ALERT=1; }
  printf "  %-16s %s%s\n" "$s" "$act" "$flag"
done

# 2) Data integrity today (the bugs we fixed must stay fixed)
read -r total lowzero enr <<<"$(sqlite3 "$PROD" "SELECT
  (SELECT COUNT(*) FROM market_data WHERE date(timestamp)=date('now')),
  (SELECT COUNT(*) FROM market_data WHERE date(timestamp)=date('now') AND low<=0),
  (SELECT COUNT(*) FROM market_data_enriched WHERE date(timestamp)=date('now'));" 2>/dev/null | tr '|' ' ')"
echo "DATA TODAY: raw=$total enriched=$enr low<=0=$lowzero"
[ "${lowzero:-0}" -gt 0 ] 2>/dev/null && { echo "  ⚠️ low=0 REGRESSION — feed lp-less filter broken!"; ALERT=1; }
[ "${total:-0}" -gt 5 ] 2>/dev/null && [ "${enr:-0}" -lt $((total/2)) ] && { echo "  ⚠️ enriched lagging raw badly"; ALERT=1; }

# 3) Harness regression gate (deterministic, no code changes)
echo "REGRESSION:"
if timeout 60 python3 -m sim.tests.test_isolation >/dev/null 2>&1; then echo "  ✅ isolation 4/4"; else echo "  ❌ isolation FAILED"; ALERT=1; fi
if timeout 60 python3 -m sim.tests.test_feed_bar_integrity >/dev/null 2>&1; then echo "  ✅ feed bar-integrity 2/2"; else echo "  ❌ feed bar-integrity FAILED"; ALERT=1; fi

# 4) Next PORCUPINE item (the nag)
echo "NEXT (build when you're in a session):"
sed -n '/^## 7. NEXT/,/^## 8/p' docs/PORCUPINE_STATE.md 2>/dev/null | grep -E '^[0-9]+\.' | head -3 | sed 's/^/  /'

echo "────────────────────────────"
[ "$ALERT" -eq 0 ] && echo "STATUS: ✅ all green" || echo "STATUS: ⚠️ ATTENTION NEEDED (see ⚠️ above)"
exit $ALERT
