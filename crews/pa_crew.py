"""Post-Mortem Analyst Crew — 2-agent trade review + PM recommendations.

Agents: TradeReviewer, PatternAnalyst.
"""

import os, sys
from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config_loader import load_agent_config
from tools.pa_tools import (
    review_trade as _review_trade,
    run_counterfactuals as _run_counterfactuals,
    detect_patterns as _detect_patterns,
    generate_post_mortem_report as _generate_post_mortem_report,
    analyze_sl_optimization as _analyze_sl_optimization,
    analyze_entry_window as _analyze_entry_window,
    analyze_strategy_selection as _analyze_strategy_selection,
    write_trade_review_to_rag as _write_trade_review_to_rag,
    query_similar_trades_from_rag as _query_similar_trades_from_rag,
    load_portfolio_state as _load_portfolio_state,
    save_session_state as _save_session_state,
    generate_pa_recommendations as _generate_pa_recommendations,
)

manager_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.3,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)


@tool
def review_trade(trade: dict, spec: dict) -> dict:
    """Review trade quality and strategy fidelity. Returns quality score and issues."""
    return _review_trade(trade, spec)


@tool
def run_counterfactuals(
    trade: dict,
    peak_pnl: float = 0,
    better_exit: float = None,
    better_sl: float = None,
    better_tp: float = None,
    hypothetical_entry: float = None,
) -> dict:
    """Run what-if analysis: alternative entry, exit, SL, TP scenarios."""
    return _run_counterfactuals(
        trade, peak_pnl, better_exit, better_sl, better_tp, hypothetical_entry
    )


@tool
def detect_patterns(trades: list) -> dict:
    """Detect recurring patterns across trades."""
    return _detect_patterns(trades)


@tool
def generate_post_mortem_report(
    reviews: list, counterfactuals: list, patterns: dict, session: str
) -> dict:
    """Generate post-mortem report for PM with recommendations."""
    return _generate_post_mortem_report(reviews, counterfactuals, patterns, session)


@tool
def analyze_sl_optimization(
    trades: list, sl_range: tuple = None, step: int = 250
) -> dict:
    """Find optimal SL level. Simulates SL from ₹1,500-₹5,000. Returns best SL + PnL improvement."""
    kwargs = {"trades": trades, "step": step}
    if sl_range:
        kwargs["sl_range"] = sl_range
    return _analyze_sl_optimization(**kwargs)


@tool
def analyze_entry_window(trades: list) -> dict:
    """Find best 30-min entry window by win rate and avg PnL."""
    return _analyze_entry_window(trades)


@tool
def analyze_strategy_selection(
    trades: list, market_regime: str = "UNKNOWN", current_vix: float = 18.0
) -> dict:
    """Recommend strategy (Iron Fly vs Credit Spread) based on market regime + performance."""
    return _analyze_strategy_selection(trades, market_regime, current_vix)


@tool
def write_trade_review_to_rag(trade: dict, review: dict, market_regime: str = "UNKNOWN") -> dict:
    """Store trade review to ChromaDB for RAG learning."""
    return _write_trade_review_to_rag(trade, review, market_regime)


@tool
def query_similar_trades_from_rag(
    query_text: str, strategy_filter: str = None, n_results: int = 5
) -> dict:
    """Query similar past trades from ChromaDB RAG."""
    return _query_similar_trades_from_rag(query_text, strategy_filter, n_results=n_results)


@tool
def load_portfolio_state() -> dict:
    """Load current portfolio state (capital, margin, trades) from SQLite."""
    return _load_portfolio_state()


@tool
def save_session_state(
    portfolio_value: float = 100000.0,
    daily_pnl: float = 0.0,
    session_pnl: float = 0.0,
    margin_available: float = 200000.0,
    margin_used: float = 0.0,
) -> dict:
    """Save portfolio state to SQLite for next session."""
    return _save_session_state(
        portfolio_value, daily_pnl, session_pnl, margin_available, margin_used
    )


@tool
def generate_pa_recommendations(
    trades: list,
    total_margin_available: float = 0,
    total_margin_used: float = 0,
) -> dict:
    """Run ALL PA analyses and return ranked recommendations for PM. Use this as primary tool."""
    return _generate_pa_recommendations(
        trades, total_margin_available, total_margin_used
    )


reviewer = Agent(
    **load_agent_config("pa", "reviewer"),
    tools=[
        review_trade,
        run_counterfactuals,
        write_trade_review_to_rag,
        query_similar_trades_from_rag,
        load_portfolio_state,
        generate_pa_recommendations,
    ],
    allow_delegation=False,
    verbose=True,
)
analyst = Agent(
    **load_agent_config("pa", "analyst"),
    tools=[
        detect_patterns,
        generate_post_mortem_report,
        analyze_sl_optimization,
        analyze_entry_window,
        analyze_strategy_selection,
        save_session_state,
    ],
    allow_delegation=False,
    verbose=True,
)

review_task = Task(
    description="Review all session trades. Run counterfactuals for SL-hit trades.",
    expected_output="Review dicts + counterfactual dicts",
    agent=reviewer,
)
report_task = Task(
    description="Detect patterns. Generate post-mortem report with recommendations for PM.",
    expected_output="Post-mortem report dict",
    agent=analyst,
)


def build_pa_crew() -> Crew:
    return Crew(
        agents=[reviewer, analyst],
        tasks=[review_task, report_task],
        process=Process.hierarchical,
        manager_llm=manager_llm,
        verbose=True,
    )
