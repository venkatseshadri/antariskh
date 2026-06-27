#!/bin/bash
# Delegate to the OUROBOROS canonical guard (root-owned, project-agnostic).
# Do NOT add project-specific logic here — put it in the canonical file.
exec /home/trading_ceo/ouroboros/ds_guard.sh "$@"
