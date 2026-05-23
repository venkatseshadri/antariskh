"""Entry Agent Crew — Deterministic entry gate (Trend + Traffic Light)."""

import sys
from pathlib import Path
import os

# Fix sys.path FIRST so entry_check can import tools
# This must happen before importing entry_check
PROJECT_ROOT = Path(__file__).parent.parent.parent
for path_to_add in [str(PROJECT_ROOT), str(PROJECT_ROOT.parent / "python-trader"), str(PROJECT_ROOT.parent / "brahmand")]:
    if path_to_add not in sys.path:
        sys.path.insert(0, path_to_add)

from .entry_check import check_entry

__all__ = ["check_entry"]
