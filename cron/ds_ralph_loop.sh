#!/bin/bash
# DeepSeek build loop — CREDENTIAL-LESS SPLIT (E6 isolation).
# Cron runs as ROOT (orchestrator + the only one with GitHub creds). The untrusted
# build runs as dsdev inside the dev CLONE with BRAHMAND_SANDBOX and NO creds/network.
# Root does all git (sync/branch/push) + the label op; dsdev only edits files, runs
# tests, and commits locally (clone is chowned to it for the build).
#
# Safe 24/7: dsdev can't write prod data (perms), restart services (no sudo), or
# reach the prod tree. flock + per-day cap + pause retained.
# RALPH_DRYRUN=1 → sync+pick+branch, skip the opencode build + push.

set -u

# If OUROBOROS_PROJECT is set, source the project config (G1: generic config system).
# Defaults below are used when running without a config (backward compatibility).
PROJECT_NAME="${OUROBOROS_PROJECT:-antariksh}"
_CONF="/home/trading_ceo/ouroboros/projects/${PROJECT_NAME}.conf"
if [ -f "$_CONF" ]; then
    # shellcheck source=/dev/null
    . "$_CONF"
fi

REPO=/home/trading_ceo/antariksh
CLONE="${DEV_DIR:-/home/trading_ceo/dev/antariksh}"
BCLONE="${BDEV_DIR:-/home/trading_ceo/dev/brahmand}"
SANDBOX=/home/trading_ceo/dev/sandbox
REPO_URL="${REPO:-venkatseshadri/antariskh}"
BREPO_URL="${BREPO:-venkatseshadri/brahmand}"
PROJECT_NAME="${PROJECT_NAME:-antariksh}"
# SKIP_TAG: issues whose body contains this tag are loop-unbuildable (ROOT_REPO_ONLY etc.)
SKIP_TAG="${SKIP_TAG:-ROOT_REPO_ONLY}"
LOG_DIR="$REPO/logs"
DAY=$(TZ=Asia/Kolkata date +%Y%m%d)
LOG="$LOG_DIR/ds_ralph_loop_$DAY.log"
# Per-project lock (G14): allows future parallel builds for different projects.
LOCK="/tmp/ouroboros_build_${PROJECT_NAME}.lock"
CAP_FILE="$LOG_DIR/.ds_build_count_$DAY"
# Pause file mirrors LLD canonical location; also checks legacy path.
PAUSE_CANONICAL="/home/trading_ceo/ouroboros/logs/.ralph_paused"
PAUSE_LEGACY="$LOG_DIR/.ralph_paused"
PER_DAY_CAP=8
RUN_TIMEOUT=1800
GH=/usr/bin/gh
GIT=/usr/bin/git
DSDEV=dsdev

mkdir -p "$LOG_DIR"
log() { echo "[$(date -Is)] $*" >> "$LOG"; }

if [ -e "$PAUSE_CANONICAL" ] || [ -e "$PAUSE_LEGACY" ]; then log "paused — skip"; exit 0; fi
exec 9>"$LOCK"; if ! /usr/bin/flock -n 9; then log "already running — skip"; exit 0; fi
count=$(cat "$CAP_FILE" 2>/dev/null || echo 0)
if [ "$count" -ge "$PER_DAY_CAP" ]; then log "per-day cap — skip"; exit 0; fi

$GIT config --global --add safe.directory "$CLONE" 2>/dev/null || true
$GIT config --global --add safe.directory "$BCLONE" 2>/dev/null || true

# 1) sync clones to origin/master (root creds)
for c in "$CLONE" "$BCLONE"; do
    $GIT -C "$c" fetch --quiet origin master 2>>"$LOG" || { log "fetch failed $c"; exit 0; }
    $GIT -C "$c" reset --hard --quiet origin/master 2>>"$LOG"
    $GIT -C "$c" clean -fdq 2>>"$LOG"
done

# 2) pick lowest unassigned ds:ready; skip SKIP_TAG issues (G12)
ISSUE_JSON=$("$GH" issue list -R "$REPO_URL" --label ds:ready --state open --json number,assignees,body \
    -q 'map(select(.assignees|length==0)) | sort_by(.number) | .[0]' 2>>"$LOG")
ISSUE=$(echo "$ISSUE_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin) or {}; print(d.get('number',''))" 2>/dev/null)
if [ -z "$ISSUE" ] || [ "$ISSUE" = "null" ]; then log "nothing ds:ready — skip"; exit 0; fi

ISSUE_BODY=$(echo "$ISSUE_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin) or {}; print(d.get('body',''))" 2>/dev/null)
if echo "$ISSUE_BODY" | grep -qF "$SKIP_TAG"; then
    log "skip #$ISSUE — contains $SKIP_TAG (loop-unbuildable)"; exit 0
fi

