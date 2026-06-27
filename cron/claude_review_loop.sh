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

_notify() {
    local msg="$1"
    /usr/bin/python3 -c "
import sys; sys.path.insert(0,'$BRAHMAND')
from notify import send_telegram
send_telegram('''$msg''', dedupe_key='ralph_review', throttle_min=30)
" 2>/dev/null || true
}

# ── INTEGRITY SWEEP (G10) ────────────────────────────────────────────────────
# Deterministic pre-flight check on PR diff text. Runs BEFORE Claude.
# Patterns match the LLD (Patterns A-D). Sets INTEGRITY_FAIL / HALLUCINATION_DETECTED.
# Args: $1=diff_text_file  $2=master_md_snapshot_file  $3=commit_messages_file
# Outputs: sweep_result="PASS|INTEGRITY_FAIL", sweep_findings (multi-line), hallucination_detected
_integrity_sweep() {
    local diff_file="$1"
    local master_md_file="$2"
    local commits_file="$3"
    sweep_result="PASS"
    sweep_findings=""
    hallucination_detected=false

    # Pattern A: direct self-mark — new ✅✅ lines in .md files
    PA=$(grep -E '^\+.*✅✅' "$diff_file" 2>/dev/null | grep -v '^+++' || true)
    if [ -n "$PA" ]; then
        sweep_result="INTEGRITY_FAIL"
        sweep_findings+="[Pattern A] Direct self-mark (✅✅ added):"$'\n'"$PA"$'\n'
    fi

    # Pattern B: polarity flip — line that was ❌/FAIL/⚠️ in master is now ✅/PASS in branch
    # Look for removed negative lines and added positive lines in same .md context
    REMOVED_NEG=$(grep -E '^\-.*[❌⚠️]|^\-.*\bFAIL\b' "$diff_file" 2>/dev/null | grep -v '^---' || true)
    ADDED_POS=$(grep -E '^\+.*✅|^\+.*\bPASS\b' "$diff_file" 2>/dev/null | grep -v '^+++' || true)
    if [ -n "$REMOVED_NEG" ] && [ -n "$ADDED_POS" ]; then
        sweep_result="INTEGRITY_FAIL"
        sweep_findings+="[Pattern B] Polarity flip (negative removed, positive added):"$'\n'
        sweep_findings+="  Removed: $(echo "$REMOVED_NEG" | head -2)"$'\n'
        sweep_findings+="  Added:   $(echo "$ADDED_POS" | head -2)"$'\n'
    fi

    # Pattern C: fabricated artifact claim — commits say "tests pass"/"verified" but no test files touched
    if [ -f "$commits_file" ]; then
        CLAIM=$(grep -iE 'tests? pass|verified|all tests|checks? pass' "$commits_file" || true)
        TEST_FILES=$(grep -E '^\+\+\+ b/(test_|tests/|_test\.)' "$diff_file" || true)
        if [ -n "$CLAIM" ] && [ -z "$TEST_FILES" ]; then
            hallucination_detected=true
            sweep_findings+="[Pattern C] Hallucination: commit claims tests pass but no test files in diff."$'\n'
        fi
    fi

    # Pattern D: deleted red flag — OPEN:/TODO:/KNOWN BUG:/⚠️ lines removed without replacement
    if [ -f "$master_md_file" ]; then
        REMOVED_FLAGS=$(grep -E '^\-.*\b(OPEN:|TODO:|KNOWN BUG:)' "$diff_file" 2>/dev/null | grep -v '^---' || true)
        if [ -n "$REMOVED_FLAGS" ]; then
            sweep_findings+="[Pattern D] Deleted red flag (severity: critical):"$'\n'"$REMOVED_FLAGS"$'\n'
        fi
    fi
}

# --- sudo-free kill switch ---
PAUSE_CANONICAL="/home/trading_ceo/ouroboros/logs/.ralph_paused"
if [ -e "$PAUSE" ] || [ -e "$PAUSE_CANONICAL" ]; then log "paused — skip"; exit 0; fi

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

# ── Fetch PR diff + metadata for integrity sweep (G10) ───────────────────────
ISSUE_NUM=$("$GH" issue list -R "$REPO_URL" --label ds:done --state open \
    --json number -q '.[0].number' 2>>"$LOG" || true)
DIFF_TMP=$(mktemp /tmp/ralph_review_diff_XXXXXX.txt)
COMMITS_TMP=$(mktemp /tmp/ralph_review_commits_XXXXXX.txt)
MASTER_MD_TMP=$(mktemp /tmp/ralph_review_master_XXXXXX.txt)
cleanup_temps() { rm -f "$DIFF_TMP" "$COMMITS_TMP" "$MASTER_MD_TMP"; }
trap cleanup_temps EXIT

PR_NUM=""
if [ -n "$ISSUE_NUM" ] && [ "$ISSUE_NUM" != "null" ]; then
    PR_NUM=$("$GH" pr list -R "$REPO_URL" --search "closes #$ISSUE_NUM" \
        --json number -q '.[0].number' 2>>"$LOG" || true)
    if [ -n "$PR_NUM" ] && [ "$PR_NUM" != "null" ]; then
        "$GH" pr diff "$PR_NUM" -R "$REPO_URL" > "$DIFF_TMP" 2>>"$LOG" || true
        "$GH" pr view "$PR_NUM" -R "$REPO_URL" --json commits \
            -q '.commits[].messageHeadline' > "$COMMITS_TMP" 2>>"$LOG" || true
        # Snapshot relevant master .md content for Pattern D
        (cd "$REPO" && git show master:docs/DAMBUILDER_STATE.md 2>/dev/null \
            | head -200 > "$MASTER_MD_TMP") || true
    fi
