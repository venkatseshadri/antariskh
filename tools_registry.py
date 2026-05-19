#!/usr/bin/env python3
"""
Tools Registry — Central registry for all CrewAI tools.

Allows dynamic discovery and lookup of tools without circular imports.
Each tool is registered with metadata about its purpose and parameters.
"""

from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field


@dataclass
class ToolRegistry:
    """Central registry for tools."""

    tools: Dict[str, Callable] = field(default_factory=dict)
    metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def register(self, name: str, tool: Callable, **metadata):
        """Register a tool with optional metadata."""
        self.tools[name] = tool
        self.metadata[name] = metadata

    def get(self, name: str) -> Optional[Callable]:
        """Get a tool by name."""
        return self.tools.get(name)

    def get_all(self) -> Dict[str, Callable]:
        """Get all registered tools."""
        return self.tools.copy()

    def get_metadata(self, name: str) -> Dict[str, Any]:
        """Get metadata for a tool."""
        return self.metadata.get(name, {})

    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self.tools.keys())

    def __repr__(self) -> str:
        return f"ToolRegistry({list(self.tools.keys())})"


# Global registry instance
_global_registry = ToolRegistry()


def register_tool(name: str, tool: Callable, **metadata):
    """Register a tool globally."""
    _global_registry.register(name, tool, **metadata)


def get_tool(name: str) -> Optional[Callable]:
    """Get a tool from global registry."""
    return _global_registry.get(name)


def get_all_tools() -> Dict[str, Callable]:
    """Get all tools from global registry."""
    return _global_registry.get_all()


def list_tools() -> List[str]:
    """List all registered tools."""
    return _global_registry.list_tools()


def get_registry() -> ToolRegistry:
    """Get the global registry instance."""
    return _global_registry


# Pre-registered tools from trading_desk.py
def register_trading_desk_tools():
    """Register all trading desk tools (called on import)."""
    # Import here to avoid circular dependency
    try:
        from trading_desk import (
            scout_market_regime,
            research_setup,
            pm_approve,
            execute_orders,
            shifter_evaluate,
            researcher_backtest_shift,
            risk_direct_shift,
            order_agent_place_order,
            order_agent_modify_order,
            order_agent_cancel_order,
        )

        # Scout tools
        register_tool(
            "scout_market_regime",
            scout_market_regime,
            phase="preparation",
            agent="scout",
            description="Detect market regime (TRENDING_BULL/BEAR/SIDEWAYS)",
        )

        # Researcher tools
        register_tool(
            "research_setup",
            research_setup,
            phase="preparation",
            agent="researcher",
            description="Design strategy setup with Iron Butterfly configuration",
        )
        register_tool(
            "researcher_backtest_shift",
            researcher_backtest_shift,
            phase="maintenance",
            agent="researcher",
            description="Backtest leg shift proposal for validation",
        )

        # PM tools
        register_tool(
            "pm_approve",
            pm_approve,
            phase="validation",
            agent="pm",
            description="Validate capital requirements and authorize order",
        )

        # Executioner tools
        register_tool(
            "execute_orders",
            execute_orders,
            phase="action",
            agent="executioner",
            description="Execute authorized order (wings-first sequencing)",
        )

        # Risk Agent tools
        register_tool(
            "shifter_evaluate",
            shifter_evaluate,
            phase="maintenance",
            agent="risk",
            description="Evaluate leg shift conditions (theta decay, hedge decay)",
        )
        register_tool(
            "risk_direct_shift",
            risk_direct_shift,
            phase="maintenance",
            agent="risk",
            description="Direct Executioner to close/open legs for shift",
        )

        # Order Agent tools
        register_tool(
            "order_agent_place_order",
            order_agent_place_order,
            phase="all",
            agent="order_agent",
            description="Place order (PAPER ledger or LIVE broker)",
        )
        register_tool(
            "order_agent_modify_order",
            order_agent_modify_order,
            phase="all",
            agent="order_agent",
            description="Modify existing order (SL/TP update)",
        )
        register_tool(
            "order_agent_cancel_order",
            order_agent_cancel_order,
            phase="all",
            agent="order_agent",
            description="Cancel existing order",
        )

        return True
    except ImportError as e:
        print(f"Warning: Could not register trading desk tools: {e}")
        return False


if __name__ == "__main__":
    print("Tools Registry System")
    print("=" * 50)
    print(f"Registry: {get_registry()}")
    print("\nAvailable tools:")
    for tool_name in list_tools():
        tool = get_tool(tool_name)
        metadata = get_registry().get_metadata(tool_name)
        print(f"  - {tool_name:35s} : {metadata.get('description', 'N/A')}")
