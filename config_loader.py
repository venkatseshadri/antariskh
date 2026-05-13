"""Agent config loader — single source of truth for all agent identities.

Usage in any crew file:
    from config_loader import load_agent_config
    cfg = load_agent_config("ta", "trade_validator")
    agent = Agent(role=cfg["role"], goal=cfg["goal"], backstory=cfg["backstory"], tools=[...])

Or load the whole crew:
    crew_cfg = load_crew_config("ta")
    # {"trade_validator": {role, goal, backstory}, "compliance_reporter": {role, goal, backstory}}
"""

import json
import os
from pathlib import Path
from typing import Dict

_CONFIG_CACHE: Dict = {}
_CONFIG_PATH = Path(__file__).parent / "config" / "agents.json"


def _load_config() -> Dict:
    """Load agents.json once, cache it."""
    global _CONFIG_CACHE
    if not _CONFIG_CACHE:
        if not _CONFIG_PATH.exists():
            raise FileNotFoundError(f"Agent config not found: {_CONFIG_PATH}")
        _CONFIG_CACHE = json.loads(_CONFIG_PATH.read_text())
    return _CONFIG_CACHE


def load_agent_config(crew: str, agent_id: str) -> Dict[str, str]:
    """Load role/goal/backstory for a single agent.

    Args:
        crew: Crew name matching key in agents.json (e.g., 'ta', 'pm', 'cto')
        agent_id: Agent key within the crew (e.g., 'trade_validator', 'strategist')

    Returns:
        {"role": "...", "goal": "...", "backstory": "..."}
    """
    cfg = _load_config()
    crew_cfg = cfg.get(crew)
    if crew_cfg is None:
        raise KeyError(f"Crew '{crew}' not found. Available: {list(cfg.keys())}")
    agent_cfg = crew_cfg.get(agent_id)
    if agent_cfg is None:
        raise KeyError(
            f"Agent '{agent_id}' not found in crew '{crew}'. Available: {list(crew_cfg.keys())}"
        )
    return agent_cfg


def load_crew_config(crew: str) -> Dict[str, Dict[str, str]]:
    """Load all agent configs for a crew.

    Returns:
        {agent_id: {role, goal, backstory}, ...}
    """
    cfg = _load_config()
    crew_cfg = cfg.get(crew)
    if crew_cfg is None:
        raise KeyError(f"Crew '{crew}' not found. Available: {list(cfg.keys())}")
    return crew_cfg
