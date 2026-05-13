#!/bin/bash
# Antarkish Crew Dispatch — called by cron for scheduled crew kicks.
# Usage: dispatch_crew.sh <crew> "<query>"

CREW="$1"
QUERY="${2:-Run scheduled task}"
LOG="/home/trading_ceo/antariksh/logs/dispatch_${CREW}.log"

echo "============================================" | tee -a "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Dispatching $CREW: $QUERY" | tee -a "$LOG"

cd /home/trading_ceo/antariksh

# Load DeepSeek key
if [ -z "$DEEPSEEK_API_KEY" ]; then
    export DEEPSEEK_API_KEY=$(python3 -c "
import yaml
with open('/root/.picoclaw/.security.yml') as f:
    s = yaml.safe_load(f)
keys = s.get('model_list',{}).get('deepseek:0',{}).get('api_keys',[])
print(keys[0] if keys else '')
" 2>/dev/null)
    export OPENAI_API_KEY="${DEEPSEEK_API_KEY}"
    export OPENAI_BASE_URL="${DEEPSEEK_BASE_URL:-https://api.deepseek.com/v1}"
    export OPENAI_MODEL_NAME="deepseek-chat"
fi

# Translate crew shorthand to full name
case "$CREW" in
    ceo)  IMPORT="crews.ceo_crew"  BUILDER="build_ceo_crew" ;;
    om)   IMPORT="crews.om_crew"   BUILDER="build_om_crew" ;;
    pm)   IMPORT="crews.pm_crew"   BUILDER="build_pm_crew" ;;
    am)   IMPORT="crews.am_crew"   BUILDER="build_am_crew" ;;
    ta)   IMPORT="crews.ta_crew"   BUILDER="build_ta_crew" ;;
    pa)   IMPORT="crews.pa_crew"   BUILDER="build_pa_crew" ;;
    *)    echo "Unknown crew: $CREW" && exit 1 ;;
esac

/usr/bin/python3 -c "
import sys, os
sys.path.insert(0, '.')
mod = __import__('$IMPORT', fromlist=['$BUILDER'])
builder = getattr(mod, '$BUILDER')
crew = builder()

# Inject PAPER MODE banner + query
from tools.orchestrator import get_trade_mode_banner, inject_learnings, ingest_learnings, is_paper_mode
mode_banner = '## ' + get_trade_mode_banner() + '\n'
if is_paper_mode():
    mode_banner += 'Do NOT place real orders. All trades are simulated.\n'
mode_banner += '\n'

base_task = crew.tasks[0].description
crew.tasks[0].description = mode_banner + base_task + '\n\n## Chairman Directive\n$QUERY'

result = crew.kickoff()
output = str(result)
print(output)

# Store learnings for inter-crew pipeline
ingest_learnings('$CREW', output)
" 2>&1 | tee -a "$LOG"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] $CREW dispatch complete" | tee -a "$LOG"
