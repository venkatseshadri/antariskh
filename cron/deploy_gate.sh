#!/bin/bash
# DEPLOY GATE — the ONLY path from dev → prod. Run by a TRUSTED operator
# (trading_ceo/root), never by dsdev. Merges a Chairman-approved branch into the
# prod tree, runs a final PORCUPINE smoke, and (markets-closed only) restarts the
# named services. Refuses during any live session or with an open position.
# Rolls back the merge AND restarts services if the smoke fails.
#
# Usage: deploy_gate.sh <branch> [service ...]
#   e.g. deploy_gate.sh ralph/antariksh/issue-21 feed enricher-nifty
#
# PRE_DEPLOY_HOOKS (optional env array): project-specific checks run before merge.
#   Export from caller: PRE_DEPLOY_HOOKS=("check_cmd_1" "check_cmd_2")
#   Default (empty): only the hardcoded market-hours + position checks run.
set -u

REPO=/home/trading_ceo/antariksh
BRAHMAND=/home/trading_ceo/brahmand
REPO_URL=venkatseshadri/antariskh
LEDGER="$BRAHMAND/data/order_ledger.json"
GATE="$REPO/cron/check_market_hours.sh"
SMOKE="eod lifecycle tp_hit"
BRANCH="${1:?usage: deploy_gate.sh <branch> [service ...]}"; shift || true
SERVICES=("$@")
ROLLBACK_SHA=""

GH=/usr/bin/gh

say() { echo "[deploy-gate $(date -Is)] $*"; }

# Telegram notify (best-effort, non-fatal)
_notify() {
    local msg="$1"
    /usr/bin/python3 -c "
import sys; sys.path.insert(0,'$BRAHMAND')
from notify import send_telegram
send_telegram('''$msg''', dedupe_key='deploy_gate', throttle_min=0)
" 2>/dev/null || true
}

# Extract issue number from branch name (ralph/project/issue-N)
ISSUE_NUM=$(echo "$BRANCH" | grep -oE 'issue-[0-9]+' | grep -oE '[0-9]+' || true)

# ── PRE-CONDITIONS ─────────────────────────────────────────────────────────────

# 1) markets must be CLOSED — fail-closed
if [ ! -x "$GATE" ]; then say "market gate missing — REFUSE"; exit 1; fi
if "$GATE" NSE >/dev/null 2>&1; then say "NSE session live — REFUSE deploy"; exit 1; fi
if "$GATE" MCX >/dev/null 2>&1; then say "MCX session live — REFUSE deploy"; exit 1; fi

# 2) no open position in the ledger
if [ -f "$LEDGER" ] && ! /usr/bin/python3 - "$LEDGER" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
orders = d.get("orders", {}) if isinstance(d, dict) else {}
open_ = [o for o in orders.values()
         if isinstance(o, dict) and str(o.get("status","")).upper() in ("ACTIVE","OPEN","PENDING","FILLED")]
sys.exit(1 if open_ else 0)
PY
then say "open/active orders in ledger — REFUSE deploy"; exit 1; fi

# 3) PRE_DEPLOY_HOOKS — project-specific checks (G15, extensible via caller env)
if [ -n "${PRE_DEPLOY_HOOKS+x}" ]; then
    for hook in "${PRE_DEPLOY_HOOKS[@]}"; do
        say "pre-deploy hook: $hook"
        if ! eval "$hook"; then
            say "DEPLOY BLOCKED: pre-deploy hook failed: $hook"
            exit 1
        fi
    done
fi

# 4) chairman:approve label must be present on the PR (G2)
say "checking chairman:approve on PR for branch $BRANCH"
APPROVED=$("$GH" pr list -R "$REPO_URL" --head "$BRANCH" --json labels \
    -q '.[0].labels[].name' 2>/dev/null | grep -c "chairman:approve" || true)
if [ "${APPROVED:-0}" -eq 0 ]; then
    say "DEPLOY BLOCKED: chairman:approve label not found on PR for $BRANCH"
    _notify "⛔ [antariksh] DEPLOY BLOCKED: chairman:approve missing on $BRANCH"
    exit 1
fi
say "chairman:approve confirmed"

# ── STEP 1: CAPTURE PRE-MERGE STATE ──────────────────────────────────────────
cd "$REPO" || { say "cd failed"; exit 1; }
ROLLBACK_SHA=$(git rev-parse HEAD)
say "rollback SHA: $ROLLBACK_SHA"

# ── STEP 2: MERGE BRANCH ─────────────────────────────────────────────────────
say "fetch + merge origin/$BRANCH"
git fetch --quiet origin "$BRANCH" || { say "fetch failed"; exit 1; }
git merge --no-ff --no-edit "origin/$BRANCH" || {
    say "merge conflict — abort (nothing changed)"
    git merge --abort 2>/dev/null || true
    exit 1
}
say "merged at $(git rev-parse --short HEAD)"

