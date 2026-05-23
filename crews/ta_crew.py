"""Trading Analyst Crew — 4-agent trade validation (Varaha model: Scout → Execution → Analyst → Reporter).

import os
import sys
from typing import Type
from pydantic import BaseModel, Field
from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import BaseTool, tool
from config_loader import load_agent_config
from tools.ta_tools import (
    detect_market_regime as _detect_market_regime,
    load_skill_file as _load_skill_file,
    validate_trade as _validate_trade,
    check_slippage as _check_slippage,
    detect_duplicate as _detect_duplicate,
    validate_strike_logic as _validate_strike_logic,
    validate_sl_vs_volatility as _validate_sl_vs_volatility,
    generate_options_validation_report as _generate_options_validation_report,
    generate_compliance_report as _generate_compliance_report,
    generate_execution_ledger as _generate_execution_ledger,
)
from tools.ta_strategy_tools import FetchOptionChainTool, FetchGreeksTool
from tools.execution_tools import (
    ExecuteTradeTool,
    GetOrderStatusTool,
    GetPositionsTool,
    ModifyOrderTool,
    CancelOrderTool,
)
from tools.contract_tools import (
    ResolveContractTool,
    EnrichTradePlanTool,
    LibrarianContractTool,
)
from tools.risk_tools import (
    MonitorPnLGreeksTool,
    TSLEngineTool,
    TradeCommandHandlerTool,
    WebSocketSubscriptionTool,
)
from dotenv import load_dotenv
load_dotenv()


Agents:
  - Technical Scout: market regime from DuckDB (ADX, SuperTrend, VIX)
  - Trade Execution Validator: spec conformance, slippage, duplicates
  - Quantitative Options Analyst: Greeks, strikes, SL vs volatility
  - Compliance Reporter: PM + AM reports

Uses CrewAI Process.hierarchical. Deterministic tools from tools/ta_tools.py.
"""



sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
manager_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=DEEPSEEK_BASE,
    temperature=0.3,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)


# ============================================================
# Tools (CrewAI-wrapped)
# ============================================================


class MarketRegimeInput(BaseModel):
    target_date: str = Field(
        default=None,
        description="CRITICAL: If the user asks for historical data (like 'yesterday'), you MUST provide the date in 'YYYY-MM-DD' format here. Leave empty ONLY for current live data.",
    )


class DetectMarketRegimeTool(BaseTool):
    name: str = "detect_market_regime"
    description: str = (
        "Get CURRENT or HISTORICAL market regime from DuckDB (ADX, SuperTrend, VIX).\n\n"
        "If you need data for a specific past date (e.g., 'yesterday'), you MUST pass "
        "the target_date argument in 'YYYY-MM-DD' format. Omit target_date ONLY for "
        "the latest live market data.\n\n"
        "Use for: 'how is the market?', 'current regime?', 'what was yesterday?', "
        "'what was the regime on 2026-05-04?'"
    )
    args_schema: Type[BaseModel] = MarketRegimeInput

    def _run(self, target_date: str = None) -> dict:
        return _detect_market_regime(target_date=target_date)


detect_market_regime = DetectMarketRegimeTool()


@tool
def load_skill_file(skill_file: str) -> dict:
    """Load knowledge from skills/ directory (technical-scout.json or options-fundamentals.json)."""
    return _load_skill_file(skill_file)


@tool
def validate_trade(spec: dict, trade: dict) -> dict:
    """Validate trade execution against PM strategy spec. Returns valid flag and violations."""
    return _validate_trade(spec, trade)


@tool
def check_slippage(
    expected_strike: float, actual_fill: float, tolerance: float = 50
) -> dict:
    """Check order fill slippage against tolerance in points."""
    return _check_slippage(expected_strike, actual_fill, tolerance)


@tool
def detect_duplicate(trade: dict, session_trades: list) -> dict:
    """Check if trade duplicates an existing one in the session."""
    return _detect_duplicate(trade, session_trades)


@tool
def validate_strike_logic(spec: dict, vix: float, nifty_spot: float) -> dict:
    """Validate strikes make market sense: ATM grid, wing width vs VIX."""
    return _validate_strike_logic(spec, vix, nifty_spot)


@tool
def validate_sl_vs_volatility(spec: dict, vix: float, nifty_spot: float) -> dict:
    """Validate SL is adequate for current volatility."""
    return _validate_sl_vs_volatility(spec, vix, nifty_spot)


@tool
def generate_options_validation_report(
    spec: dict, vix: float, nifty_spot: float
) -> dict:
    """Run all options market validations and produce a combined report."""
    return _generate_options_validation_report(spec, vix, nifty_spot)


@tool
def generate_compliance_report(trade_id: str, spec: dict, violations: list) -> dict:
    """Generate compliance report for PM with accuracy score and violations."""
    return _generate_compliance_report(trade_id, spec, violations)


