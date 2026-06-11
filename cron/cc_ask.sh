#!/bin/bash
# cc_ask.sh — relay a Telegram message to Claude Code (headless) and reply on Telegram.
#
# Intended to be invoked by picoclaw when it sees a `/cc <message>` command:
#     /cc penguin status   ->   picoclaw runs:  cc_ask.sh "penguin status"
#
# Claude runs headless in /home/trading_ceo, auto-loading MEMORY.md + the
# SESSION_HANDOFF, so it answers with current project context. Read-only by
# design: the project allowlist permits diagnostics; anything destructive has no
# approver in headless mode and is denied — a safe boundary for a phone channel.
set -uo pipefail

MSG="$*"
CHAT_ID="8317944043"
REPO="/home/trading_ceo"
LOG="$REPO/antariksh/logs/cc_ask.log"
TS="$(date '+%F %T')"
SEC="/root/.picoclaw/.security.yml"

[ -z "${MSG// /}" ] && exit 0
mkdir -p "$(dirname "$LOG")"
echo "[$TS] Q: $MSG" >> "$LOG"

PROMPT="You are answering a Telegram message from the trading-system operator who is away from their desk. Be concise and phone-friendly (a few short lines, no code blocks unless essential). Use project memory for current state. You cannot take destructive actions here (no approver) — if asked to change/restart something, say what command to run or to use picoclaw. Operator message: ${MSG}"

REPLY="$(cd "$REPO" && timeout 240 claude -p "$PROMPT" 2>>"$LOG")"
RC=$?
if [ $RC -ne 0 ] || [ -z "${REPLY// /}" ]; then
  REPLY="⚠️ Claude couldn't answer (rc=$RC — timed out, or a tool needed approval). Use picoclaw for actions, or rephrase as a read-only question."
fi
echo "[$TS] A: ${REPLY:0:600}" >> "$LOG"

# Send to Telegram (token from picoclaw .security.yml), truncated to Telegram's limit.
python3 - "$CHAT_ID" "$SEC" "$REPLY" <<'PY'
import sys, yaml, requests
chat_id, sec_path, reply = sys.argv[1], sys.argv[2], sys.argv[3][:3900]
try:
    sec = yaml.safe_load(open(sec_path))
    token = sec.get("channel_list", {}).get("telegram", {}).get("settings", {}).get("token", "")
    if token:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": "🤖 Claude: " + reply},
            timeout=15,
        )
except Exception as e:
    print("send failed:", e)
PY