# ── STEP 3: STOP SERVICES (G16) ──────────────────────────────────────────────
if [ "${#SERVICES[@]}" -gt 0 ]; then
    for svc in "${SERVICES[@]}"; do
        say "stopping $svc"
        systemctl stop "$svc" 2>&1 | sed 's/^/[deploy-gate] /' || true
    done
    # Wait up to 10s for services to stop
    STOP_WAIT=0
    while [ "$STOP_WAIT" -lt 10 ]; do
        all_stopped=1
        for svc in "${SERVICES[@]}"; do
            if systemctl is-active "$svc" >/dev/null 2>&1; then all_stopped=0; break; fi
        done
        [ "$all_stopped" -eq 1 ] && break
        sleep 1; STOP_WAIT=$((STOP_WAIT + 1))
    done
    say "services stopped (waited ${STOP_WAIT}s)"
fi

# ── STEP 4: SMOKE TEST ───────────────────────────────────────────────────────
smoke_pass=1
for s in $SMOKE; do
    say "smoke: $s"
    if ! /usr/bin/timeout 180 python3 -m sim.run_scenario "$s" >/dev/null 2>&1; then
        say "SMOKE FAIL ($s)"
        smoke_pass=0
        break
    fi
done

if [ "$smoke_pass" -eq 0 ]; then
    # ── ROLLBACK (G17) ───────────────────────────────────────────────────────
    say "SMOKE FAIL — rolling back to $ROLLBACK_SHA"
    if git reset --hard "$ROLLBACK_SHA"; then
        say "git rollback OK"
    else
        say "CRITICAL: git reset failed — manual intervention required"
        _notify "🚨 [antariksh] ROLLBACK FAILED — manual intervention required (branch: $BRANCH)"
        exit 2
    fi
    # Restart services on rollback (G17)
    if [ "${#SERVICES[@]}" -gt 0 ]; then
        for svc in "${SERVICES[@]}"; do
            say "rollback restart: $svc"
            systemctl restart "$svc" 2>&1 | sed 's/^/[deploy-gate] /' || say "restart $svc FAILED"
        done
        sleep 10
        for svc in "${SERVICES[@]}"; do
            systemctl is-active "$svc" >/dev/null 2>&1 && say "$svc active post-rollback" \
                || say "WARNING: $svc not active post-rollback — inspect"
        done
    fi
    _notify "⛔ [antariksh] DEPLOY ROLLED BACK: $BRANCH. Smoke failed. SHA restored to ${ROLLBACK_SHA:0:8}."
    [ -n "$ISSUE_NUM" ] && "$GH" issue comment -R "$REPO_URL" "$ISSUE_NUM" \
        --body "🔴 Deploy gate: smoke FAILED for \`$BRANCH\`. Rolled back to \`${ROLLBACK_SHA:0:8}\`." 2>/dev/null || true
    exit 1
fi

say "smoke PASS — merge kept ($(git rev-parse --short HEAD))"

# ── STEP 5: START SERVICES + VERIFY (G16) ────────────────────────────────────
if [ "${#SERVICES[@]}" -gt 0 ]; then
    for svc in "${SERVICES[@]}"; do
        say "starting $svc"
        systemctl start "$svc" 2>&1 | sed 's/^/[deploy-gate] /' || say "start $svc WARN"
    done
    sleep 5
    start_fail=0
    for svc in "${SERVICES[@]}"; do
        if ! systemctl is-active "$svc" >/dev/null 2>&1; then
            say "$svc not active after start — triggering rollback"
            start_fail=1; break
        fi
    done
    if [ "$start_fail" -eq 1 ]; then
        # Rollback service start failure
        say "SERVICE START FAIL — rolling back"
        git reset --hard "$ROLLBACK_SHA"
        for svc in "${SERVICES[@]}"; do
            systemctl restart "$svc" 2>&1 || true
        done
        _notify "⛔ [antariksh] DEPLOY ROLLED BACK: $BRANCH. Service start failed."
        exit 1
    fi

    # Poll 30s for failed state
    say "polling 30s for service stability"
    POLL=0
    while [ "$POLL" -lt 30 ]; do
        for svc in "${SERVICES[@]}"; do
            state=$(systemctl is-failed "$svc" 2>/dev/null || true)
            if [ "$state" = "failed" ]; then
                say "$svc entered failed state — rollback"
                git reset --hard "$ROLLBACK_SHA"
                for s2 in "${SERVICES[@]}"; do systemctl restart "$s2" 2>/dev/null || true; done
                _notify "⛔ [antariksh] DEPLOY ROLLED BACK: $BRANCH. $svc failed post-start."
                exit 1
            fi
        done
        sleep 1; POLL=$((POLL + 1))
    done
    say "all services stable"
fi

# ── STEP 6: SUCCESS (G3, G4) ─────────────────────────────────────────────────
say "deploy complete: $BRANCH -> prod"
_notify "✅ [antariksh] DEPLOY SUCCESS: $BRANCH merged. Services running."
if [ -n "$ISSUE_NUM" ]; then
    "$GH" issue close -R "$REPO_URL" "$ISSUE_NUM" \
        --comment "✅ Deployed via deploy gate. Branch: \`$BRANCH\`." 2>/dev/null || true
fi
