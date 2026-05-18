"""
Entry Crew — Traffic Light Agent (Multi-TF candle color patterns).

Analyzes candle GREEN/RED across 6 timeframes.
Detects: continuation, pullback, resumption, exhaustion, reversal.
Uses deterministic `query_traffic_light` tool from antariksh.tools.entry_tools.

Output: structured JSON {family, signal, score, confidence, reasoning, key_indicators}
"""

import os
import sys
import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

from tools.entry_tools import query_traffic_light as _query_traffic_light

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = LLM(
            model="deepseek/deepseek-chat",
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            temperature=0.3,
        )
    return _llm


@tool
def query_traffic_light_tool(index: str = "NIFTY") -> str:
    """
    Query multi-TF candle colors (GREEN/RED) and pattern detection.
    Returns JSON with per-TF candle data + pattern, exhaustion, reversal signals.
    Call this FIRST before producing your analysis JSON.
    """
    return _query_traffic_light(index)


_agent = None


def get_traffic_light_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent(
            role="Multi-TF Traffic Light Analyst",
            goal=(
                "Analyze candle colors (GREEN/RED) across 6 timeframes. "
                "Detect trend phases: continuation, pullback, resumption, exhaustion, reversal."
            ),
            backstory=(
                "You are the Traffic Light specialist — separate from the Trend agent. "
                "While Trend focuses on SMA/EMA structure, you focus on candle COLOR patterns.\n\n"
                "Each TF candle: GREEN = close > open (bullish), RED = close < open (bearish).\n\n"
                "KEY PATTERNS:\n"
                "- Daily GREEN + 1H RED + 5m/15m GREEN = pullback ending, momentum resuming. BULLISH.\n"
                "- Daily RED + 1H GREEN + lower TFs GREEN = dead-cat bounce in bear trend. BEARISH.\n"
                "- All 6 GREEN = momentum peak, exhaustion risk. NEUTRAL (do not chase).\n"
                "- All 6 RED = strong bear continuation. BEARISH.\n"
                "- Shifting from all-Green → mixed lower TFs = trend exhaustion / topping.\n"
                "- Shifting from all-Red → mixed lower TFs = bottoming / reversal signal.\n\n"
                "HIERARCHY: Daily > 4H > 1H > 30m > 15m > 5m.\n"
                "Higher TFs dominate direction. Lower TFs show short-term flow.\n\n"
                "SCORING:\n"
                "- Score = -10 (all red, strong bear) to +10 (pullback resuming, strong bull).\n"
                "- Confidence = match between given pattern and confidence from tool.\n"
                "- Signal = BULLISH if score > 3, BEARISH if score < -3, NEUTRAL otherwise.\n\n"
                "OUTPUT: You MUST output ONLY valid JSON:\n"
                '{"family":"TrafficLight","signal":"BULLISH|BEARISH|NEUTRAL","score":-10..10,"confidence":0..100,"reasoning":"brief","key_indicators":{"pattern":"...","story":"D=G|4H=R|...","exhaustion":false,"reversal_signal":false}}'
            ),
            tools=[query_traffic_light_tool],
            llm=_get_llm(),
            verbose=True,
            allow_delegation=False,
        )
    return _agent


def run_traffic_light_analysis(index: str = "NIFTY") -> dict:
    agent = get_traffic_light_agent()

    task = Task(
        description=(
            f"Analyze traffic light (candle colors) for {index} across all 6 timeframes. "
            "First call query_traffic_light_tool to get the data. "
            "Then produce the final structured JSON analysis. "
            "Output ONLY the JSON — no markdown, no commentary."
        ),
        expected_output=(
            "JSON object with family, signal, score, confidence, reasoning, key_indicators"
        ),
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()

    try:
        raw = str(result)
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:]) if len(lines) > 1 else raw
            if raw.endswith("```"):
                raw = raw[:-3]
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {
            "family": "TrafficLight",
            "signal": "NEUTRAL",
            "score": 0,
            "confidence": 0,
            "reasoning": f"Parse error: {str(result)[:200]}",
            "key_indicators": {},
            "raw": str(result),
        }


if __name__ == "__main__":
    idx = sys.argv[1] if len(sys.argv) > 1 else "NIFTY"
    print(json.dumps(run_traffic_light_analysis(idx), indent=2))
