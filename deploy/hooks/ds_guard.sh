#!/bin/bash
# DS guardrail — Board order 2026-06-11 (see docs/DAMBUILDER_STATE.md §0e).
# Executed by .git/hooks/pre-commit in antariksh AND brahmand.
#
# ONE mechanical guard: validator/Board lines in docs are append-only.
# DS builds and deploys at full speed, any time, including market hours
# (Board-authorized). The only thing it may never do is rewrite the trust
# record — validator verdicts and Board decisions.
# Override: VALIDATOR_OVERRIDE=1 (validator/Board only).

set -u

PROTECTED_LINE_RE='✅✅|VALIDATOR|Validator record|Board decision|Board order'

if [ -z "${VALIDATOR_OVERRIDE:-}" ]; then
    deleted=$(git diff --cached -U0 -- '*.md' | grep '^-' | grep -vE '^---' | grep -E "$PROTECTED_LINE_RE" || true)
    if [ -n "$deleted" ]; then
        echo "[ds-guard] BLOCKED: staged deletion of validator/Board lines (append-only)."
        echo "$deleted" | head -5 | sed 's/^/[ds-guard]   /'
        echo "[ds-guard] Board order 2026-06-11: only the validator/Board edits these lines."
        echo "[ds-guard] Disagree with a verdict? Append your evidence below it — never delete."
        exit 1
    fi
fi

exit 0
