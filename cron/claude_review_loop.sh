#!/bin/bash
# Claude review loop — validate DS deliverables (S4.1 spec).
# Cron-safe: flock single-instance + per-day cap + timeout + per-day log.
# Reviews ds:done issues AND [deepseek] commits since last_reviewed_sha, runs
# an integrity sweep for self-marked validator lines, and writes verdicts.
# VALIDATION-ONLY: raises + validates, never edits pipeline/order code (§0b).
#
# SCAFFOLD — staged for Board review. Not auto-enabled.

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

PER_DAY_CAP=12
RUN_TIMEOUT=1500

CLAUDE=/root/.local/bin/claude
GH=/usr/bin/gh
GIT=/usr/bin/git

mkdir -p "$LOG_DIR" "$REPO/data"
log() { echo "[$(date -Is)] $*" >> "$LOG"; }

# --- single instance ---
exec 9>"$LOCK"
if ! /usr/bin/flock -n 9; then
    log "already running — skip"
    exit 0
fi

# --- per-day token brake ---
count=$(cat "$CAP_FILE" 2>/dev/null || echo 0)
if [ "$count" -ge "$PER_DAY_CAP" ]; then
    log "per-day cap $PER_DAY_CAP reached — skip"
    exit 0
fi

# --- is there anything to review? (ds:done issues OR new [deepseek] commits) ---
DS_DONE=$("$GH" issue list -R "$REPO_URL" --label ds:done --state open \
    --json number -q 'length' 2>>"$LOG")
LAST_SHA=$(cat "$SHA_FILE" 2>/dev/null || echo "")
NEW_COMMITS=$(cd "$BRAHMAND" && "$GIT" log --grep='\[deepseek\]' --oneline \
    ${LAST_SHA:+"$LAST_SHA"..HEAD} 2>/dev/null | wc -l)

if [ "${DS_DONE:-0}" -eq 0 ] && [ "${NEW_COMMITS:-0}" -eq 0 ]; then
    log "nothing to review (ds:done=0, new [deepseek] commits=0) — skip"
    exit 0
fi

echo $((count + 1)) > "$CAP_FILE"
log "REVIEW start (ds:done=$DS_DONE, new commits=$NEW_COMMITS, run $((count + 1))/$PER_DAY_CAP)"

PROMPT="You are Claude, the VALIDATOR (role §0b in docs/DAMBUILDER_STATE.md): you raise and \
validate ONLY — never edit pipeline/order/feed code, never implement fixes. Do all of: \
(1) For each GitHub issue labelled ds:done in $REPO_URL, re-run that story's Accept/Verify \
commands; on pass set label chairman:approve, on fail set changes:requested with a comment \
listing exactly what failed. Never self-approve, never close. \
(2) For each [deepseek] commit in brahmand and antariksh since SHA '$LAST_SHA', re-run the \
relevant task's Accept and append a validator verdict (✅✅/❌/◐) to its task block in \
docs/DAMBUILDER_STATE.md (append-only, validator-owned). \
(3) INTEGRITY SWEEP: grep docs/DAMBUILDER_STATE.md for ✅✅ or '✅ FIXED' lines added since \
'$LAST_SHA' that are NOT in a validator-authored block; flag each as a §0e rule-3 candidate \
violation and revert the task to its honest status. A self-marked ✅✅ is an automatic ❌. \
(4) Commit doc/label changes; notify via picoclaw on any ❌ or violation, silent if all green."

/usr/bin/timeout "$RUN_TIMEOUT" "$CLAUDE" -p "$PROMPT" \
    --permission-mode acceptEdits >>"$LOG" 2>&1
rc=$?
log "REVIEW end rc=$rc"

# --- advance the watermark (brahmand HEAD; antariksh tracked separately by the doc) ---
if [ "$rc" -eq 0 ]; then
    (cd "$BRAHMAND" && "$GIT" rev-parse HEAD) > "$SHA_FILE" 2>>"$LOG"
    log "last_reviewed_sha -> $(cat "$SHA_FILE")"
fi

exit 0