fi

# ── Run deterministic integrity sweep BEFORE Claude (G10) ────────────────────
_integrity_sweep "$DIFF_TMP" "$MASTER_MD_TMP" "$COMMITS_TMP"
log "integrity sweep: result=$sweep_result hallucination=$hallucination_detected"

# ── Build verdict prefix for Claude prompt ────────────────────────────────────
SWEEP_SECTION="INTEGRITY SWEEP RESULT: $sweep_result"
if [ -n "$sweep_findings" ]; then
    SWEEP_SECTION+=$'\n'"$sweep_findings"
fi
if $hallucination_detected; then
    SWEEP_SECTION+=$'\n'"HALLUCINATION FLAG: true — commits claim test results not visible in diff."
fi

# If INTEGRITY_FAIL → skip Claude, post verdict directly
if [ "$sweep_result" = "INTEGRITY_FAIL" ]; then
    log "INTEGRITY_FAIL — skipping Claude review (deterministic)"
    VERDICT_BODY="## Review: INTEGRITY_FAIL (pre-flight, no Claude call)

$sweep_findings

🤖 ralph-review (read-only — no label change)"

    if [ -n "$ISSUE_NUM" ] && [ "$ISSUE_NUM" != "null" ]; then
        "$GH" issue comment "$ISSUE_NUM" -R "$REPO_URL" --body "$VERDICT_BODY" >>"$LOG" 2>&1 || true
    fi
    _notify "⚠️ [antariksh] Review #${ISSUE_NUM:-?}: INTEGRITY_FAIL — ${sweep_findings:0:120}"
    # advance watermark is NOT done on integrity fail (issue stays ds:done for human)
    exit 0
fi

# ── Claude review with structured JSON output (G11) ──────────────────────────
PROMPT="You are Claude, the VALIDATOR (role §0b, docs/DAMBUILDER_STATE.md): raise + validate ONLY. \
No write tools — do not edit files, labels, or push.

PRE-FLIGHT SWEEP (already run deterministically):
$SWEEP_SECTION

YOUR TASK:
(1) For each GitHub issue labelled ds:done in $REPO_URL, re-run its story's Accept/Verify \
commands, state PASS/FAIL with the command output, and POST that verdict as a comment on \
the issue via 'gh issue comment <N>' prefixed '🤖 ralph-review (read-only — no label change)'. \
Do NOT change labels, close, or merge — the Chairman flips labels. \
(2) For each [deepseek] commit in brahmand + antariksh since SHA '$LAST_SHA', re-run the \
relevant task's Accept and give a verdict (PASS=✅✅ / FAIL=❌ / PARTIAL=◐) with evidence. \
(3) Flag any ✅✅ or '✅ FIXED' lines in docs since '$LAST_SHA' not in validator-authored block.

End your ENTIRE response with a JSON block (no markdown fences) on the final lines:
{\"verdict\": \"PASS\" | \"FAIL\" | \"NEEDS_CLARIFICATION\", \
\"summary\": \"1-2 sentences\", \
\"hallucination_detected\": true | false, \
\"hallucination_detail\": null | \"string\"}"

/usr/bin/timeout "$RUN_TIMEOUT" "$CLAUDE" -p "$PROMPT" \
    --settings "$SETTINGS" --add-dir "$BRAHMAND" --strict-mcp-config >>"$LOG" 2>&1
rc=$?
log "REVIEW end rc=$rc"

# ── Parse JSON verdict from Claude output (G11) ───────────────────────────────
CLAUDE_VERDICT=$(/usr/bin/python3 - <<PYEOF 2>/dev/null || echo "REVIEW_ERROR"
import re, json
log = open("$LOG").read()
# Find last JSON-like object in the log
matches = list(re.finditer(r'\{"verdict"[^}]+\}', log, re.DOTALL))
if not matches:
    print("REVIEW_ERROR")
else:
    try:
        obj = json.loads(matches[-1].group())
        print(obj.get("verdict", "REVIEW_ERROR"))
    except Exception:
        print("REVIEW_ERROR")
PYEOF
)
log "parsed verdict: $CLAUDE_VERDICT"

# ── Alert on issues ───────────────────────────────────────────────────────────
case "$CLAUDE_VERDICT" in
    PASS)
        MSG="✅ [antariksh] Review #${ISSUE_NUM:-?}: PASS. $(date -Is)"
        ;;
    FAIL|NEEDS_CLARIFICATION)
        MSG="🔴 [antariksh] Review #${ISSUE_NUM:-?}: $CLAUDE_VERDICT. See logs/claude_review_loop_$DAY.log"
        _notify "$MSG"
        ;;
    REVIEW_ERROR|*)
        MSG="⚠️ [antariksh] Review loop: verdict parse error (rc=$rc). Manual check needed."
        _notify "$MSG"
        ;;
esac
log "notify: $MSG"

if $hallucination_detected || grep -q "hallucination_detected.*true" "$LOG" 2>/dev/null; then
    _notify "⚠️ [antariksh] HALLUCINATION DETECTED in review #${ISSUE_NUM:-?}"
fi

# ── Advance watermark only on clean run ──────────────────────────────────────
if [ "$rc" -eq 0 ]; then
    (cd "$BRAHMAND" && "$GIT" rev-parse HEAD) > "$SHA_FILE" 2>>"$LOG"
    log "last_reviewed_sha -> $(cat "$SHA_FILE")"
fi

exit 0
