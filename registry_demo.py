#!/usr/bin/env python3
"""
Registry Demo — Shows how to use agent and tools registries.

Demonstrates:
1. Dynamic agent discovery
2. Dynamic tool discovery
3. Getting agent/tool metadata
4. Calling tools from registry
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Suppress verbose logging during import
os.environ["LOG_LEVEL"] = "WARNING"

from agent_registry import list_agents, get_agent, get_registry as get_agent_registry
from agent_registry import register_trading_desk_agents
from tools_registry import list_tools, get_tool, get_registry as get_tools_registry
from tools_registry import register_trading_desk_tools

# Explicitly register all agents and tools
print("[INFO] Registering agents and tools...")
register_trading_desk_agents()
register_trading_desk_tools()
print("[INFO] Registration complete")


def demo_agent_registry():
    """Demonstrate agent registry usage."""
    print("\n" + "=" * 70)
    print("AGENT REGISTRY DEMO")
    print("=" * 70)

    print("\n1. List all registered agents:")
    for agent_name in list_agents():
        agent = get_agent(agent_name)
        metadata = get_agent_registry().get_metadata(agent_name)
        print(f"   • {agent_name:20s} : {metadata.get('role', 'N/A')}")

    print("\n2. Get a specific agent:")
    order_agent = get_agent("order_agent")
    if order_agent:
        print(f"   Order Agent found: {order_agent.role}")
        print(f"   Tools: {[str(t) for t in order_agent.tools][:3]}...")  # First 3 tools
    else:
        print("   Order Agent not found")

    print("\n3. Query agent metadata:")
    for agent_name in ["scout", "risk", "order_agent"]:
        metadata = get_agent_registry().get_metadata(agent_name)
        print(f"   • {agent_name}: {metadata}")


def demo_tools_registry():
    """Demonstrate tools registry usage."""
    print("\n" + "=" * 70)
    print("TOOLS REGISTRY DEMO")
    print("=" * 70)

    print("\n1. List all registered tools:")
    for tool_name in list_tools():
        tool = get_tool(tool_name)
        metadata = get_tools_registry().get_metadata(tool_name)
        agent = metadata.get("agent", "N/A")
        description = metadata.get("description", "N/A")
        print(f"   • {tool_name:35s} [{agent:15s}] {description}")

    print("\n2. Get tools by phase:")
    phases = {}
    for tool_name in list_tools():
        metadata = get_tools_registry().get_metadata(tool_name)
        phase = metadata.get("phase", "unknown")
        if phase not in phases:
            phases[phase] = []
        phases[phase].append(tool_name)

    for phase, tools in sorted(phases.items()):
        print(f"   • {phase:15s}: {', '.join(tools)}")

    print("\n3. Get tools by agent:")
    agents = {}
    for tool_name in list_tools():
        metadata = get_tools_registry().get_metadata(tool_name)
        agent = metadata.get("agent", "unknown")
        if agent not in agents:
            agents[agent] = []
        agents[agent].append(tool_name)

    for agent_name, tools in sorted(agents.items()):
        print(f"   • {agent_name:15s}: {', '.join(tools)}")

    print("\n4. Get specific tool:")
    order_place_tool = get_tool("order_agent_place_order")
    if order_place_tool:
        metadata = get_tools_registry().get_metadata("order_agent_place_order")
        print(f"   Tool: order_agent_place_order")
        print(f"   Agent: {metadata.get('agent')}")
        print(f"   Phase: {metadata.get('phase')}")
        print(f"   Description: {metadata.get('description')}")
    else:
        print("   Tool not found")


def demo_dynamic_discovery():
    """Demonstrate dynamic agent/tool discovery."""
    print("\n" + "=" * 70)
    print("DYNAMIC DISCOVERY DEMO")
    print("=" * 70)

    print("\n1. Find all agents for maintenance phase:")
    maintenance_agents = []
    for agent_name in list_agents():
        # In a real system, you'd store phase info in agent metadata
        if agent_name in ["risk", "shifter", "order_agent"]:
            maintenance_agents.append(agent_name)
    print(f"   Maintenance agents: {maintenance_agents}")

    print("\n2. Find all tools for order routing:")
    order_tools = [tool for tool in list_tools() if "order_agent" in tool]
    print(f"   Order Agent tools: {order_tools}")

    print("\n3. Build agent-tool map:")
    agent_tool_map = {}
    for tool_name in list_tools():
        metadata = get_tools_registry().get_metadata(tool_name)
        agent = metadata.get("agent", "unknown")
        if agent not in agent_tool_map:
            agent_tool_map[agent] = []
        agent_tool_map[agent].append(tool_name)

    print("   Agent → Tools mapping:")
    for agent, tools in sorted(agent_tool_map.items()):
        print(f"      {agent:20s}: {len(tools)} tools")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("ANTARIKSH REGISTRY SYSTEM — DEMONSTRATION")
    print("=" * 70)

    demo_agent_registry()
    demo_tools_registry()
    demo_dynamic_discovery()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total agents registered: {len(list_agents())}")
    print(f"Total tools registered: {len(list_tools())}")
    print("\nUse these registries to:")
    print("  • Discover agents and tools dynamically")
    print("  • Build agent-tool mappings")
    print("  • Query metadata (role, phase, description)")
    print("  • Route orders through the Order Agent")
    print("  • Maintain audit trail of all operations")
    print()
