#!/bin/bash
# Antariksh Trading Query Bridge for Picoclaw/Kubera
# Kubera calls this when user sends /ant <query>
# Routes to correct crew via orchestrator + DeepSeek + Ralph PRD check.

QUERY="$*"
ANTARIKSH_DIR="/home/trading_ceo/antariksh"

if [ -z "$QUERY" ]; then
    echo "Usage: antariskh_query.sh <your trading question>"
    exit 1
fi

# Load DeepSeek API key from Picoclaw security file
if [ -z "$DEEPSEEK_API_KEY" ] && [ -f /root/.picoclaw/.security.yml ]; then
    export DEEPSEEK_API_KEY=$(python3 -c "
import yaml
with open('/root/.picoclaw/.security.yml') as f:
    s = yaml.safe_load(f)
keys = s.get('model_list',{}).get('deepseek:0',{}).get('api_keys',[])
print(keys[0] if keys else '')
" 2>/dev/null)
fi

# Fallback: try from environment
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
export OPENAI_API_KEY="${DEEPSEEK_API_KEY}"
export OPENAI_BASE_URL="${DEEPSEEK_BASE_URL:-https://api.deepseek.com/v1}"
export OPENAI_MODEL_NAME="deepseek-chat"
export ANTARIKSH_MOCK_MODE="${ANTARIKSH_MOCK_MODE:-0}"

cd "$ANTARIKSH_DIR"

python3 -c "
import os, sys
sys.path.insert(0, '$ANTARIKSH_DIR')
from tools.orchestrator import handle_query
query = '''$QUERY'''
result = handle_query(query)
if result['status'] == 'ok':
    response = result.get('response', '')
    if isinstance(response, str) and len(response) > 3000:
        response = response[:3000] + '...(truncated)'
    print('— answered by Antariksh')
    print()
    print(response)
else:
    print('— answered by Antariksh')
    print()
    print(f'Error: {result.get(\"error\", \"Crew not responding\")}')
" 2>&1
