"""
Entry Crew — Trend Agent (Family 1 of 7).

Analyzes EMA/SMA alignment + SuperTrend across 6 timeframes.
Uses deterministic `query_trend` tool from antariksh.tools.entry_tools.

Output: structured JSON {family, signal, score, confidence, reasoning, key_indicators}

Usage:
    python -m agents.entry.trend_agent --mock
    python -m agents.entry.trend_agent
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

from tools.entry_tools import query_trend as _query_trend

# ============================================================
# LLM Config
# ============================================================

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


# ============================================================
# Tool — CrewAI-wrapped trend query
# ============================================================


@tool
def query_trend_tool(index: str = "NIFTY") -> str:
    """
    Query multi-timeframe trend data: SMA20/50, SuperTrend, ADX per TF.
    Returns JSON with per-timeframe trend positioning.
    Call this FIRST before producing your analysis JSON.
    """
    return _query_trend(index)


# ============================================================
# Agent
# ============================================================

_agent = None


def get_trend_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent(
            role="Trend Family Analyst",
            goal=(
                "Analyze EMA/SMA alignment and SuperTrend across 6 timeframes "
                "(5m/15m/30m/60m/240m/1440m). Determine if trend supports bullish, "
                "bearish, or neutral entry for option selling."
            ),
            backstory=(
                "You are the Trend specialist in the 7-family entry crew. "
                "You call query_trend_tool which returns SMA20/50 positioning, "
                "candle colors, and SuperTrend consensus per timeframe.\n\n"
                "RULES:\n"
                "- SMA20 > SMA50 across most TFs = bullish trend.\n"
                "- SMA20 < SMA50 = bearish trend.\n"
                "- Mixed across TFs = neutral/choppy.\n"
                "- SuperTrend consensus confirms or weakens your signal.\n"
                "- ADX > 25 on key TFs (1h, 4h) adds confidence.\n"
                "- Higher TFs (1h, 4h, daily) carry MORE weight than lower TFs (5m, 15m).\n\n"
                "TRAFFIC LIGHT (candle color per TF):\n"
                "- GREEN = close > open (bullish candle). RED = close < open (bearish candle).\n"
                "- Daily candle dominates the day's direction.\n"
                "- 4H/1H candles show intermediate momentum.\n"
                "- Lower TF candles (5m, 15m, 30m) show short-term flow.\n"
                "- Daily GREEN + 4H RED + 1H/30m GREEN = bullish day with pullback resuming.\n"
                "- Daily GREEN + 1H RED = intraday pullback in bull trend (common, low concern).\n"
                "- Daily RED + lower TFs GREEN = dead-cat bounce in bear trend (sceptical).\n"
                "- Use the traffic_light.story field for rapid interpretation.\n"
                "- traffic_light.pullback and traffic_light.resuming tell you phase.\n\n"
                "SCORING:\n"
                "- Score = -10 (all TFs bearish, ST bearish, daily RED) to +10 (all TFs bullish, ST bullish, daily GREEN).\n"
                "- Confidence = 0-100 based on TF alignment %. 100% alignment = 100 confidence.\n"
                "- Signal = BULLISH if score > 3, BEARISH if score < -3, NEUTRAL otherwise.\n\n"
                "OUTPUT: You MUST output ONLY valid JSON with this exact structure:\n"
                '{"family":"Trend","signal":"BULLISH|BEARISH|NEUTRAL","score":-10..10,"confidence":0..100,"reasoning":"brief explanation","key_indicators":{"aligned_tfs":"4/6","dominant_tf":"daily","st_consensus":"BULLISH","adx_1h":28.5,"traffic_light":"Daily=GREEN | 4H=RED | 1H=GREEN | ..."}}'
            ),
            tools=[query_trend_tool],
            llm=_get_llm(),
            verbose=True,
            allow_delegation=False,
        )
    return _agent


# ============================================================
# Crew
# ============================================================


def run_trend_analysis(index: str = "NIFTY") -> dict:
    """
    Run the Trend agent standalone. Returns parsed analysis dict.
    """
    agent = get_trend_agent()

    task = Task(
        description=(
            f"Analyze trend for {index} index across all timeframes. "
            "First call query_trend_tool to get the data. "
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
    logger = logging.getLogger("TrendAgent")
    logger.info(f"Raw result: {result}")

    # Parse the result — CrewAI returns a string
    try:
        raw = str(result)
        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:]) if len(lines) > 1 else raw
            if raw.endswith("```"):
                raw = raw[:-3]
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {
            "family": "Trend",
            "signal": "NEUTRAL",
            "score": 0,
            "confidence": 0,
            "reasoning": f"Failed to parse agent output: {str(result)[:200]}",
            "key_indicators": {},
            "raw": str(result),
        }


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    idx = sys.argv[1] if len(sys.argv) > 1 else "NIFTY"
    print(json.dumps(run_trend_analysis(idx), indent=2))
