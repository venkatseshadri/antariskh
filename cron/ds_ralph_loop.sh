#!/bin/bash
# DeepSeek build loop — ONE ds:ready issue per run (DEEPSEEK_RALPH_LOOP.md).
# Cron-safe: flock single-instance + per-day cap + timeout + per-day log.
# Picks the lowest unassigned ds:ready issue, hands it to opencode/DeepSeek to
# implement to spec, then stops. Never closes (ds:ready -> ds:done only).
#
# SCAFFOLD — staged for Board review. Installing /etc/cron.d/antariksh-ralph
# enables autonomous DS (incl. market hours, per §0e ruling 3). Not auto-enabled.

set -u

export HOME=/root
REPO=/home/trading_ceo/antariksh
REPO_URL=venkatseshadri/antariskh
LOG_DIR="$REPO/logs"
DAY=$(TZ=Asia/Kolkata date +%Y%m%d)
LOG="$LOG_DIR/ds_ralph_loop_$DAY.log"
LOCK=/tmp/ds_ralph_loop.lock
CAP_FILE="$LOG_DIR/.ds_build_count_$DAY"

PER_DAY_CAP=8
RUN_TIMEOUT=1800

OPENCODE=/root/.opencode/bin/opencode
GH=/usr/bin/gh
GIT=/usr/bin/git

PAUSE="$LOG_DIR/.ralph_paused"

mkdir -p "$LOG_DIR"
log() { echo "[$(date -Is)] $*" >> "$LOG"; }

# --- sudo-free kill switch ---
if [ -e "$PAUSE" ]; then log "paused ($PAUSE present) — skip"; exit 0; fi

# --- MAINTENANCE ONLY WHEN MARKETS CLOSED (fail-closed via prod-tested gate) ---
# Never edit code / restart services / build while equity OR commodity session is
# live — protects capture + order path. check_market_hours.sh exits 0 if the
# session is OPEN (then we skip). Holiday/weekend aware via check_market_open.sh.
GATE="$REPO/cron/check_market_hours.sh"
if [ -x "$GATE" ]; then
    if "$GATE" NSE >/dev/null 2>&1; then log "NSE session live — maintenance skipped"; exit 0; fi
    if "$GATE" MCX >/dev/null 2>&1; then log "MCX session live — maintenance skipped"; exit 0; fi
else
    log "market gate missing ($GATE) — fail-closed, skip"; exit 0
fi

# --- single instance (flock, non-blocking) ---
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

cd "$REPO" || { log "cd failed"; exit 1; }

# --- pick next ready, unassigned, lowest number ---
ISSUE=$("$GH" issue list -R "$REPO_URL" --label ds:ready --state open \
    --json number,assignees \
    -q 'map(select(.assignees|length==0)) | sort_by(.number) | .[0].number' 2>>"$LOG")
if [ -z "$ISSUE" ] || [ "$ISSUE" = "null" ]; then
    log "nothing ds:ready — skip"
    exit 0
fi

# --- DRY RUN: prove guardrails + env, skip claim + opencode (no side effects) ---
if [ "${RALPH_DRYRUN:-0}" = "1" ]; then
    log "DRYRUN: would build #$ISSUE — NO claim, NO opencode"
    log "DRYRUN: opencode=$([ -x "$OPENCODE" ] && echo ok || echo MISSING) flock=held cap=$count/$PER_DAY_CAP"
    exit 0
fi

# --- claim (the lock) ---
"$GH" issue edit -R "$REPO_URL" "$ISSUE" --add-assignee @me >>"$LOG" 2>&1
echo $((count + 1)) > "$CAP_FILE"
log "BUILD start issue #$ISSUE (run $((count + 1))/$PER_DAY_CAP)"

# --- implement ONE issue via opencode/DeepSeek, time-boxed ---
PROMPT="You are DeepSeek, the implementer. Read docs/DEEPSEEK_RALPH_LOOP.md (your \
operating contract) and execute exactly ONE loop iteration for GitHub issue #$ISSUE in \
repo $REPO_URL. Implement the issue's PRD story to its Acceptance/Test AND the 9-dim \
rubric, write/run tests + integration + PORCUPINE, commit referencing #$ISSUE, then set \
the label ds:ready -> ds:done with a handback comment. Do NOT close. ONE issue only."

/usr/bin/timeout "$RUN_TIMEOUT" "$OPENCODE" run -m deepseek/deepseek-chat --thinking \
    "$PROMPT" >>"$LOG" 2>&1
rc=$?
log "BUILD end issue #$ISSUE rc=$rc"

# --- return to a clean master (per golive workflow) ---
"$GIT" checkout master >>"$LOG" 2>&1 || log "git checkout master failed (inspect)"

exit 0
