#!/usr/bin/env bash
# PORCUPINE gated autonomous builder.
# Flow: free status check → if COMPLETE do nothing (₹0) → else invoke `claude -p`
# ONCE to build the next item. Self-terminates at completion. Stuck-guard pauses
# after 4 no-progress attempts so it can never burn tokens forever.
#
# SAFETY: claude is scoped — edits expected under sim/ & tests/ (prompt), and Bash
# is allow-listed to python3/git ONLY, so it cannot restart services, rm data, or
# run anything destructive. Commits to git for auditability.
#
# Env: DRY=1 skips the claude call (plumbing test, ₹0).
set -uo pipefail
cd /home/trading_ceo/antariksh || exit 1
LOG=sim/logs/autobuild.log
PAUSE=sim/.autobuild_paused
ATTEMPTS=sim/.autobuild_attempts
mkdir -p sim/logs
ts() { date '+%F %T'; }
tg() { python3 -c "import sys;sys.path.insert(0,'.');from tools.log_analyzer import send_telegram;send_telegram('''$1''')" 2>/dev/null || true; }

# Paused by stuck-guard → report only, no spend
[ -f "$PAUSE" ] && { echo "$(ts) paused (stuck-guard)"; exit 0; }

# Singleton — don't overlap a still-running build
exec 9>sim/.autobuild.lock
flock -n 9 || { echo "$(ts) another build running — skip"; exit 0; }

# Free status check (also nags Telegram on change)
python3 -m sim.porcupine_status --send >> "$LOG" 2>&1
if python3 -m sim.porcupine_status >/dev/null 2>&1; then
  echo "$(ts) COMPLETE — nothing to build (₹0)" >> "$LOG"
  rm -f "$ATTEMPTS"
  exit 0
fi

# Stuck-guard: if milestone signature unchanged across attempts, count; pause at 4
SIG=$(python3 -c "import json;print(json.load(open('sim/.porcupine_status.json'))['sig'])" 2>/dev/null || echo none)
read -r LASTSIG CNT < <(cat "$ATTEMPTS" 2>/dev/null || echo "x 0")
if [ "$SIG" = "$LASTSIG" ]; then CNT=$((CNT+1)); else CNT=1; fi
echo "$SIG $CNT" > "$ATTEMPTS"
if [ "$CNT" -ge 4 ]; then
  touch "$PAUSE"
  echo "$(ts) PAUSED — no progress in 4 attempts" >> "$LOG"
  tg "🦔 PORCUPINE autobuild PAUSED — no progress in 4 tries, needs a human. Resume: rm sim/.autobuild_paused"
  exit 0
fi

echo "$(ts) building next item (attempt $CNT for sig $SIG)" >> "$LOG"

PROMPT='You are advancing Project PORCUPINE, an offline test harness. Read docs/PORCUPINE_STATE.md (the "NEXT" list) and build the SINGLE next incomplete item, then stop.
HARD RULES (do not violate):
- Only create/edit files under sim/ and tests/. NEVER edit feed.py, consumers/, enrichers/, config/, or anything under brahmand/ or python-trader/ — that is live trading code.
- NEVER restart, start, or stop any service. NEVER delete data or DB files.
- After building, run the relevant tests in sim/tests/ and (if relevant) `python3 -m sim.run_scenario happy_path --date 2026-06-05`; ensure they pass before finishing.
- If you complete bug #3 (entry-agent deterministic_fallback root-cause/guard) create empty marker file sim/.bug3_fixed. If bug #4 (VIX-null auto-enter guard) create sim/.bug4_fixed.
- Commit ONLY your harness work: `git add sim tests && git commit -m "porcupine: <summary>"`.
- Update docs/PORCUPINE_STATE.md NEXT list to reflect what you finished.
Keep changes surgical and minimal. End with a 3-line summary of what you built and test results.'

if [ "${DRY:-0}" = "1" ]; then
  echo "$(ts) DRY run — would invoke claude -p now (skipped)" >> "$LOG"
  exit 0
fi

timeout 1200 claude -p "$PROMPT" \
  --permission-mode acceptEdits \
  --allowedTools 'Bash(python3:*)' 'Bash(git add:*)' 'Bash(git commit:*)' 'Bash(git status:*)' 'Bash(git diff:*)' Edit Write Read Grep Glob \
  >> "$LOG" 2>&1
RC=$?
echo "$(ts) claude exited rc=$RC" >> "$LOG"

# Report new status (force a Telegram update after a build attempt)
python3 -m sim.porcupine_status --send --force >> "$LOG" 2>&1
tg "🦔 PORCUPINE autobuild ran (rc=$RC). $(python3 -m sim.porcupine_status 2>/dev/null | tail -1)"