ISSUE_TITLE=$("$GH" issue view -R "$REPO_URL" "$ISSUE" --json title -q '.title' 2>>"$LOG")
# Branch naming: ralph/{project}/issue-{N} (G13)
BR="ralph/${PROJECT_NAME}/issue-${ISSUE}"

# 3) branch (root) in both clones
$GIT -C "$CLONE" checkout -B "$BR" --quiet 2>>"$LOG"
$GIT -C "$BCLONE" checkout -B "$BR" --quiet 2>>"$LOG"

if [ "${RALPH_DRYRUN:-0}" = "1" ]; then
    log "DRYRUN: synced+picked #$ISSUE ($ISSUE_TITLE), branch $BR — NO build/push. cap=$count/$PER_DAY_CAP"
    exit 0
fi

# 4) claim + stage the task, hand the clones to dsdev for the build
"$GH" issue edit -R "$REPO_URL" "$ISSUE" --add-assignee @me >>"$LOG" 2>&1
"$GH" issue view -R "$REPO_URL" "$ISSUE" --json title,body -q '.title + "\n\n" + .body' \
    > "$CLONE/.ralph_task.md" 2>>"$LOG"
chown -R "$DSDEV":"$DSDEV" "$CLONE" "$BCLONE"
echo $((count + 1)) > "$CAP_FILE"
log "BUILD #$ISSUE start (dsdev, sandbox, no creds) run $((count+1))/$PER_DAY_CAP"

# 5) BUILD as dsdev — opencode implements, runs tests, commits LOCALLY (no push/gh/network)
PROMPT="You are DeepSeek implementing ONE story. The spec is ./.ralph_task.md (read it first). \
Work ONLY in this repo clone (and ../brahmand if the story spans both). Implement to its \
Acceptance/Test + the 9-dim rubric. Run its tests + relevant PORCUPINE scenarios \
(python3 -m sim.run_scenario ...). When green, \`git add\` + \`git commit\` with a conventional \
message referencing #$ISSUE and [deepseek]. Do NOT push, do NOT use gh, do NOT touch any path \
outside these clones."
sudo -u "$DSDEV" env HOME=/home/"$DSDEV" BRAHMAND_SANDBOX="$SANDBOX" \
    /usr/bin/timeout "$RUN_TIMEOUT" opencode run -m deepseek/deepseek-chat --thinking "$PROMPT" \
    >>"$LOG" 2>&1
OPENCODE_RC=$?
log "BUILD #$ISSUE opencode rc=$OPENCODE_RC"

# 6) root (trusted, narrow): push any branch that got commits + PR + handback label (G5, G6)
pushed=0
for pair in "$CLONE:$REPO_URL" "$BCLONE:$BREPO_URL"; do
    dir="${pair%%:*}"
    repo="${pair##*:}"
    if [ -n "$($GIT -C "$dir" log "origin/master..$BR" --oneline 2>/dev/null)" ]; then
        if $GIT -C "$dir" push origin "$BR" >>"$LOG" 2>&1; then
            log "pushed $BR ($dir)"
            pushed=1
            # Create PR for review (G6) — required for chairman:approve gate in deploy
            "$GH" pr create -R "$repo" \
                --title "#${ISSUE}: ${ISSUE_TITLE}" \
                --body "Closes #${ISSUE}" \
                --base master --head "$BR" >>"$LOG" 2>&1 || log "pr create warn (may already exist)"
        else
            log "push failed $BR ($dir)"
        fi
    fi
done

if [ "$pushed" = "1" ]; then
    "$GH" issue edit -R "$REPO_URL" "$ISSUE" --remove-label ds:ready --add-label ds:done >>"$LOG" 2>&1
    "$GH" issue comment -R "$REPO_URL" "$ISSUE" \
        --body "🤖 ds-build: \`$BR\` pushed (isolated, no creds). Tests run by dsdev. PR created. Ready for review." \
        >>"$LOG" 2>&1
    log "handback #$ISSUE -> ds:done"
else
    # G5: no commits → post failure comment + changes:requested so DS gets feedback
    FAIL_SNIPPET=$(tail -50 "$LOG" | head -c 2000)
    "$GH" issue comment -R "$REPO_URL" "$ISSUE" \
        --body "🔴 ds-build failed for \`$BR\`: no commits from dsdev (opencode rc=${OPENCODE_RC}).

\`\`\`
${FAIL_SNIPPET}
\`\`\`" >>"$LOG" 2>&1 || true
    "$GH" issue edit -R "$REPO_URL" "$ISSUE" \
        --remove-label ds:ready --add-label changes:requested >>"$LOG" 2>&1 || true
    log "no commits from dsdev for #$ISSUE — posted failure + set changes:requested"
fi

# 7) reset clones to master for next run
$GIT -C "$CLONE" checkout --quiet master 2>>"$LOG"; $GIT -C "$BCLONE" checkout --quiet master 2>>"$LOG"
exit 0