@tool
def generate_execution_ledger(trades: list, session: str) -> dict:
    """Generate P&L + broker + fees ledger for Asset Manager."""
    return _generate_execution_ledger(trades, session)


# ============================================================
# Agents (Varaha model: Scout → Analyst → Guardian → Execution)
# ============================================================

scout_tools = [detect_market_regime, load_skill_file]

technical_scout = Agent(
    **load_agent_config("ta", "technical_scout"),
    tools=scout_tools,
    allow_delegation=False,
    verbose=True,
    memory=True,
)

trade_validator = Agent(
    **load_agent_config("ta", "trade_validator"),
    tools=[validate_trade, check_slippage, detect_duplicate],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

options_analyst = Agent(
    **load_agent_config("ta", "options_analyst"),
    tools=[
        validate_strike_logic,
        validate_sl_vs_volatility,
        generate_options_validation_report,
        load_skill_file,
    ],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

compliance_reporter = Agent(
    **load_agent_config("ta", "compliance_reporter"),
    tools=[generate_compliance_report, generate_execution_ledger],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

# Strategy Architect — Quantitative Options Analyst with DuckDB tools
fetch_option_chain = FetchOptionChainTool()
fetch_greeks = FetchGreeksTool()

strategy_architect = Agent(
    role="Quantitative Options Analyst (NFO Segment)",
    goal=(
        "Design mathematically optimal options strategies (e.g., Iron Condors, "
        "Credit Spreads) based on the Technical Scout's market regime. Output a "
        "strict JSON trade plan detailing the exact legs, strikes, and actions."
    ),
    backstory=(
        "You are a cold, highly disciplined Dalal Street quantitative analyst. "
        "You never guess. You take the 'Regime' provided by the Technical Scout, "
        "use your DuckDB tools to check the Option Chain and Aggregate Greeks, and "
        "select the precise strikes for the trade. You evaluate risk aggressively and "
        "always ensure protective 'wings' are defined for any spread."
    ),
    tools=[
        fetch_option_chain,
        fetch_greeks,
        validate_strike_logic,
        validate_sl_vs_volatility,
        generate_options_validation_report,
        load_skill_file,
    ],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

# Execution Specialist — zero market-analysis tools, broker API only
execute_trade = ExecuteTradeTool()
get_status = GetOrderStatusTool()
get_positions = GetPositionsTool()
modify_order_tool = ModifyOrderTool()
cancel_order_tool = CancelOrderTool()

execution_specialist = Agent(
    role="Execution Specialist (NFO Segment)",
    goal=(
        "Execute, modify, and cancel orders precisely as commanded by the Risk Sentry. "
        "Receive trade commands and translate them into broker API calls with zero delay. "
        "Report order status back to keep the Risk Sentry in sync."
    ),
    backstory=(
        "You are the HANDS of the firm — a high-speed order management engine. "
        "You receive COMMANDS from the Risk Sentry (trade_command) and execute instantly:\n"
        "- execute_broker_trade for entry and exit.\n"
        "- execute_modify_order for TSL adjustments.\n"
        "- cancel_order for SL/TP lifecycle management (TP filled → cancel SL, SL filled → cancel TP).\n"
        "You NEVER decide when to cancel or modify — the Risk Sentry commands, you obey.\n"
        "You call get_order_status after every action to confirm state and report back."
    ),
    tools=[
        execute_trade,
        get_status,
        get_positions,
        modify_order_tool,
        cancel_order_tool,
        load_skill_file,
    ],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

# Contract Specialist — Symbol resolution, lot sizes, expiry mapping
resolve_contract = ResolveContractTool()
enrich_plan = EnrichTradePlanTool()
librarian_lookup = LibrarianContractTool()

contract_specialist = Agent(
    role="Market Data Librarian (NFO Specialist)",
    goal=(
        "Translate theoretical strikes and option types into exact, tradeable "
        "broker tokens, trading symbols, and lot sizes. Provide PM-ready "
        "enriched trade plans with all contract metadata."
    ),
    backstory=(
        "You are the master of the Scrip Master — the firm's data librarian. "
        "You do NOT analyze trends or evaluate strategies. "
        "Your ONLY job is to take index names, strikes, and option types "
        "and return the physical contract details: Token, Trading Symbol, Lot Size, "
        "Expiry Date. "
        "You use contract_librarian_lookup for single-contract resolution "
        "and enrich_trade_plan for full multi-leg plan enrichment. "
        "You ALWAYS query the lock-free data cache (ATTACH pattern) — "
        "never a raw API call. "
        "If a token is 0 or Null, you REJECT the trade plan. "
        "You are the single source of truth between the Architect's theory "
        "and the Portfolio Manager's reality."
    ),
    tools=[librarian_lookup, resolve_contract, enrich_plan, load_skill_file],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

# Risk & Compliance Sentry — COMMANDS the Executioner, never touches the API directly
monitor_pnl = MonitorPnLGreeksTool()
tsl_calc = TSLEngineTool()
trade_cmd = TradeCommandHandlerTool()
ws_monitor = WebSocketSubscriptionTool()

risk_sentry = Agent(
    role="Risk & Compliance Sentry (The Commander)",
    goal=(
        "Monitor live positions via WebSocket ticks and ISSUE COMMANDS "
        "(not recommendations) to the Execution Specialist. Command EXIT "
        "when SL/TSL/TP breached. Command MODIFY when TSL needs updating."
    ),
    backstory=(
        "You are the COMMANDER — the BRAIN of the live trade. "
        "You NEVER call broker APIs directly. You issue COMMANDS via trade_command "
        "and the Execution Specialist executes them. "
        "You subscribe to live ticks via live_risk_monitor (WebSocket). "
        "You monitor MTM P&L + Greeks every cycle via monitor_pnl_greeks. "
        "You calculate SL/TP/TSL levels via tsl_engine. "
        "When tsl_engine returns EXIT_*: issue trade_command(command_type='EXIT'). "
        "When tsl_engine returns TRAIL with new tsl_level: issue "
        "trade_command(command_type='MODIFY', order_id=..., new_trigger_price=...). "
        "The Executioner receives your commands and executes them via "
        "execute_broker_trade (for EXIT) or execute_modify_order (for MODIFY). "
        "You command. They execute. Zero latency. Zero double-check delays."
    ),
    tools=[monitor_pnl, tsl_calc, trade_cmd, ws_monitor, load_skill_file],
    allow_delegation=False,
    verbose=True,
    memory=True,
)


# ============================================================
# Tasks
# ============================================================

scout_task = Task(
    description=(
        "Detect the market regime from live DuckDB data before any analysis begins:\n"
        "1. Call detect_market_regime() — reads ADX + SuperTrend + VIX from DuckDB\n"
        "2. Determine regime: TRENDING_BULL, TRENDING_BEAR, or SIDEWAYS\n"
        "3. Report suitable strategies for current regime\n"
        "4. If DuckDB is stale/unavailable, report exactly that — never fabricate\n\n"
        "This is the FIRST step. The Analyst cannot design a strategy until "
        "you tell them what kind of market this is."
    ),
    expected_output="Market regime dict with ADX, SuperTrend, VIX, regime, suitable_strategies",
    agent=technical_scout,
)

validation_task = Task(
    description=(
        "For each trade executed, validate against PM spec:\n"
        "1. Type matches (IRON_FLY vs CREDIT_SPREAD)\n"
        "2. Strike prices match exactly\n"
        "3. Wing width matches\n"
        "4. Lot count matches\n"
        "5. SL placement matches\n"
        "6. TSL configuration matches\n"
        "7. Broker matches\n"
        "8. Slippage check on each fill\n"
        "9. Duplicate detection (same type + strikes + lots in session)\n\n"
        "Return structured results with violations list, slippage results, "
        "and duplicate flag."
    ),
    expected_output=(
        "A dict with: valid (bool), violations (list), "
        "slippage_results (list), duplicate (bool)"
    ),
    agent=trade_validator,
)

options_task = Task(
    description=(
        "Validate the trade PLAN against options market reality:\n"
        "1. Check strikes are on the 50-pt grid and make sense for spot\n"
        "2. Verify wing width is adequate for current VIX\n"
        "3. Validate SL covers at least 1.5x expected daily range\n"
        "4. Check TSL distance against daily range\n"
        "5. Run generate_options_validation_report() for combined verdict\n\n"
        "This is MARKET validation, not execution validation. You check "
        "if the plan itself makes sense given current volatility."
    ),
    expected_output="Options market validation dict with strike logic + SL volatility checks",
    agent=options_analyst,
)

report_task = Task(
    description=(
        "Take the validation results and generate:\n"
        "1. Compliance report for PM — accuracy %, violations with "
        "expected/actual/severity, trade ID\n"
        "2. Execution ledger for AM — session P&L, fees, slippage, "
        "broker per-trade breakdown\n\n"
        "Both reports must use concrete data from tools, not LLM synthesis."
    ),
    expected_output=(
        "Compliance report (dict) + execution ledger (dict) "
        "ready for routing to PM and AM"
    ),
    agent=compliance_reporter,
)


# ============================================================
# Crew Builder
# ============================================================


def build_ta_crew() -> Crew:
    """Build TA crew with 4 agents in hierarchical process.

    Varaha model: Scout → Analyst → Guardian → Execution.
    """
    return Crew(
        agents=[technical_scout, trade_validator, options_analyst, compliance_reporter],
        tasks=[scout_task, validation_task, options_task, report_task],
        process=Process.hierarchical,
        manager_llm=manager_llm,
        verbose=True,
    )


if __name__ == "__main__":
    crew = build_ta_crew()
    print(
        f"TA Crew: {len(crew.agents)} agents, {len(crew.tasks)} tasks, process={crew.process}"
    )
