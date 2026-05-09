#!/bin/bash
# Antariksh Trading Query Bridge for Picoclaw/Kubera
#
# Kubera calls this when user asks trading questions.
# Routes to correct crew via orchestrator + DeepSeek + Ralph Loop PRD check.
#
# Usage: ./antariskh_query.sh "how much margin is available?"

QUERY="$*"
ANTARIKSH_DIR="/home/trading_ceo/antariksh"

if [ -z "$QUERY" ]; then
    echo "Usage: antariskh_query.sh <your trading question>"
    exit 1
fi

cd "$ANTARIKSH_DIR"

# Pass query via environment to avoid shell quoting issues
export ANTARIKSH_QUERY="$QUERY"
export ANTARIKSH_MOCK_MODE="${ANTARIKSH_MOCK_MODE:-0}"

python3 -c "
import os, sys
sys.path.insert(0, '/home/trading_ceo/antariksh')
from tools.orchestrator import handle_query

query = os.environ.get('ANTARIKSH_QUERY', '')
result = handle_query(query)

if result['status'] == 'ok':
    response = result.get('response', '')
    if isinstance(response, str) and len(response) > 3000:
        response = response[:3000] + '...(truncated)'
    print(response)
else:
    print(f'Error: {result.get(\"error\", \"Unknown\")}')
" 2>&1
