#!/usr/bin/env python3
"""
Agent Registry — Central registry for all CrewAI agents.

Allows dynamic discovery and lookup of agents without circular imports.
Each agent is registered with metadata about its role and responsibilities.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field


@dataclass
class AgentRegistry:
    """Central registry for agents."""

    agents: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def register(self, name: str, agent: Any, **metadata):
        """Register an agent with optional metadata."""
        self.agents[name] = agent
        self.metadata[name] = metadata

    def get(self, name: str) -> Optional[Any]:
        """Get an agent by name."""
        return self.agents.get(name)

    def get_all(self) -> Dict[str, Any]:
        """Get all registered agents."""
        return self.agents.copy()

    def get_metadata(self, name: str) -> Dict[str, str]:
        """Get metadata for an agent."""
        return self.metadata.get(name, {})

    def list_agents(self) -> List[str]:
        """List all registered agent names."""
        return list(self.agents.keys())

    def __repr__(self) -> str:
        return f"AgentRegistry({list(self.agents.keys())})"


# Global registry instance
_global_registry = AgentRegistry()


def register_agent(name: str, agent: Any, **metadata):
    """Register an agent globally."""
    _global_registry.register(name, agent, **metadata)


def get_agent(name: str) -> Optional[Any]:
    """Get an agent from global registry."""
    return _global_registry.get(name)


def get_all_agents() -> Dict[str, Any]:
    """Get all agents from global registry."""
    return _global_registry.get_all()


def list_agents() -> List[str]:
    """List all registered agents."""
    return _global_registry.list_agents()


def get_registry() -> AgentRegistry:
    """Get the global registry instance."""
    return _global_registry


# Pre-registered agents from trading_desk.py
def register_trading_desk_agents():
    """Register all trading desk agents (called on import)."""
    # Import here to avoid circular dependency
    try:
        from trading_desk import (
            scout_agent,
            researcher_agent,
            pm_agent,
            executioner_agent,
            risk_agent,
            shifter_agent,
            order_agent,
        )

        register_agent("scout", scout_agent, role="Technical Scout (Market Eyes)")
        register_agent("researcher", researcher_agent, role="Strategy Researcher")
        register_agent("pm", pm_agent, role="Portfolio Manager")
        register_agent("executioner", executioner_agent, role="Execution Specialist")
        register_agent("risk", risk_agent, role="Risk & Compliance Sentry")
        register_agent("shifter", shifter_agent, role="Leg Shifter (Theta Optimizer)")
        register_agent("order_agent", order_agent, role="Order Agent (Order Router)")

        return True
    except ImportError:
        return False


if __name__ == "__main__":
    print("Agent Registry System")
    print("=" * 50)
    print(f"Registry: {get_registry()}")
    print("\nAvailable agents:")
    for agent_name in list_agents():
        agent = get_agent(agent_name)
        metadata = get_registry().get_metadata(agent_name)
        print(f"  - {agent_name:20s} : {metadata.get('role', 'N/A')}")
