#!/bin/bash
# DEPLOY GATE — the ONLY path from dev → prod. Run by a TRUSTED operator
# (trading_ceo/root), never by dsdev. Merges a Chairman-approved branch into the
# prod tree, runs a final PORCUPINE smoke, and (markets-closed only) restarts the
# named services. Refuses during any live session or with an open position.
# Rolls back the merge if the smoke fails.
#
# Usage: deploy_gate.sh <branch> [service ...]
#   e.g. deploy_gate.sh ds/issue-21-stale-fix feed enricher-nifty
set -u

REPO=/home/trading_ceo/antariksh
BRAHMAND=/home/trading_ceo/brahmand
LEDGER="$BRAHMAND/data/order_ledger.json"
GATE="$REPO/cron/check_market_hours.sh"
SMOKE="eod lifecycle tp_hit"          # PORCUPINE core; must pass post-merge
BRANCH="${1:?usage: deploy_gate.sh <branch> [service ...]}"; shift || true
SERVICES=("$@")

say() { echo "[deploy-gate $(date -Is)] $*"; }

# 1) markets must be CLOSED (equity + commodity) — fail-closed
if [ ! -x "$GATE" ]; then say "market gate missing — REFUSE"; exit 1; fi
if "$GATE" NSE >/dev/null 2>&1; then say "NSE session live — REFUSE deploy"; exit 1; fi
if "$GATE" MCX >/dev/null 2>&1; then say "MCX session live — REFUSE deploy"; exit 1; fi

# 2) no open position in the ledger
if [ -f "$LEDGER" ] && /usr/bin/python3 - "$LEDGER" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
orders=d.get("orders",{}) if isinstance(d,dict) else {}
open_=[o for o in orders.values() if isinstance(o,dict)
       and str(o.get("status","")).upper() in ("ACTIVE","OPEN","PENDING","FILLED")]
sys.exit(1 if open_ else 0)
PY
then :; else say "open/active orders in ledger — REFUSE deploy"; exit 1; fi

# 3) merge the approved branch into prod (record rollback point)
cd "$REPO" || { say "cd failed"; exit 1; }
say "fetch + merge origin/$BRANCH"
git fetch --quiet origin "$BRANCH" || { say "fetch failed"; exit 1; }
ROLLBACK=$(git rev-parse HEAD)
git merge --no-ff --no-edit "origin/$BRANCH" || { say "merge conflict — abort"; git merge --abort; exit 1; }

# 4) final smoke — PORCUPINE core must pass on the merged tree
for s in $SMOKE; do
    say "smoke: $s"
    if ! /usr/bin/timeout 180 python3 -m sim.run_scenario "$s" >/dev/null 2>&1; then
        say "SMOKE FAIL ($s) — rolling back to $ROLLBACK"
        git reset --hard "$ROLLBACK"
        exit 1
    fi
done
say "smoke PASS — merge kept ($(git rev-parse --short HEAD))"

# 5) restart named services (only now, markets still closed)
for svc in "${SERVICES[@]}"; do
    say "restart $svc"
    systemctl restart "$svc" 2>&1 | sed 's/^/[deploy-gate] /' || say "restart $svc FAILED — inspect"
done

say "deploy complete: $BRANCH -> prod"
