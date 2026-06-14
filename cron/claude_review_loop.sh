#!/bin/bash
# Claude review loop — Option A+ (READ-ONLY validate + GH COMMENTS + NOTIFY) of S4.1.
# Validates DS deliverables under a least-privilege allowlist (review_settings.json):
# runs read-only Accept commands, POSTS its verdict as a GitHub issue/PR comment
# (additive, reversible), prints the report to stdout (captured to log), and the
# WRAPPER alerts via Telegram. It NEVER changes labels, closes, merges, edits files,
# or pushes — only the Chairman flips labels (§0b validator; PRD §5 state machine).
#
# Cron-safe: flock single-instance + per-day cap + timeout + per-day log.
# RALPH_DRYRUN=1 → exercise every guardrail but skip the claude -p call.

set -u

export HOME=/root
REPO=/home/trading_ceo/antariksh
BRAHMAND=/home/trading_ceo/brahmand
REPO_URL=venkatseshadri/antariskh
LOG_DIR="$REPO/logs"
DAY=$(TZ=Asia/Kolkata date +%Y%m%d)
LOG="$LOG_DIR/claude_review_loop_$DAY.log"
LOCK=/tmp/claude_review_loop.lock
CAP_FILE="$LOG_DIR/.claude_review_count_$DAY"
SHA_FILE="$REPO/data/last_reviewed_sha"
SETTINGS="$REPO/cron/review_settings.json"
PAUSE="$LOG_DIR/.ralph_paused"

PER_DAY_CAP=12
RUN_TIMEOUT=1500

CLAUDE=/root/.local/bin/claude
GH=/usr/bin/gh
GIT=/usr/bin/git
GATE="$REPO/cron/check_market_hours.sh"

# Telegram secrets for notify.send_telegram (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).
# Point RALPH_ENV_FILE at wherever they live; sourced safely (set -a, never printed).
RALPH_ENV_FILE="${RALPH_ENV_FILE:-/home/trading_ceo/brahmand/.env}"

mkdir -p "$LOG_DIR" "$REPO/data"
log() { echo "[$(date -Is)] $*" >> "$LOG"; }

if [ -f "$RALPH_ENV_FILE" ]; then set -a; . "$RALPH_ENV_FILE"; set +a; fi

# --- sudo-free kill switch ---
if [ -e "$PAUSE" ]; then log "paused ($PAUSE present) — skip"; exit 0; fi

# --- MAINTENANCE ONLY WHEN MARKETS CLOSED (fail-closed via prod-tested gate) ---
if [ -x "$GATE" ]; then
    if "$GATE" NSE >/dev/null 2>&1; then log "NSE session live — review skipped"; exit 0; fi
    if "$GATE" MCX >/dev/null 2>&1; then log "MCX session live — review skipped"; exit 0; fi
else
    log "market gate missing ($GATE) — fail-closed, skip"; exit 0
fi

# --- single instance ---
exec 9>"$LOCK"
if ! /usr/bin/flock -n 9; then log "already running — skip"; exit 0; fi

# --- per-day token brake ---
count=$(cat "$CAP_FILE" 2>/dev/null || echo 0)
if [ "$count" -ge "$PER_DAY_CAP" ]; then log "per-day cap $PER_DAY_CAP reached — skip"; exit 0; fi

# --- is there anything to review? (ds:done issues OR new [deepseek] commits) ---
DS_DONE=$("$GH" issue list -R "$REPO_URL" --label ds:done --state open --json number -q 'length' 2>>"$LOG")
LAST_SHA=$(cat "$SHA_FILE" 2>/dev/null || echo "")
NEW_COMMITS=$(cd "$BRAHMAND" && "$GIT" log --grep='\[deepseek\]' --oneline \
    ${LAST_SHA:+"$LAST_SHA"..HEAD} 2>/dev/null | wc -l)

if [ "${DS_DONE:-0}" -eq 0 ] && [ "${NEW_COMMITS:-0}" -eq 0 ]; then
    log "nothing to review (ds:done=0, new [deepseek] commits=0) — skip"
    exit 0
fi

# --- DRY RUN: prove guardrails + env, skip the LLM ---
if [ "${RALPH_DRYRUN:-0}" = "1" ]; then
    log "DRYRUN: would review (ds:done=$DS_DONE, new_commits=$NEW_COMMITS)"
    log "DRYRUN: settings=$([ -f "$SETTINGS" ] && echo present || echo MISSING) claude=$([ -x "$CLAUDE" ] && echo ok || echo MISSING) flock=held cap=$count/$PER_DAY_CAP"
    exit 0
fi

echo $((count + 1)) > "$CAP_FILE"
log "REVIEW start (ds:done=$DS_DONE, new=$NEW_COMMITS, run $((count + 1))/$PER_DAY_CAP)"

PROMPT="You are Claude, the VALIDATOR (role §0b, docs/DAMBUILDER_STATE.md): raise + validate \
ONLY. You have NO write tools — do not attempt to edit files, labels, or push; just analyse \
and PRINT a report. Do all read-only: \
(1) For each GitHub issue labelled ds:done in $REPO_URL, re-run its story's Accept/Verify \
commands, state PASS/FAIL with the command output, and POST that verdict as a comment on \
the issue via 'gh issue comment <N>' prefixed '🤖 ralph-review (read-only — no label change)'. \
Do NOT change labels, close, or merge — a human/the Chairman flips labels. \
(2) For each [deepseek] commit in brahmand + antariksh since SHA '$LAST_SHA', re-run the \
relevant task's Accept and give a verdict (PASS=✅✅ / FAIL=❌ / PARTIAL=◐) with evidence. \
(3) INTEGRITY SWEEP: scan docs/DAMBUILDER_STATE.md for ✅✅ or '✅ FIXED' lines added since \
'$LAST_SHA' that are NOT in a validator-authored block — flag each as a §0e rule-3 candidate. \
Accept-command output is the arbiter. End your report with EXACTLY one line: \
'REVIEW_RESULT: GREEN' if everything passed and no integrity flags, else 'REVIEW_RESULT: ISSUES'."

/usr/bin/timeout "$RUN_TIMEOUT" "$CLAUDE" -p "$PROMPT" \
    --settings "$SETTINGS" --add-dir "$BRAHMAND" --strict-mcp-config >>"$LOG" 2>&1
rc=$?
log "REVIEW end rc=$rc"

# --- alert on issues (wrapper notifies; claude has no write tools) ---
if grep -q "REVIEW_RESULT: ISSUES" "$LOG" 2>/dev/null || grep -q "❌" "$LOG" 2>/dev/null; then
    MSG="🔴 Ralph review found issues $(date -Is). See logs/claude_review_loop_$DAY.log (apply verdicts manually)."
    /usr/bin/python3 -c "import sys; sys.path.insert(0,'$BRAHMAND'); from notify import send_telegram; send_telegram('''$MSG''', dedupe_key='ralph_review', throttle_min=30)" >>"$LOG" 2>&1 || log "notify failed"
fi

# --- advance watermark only on a clean run ---
if [ "$rc" -eq 0 ]; then
    (cd "$BRAHMAND" && "$GIT" rev-parse HEAD) > "$SHA_FILE" 2>>"$LOG"
    log "last_reviewed_sha -> $(cat "$SHA_FILE")"
fi

exit 0
