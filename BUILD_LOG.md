Project Varaha — CrewAI Agent System Build Log
================================================================================
Generated: 2026-05-12
Root: /home/trading_ceo/antariksh
Broker SDK: /home/trading_ceo/python-trader

PHASE 1: Technical Scout (Market Regime Detection)
─────────────────────────────────────────────────────────────────

Change: Fixed "Tool Binding" issue — LLM ignored optional target_date.
Solution: Converted @tool → BaseTool subclass with Pydantic args_schema.

Files changed:
  crews/ta_crew.py
    - Added from pydantic import BaseModel, Field
    - Defined class MarketRegimeInput(BaseModel): target_date
    - Converted detect_market_regime() → class DetectMarketRegimeTool(BaseTool)
    - Removed duplicate detect_market_regime_date tool (merged into single tool)
    - Removed shadowing agent definitions (lines 170-194)
    - Set args_schema = MarketRegimeInput on the tool instance

  tests/test_technical_scout.py
    - Already injects exact date via datetime.now()-timedelta(1)
    - Added memory=False to Agent and Crew to suppress gpt-4o-mini errors
    - Cleaned up unused load_skill_file import

Verified:
  - Both tests pass: current regime + yesterday's regime
  - LLM correctly passes target_date='2026-05-10' to tool
  - gpt-4o-mini errors eliminated (memory=False on Crew)


PHASE 2: Strategy Architect (Options Spread Design)
─────────────────────────────────────────────────────────────────

Change: Built Quantitative Options Analyst with DuckDB tools + skill file.

Files created:
  tools/ta_strategy_tools.py (NEW)
    - class FetchOptionChainTool(BaseTool)  →  queries option_snapshots
    - class FetchGreeksTool(BaseTool)       →  queries market_data agg_delta/gamma/vega/theta
    - class MarketDataInput(BaseModel)      →  symbol: str = "NIFTY"
    - Uses BaseTool subclass for strict schema enforcement

  skills/strategy-architect.json (NEW)
    - strategy_definitions: credit_spreads, debit_spreads, iron_condor, iron_butterfly, ratio_spreads
    - decision_matrix: SIDEWAYS→IronCondor, CHOPPY→IronFly, TRENDING_BULL→PutCrSpread, TRENDING_BEAR→CallCrSpread
    - greek_and_strike_rules: 0.15 Delta Rule, Wing Width Sizing, Vega/VIX Check

  tests/test_strategy_architect.py (NEW)
    - TRENDING_BEAR → Bear Call Credit Spread E2E test

  tests/test_architect_iron_condor.py (NEW)
    - 7 theory tests: structure, risk, strategy identification, delta-neutral, asymmetric fly, unbalanced condor, calendar/theta

Files changed:
  crews/ta_crew.py
    + strategy_architect agent (6 tools: fetch_option_chain, fetch_greeks, 4 validation tools, load_skill_file)

Verified:
  - DuckDB hits return live data: option chain (12+ strikes) + greeks (Delta=0.16, Theta=-270)
  - Skill file correctly maps TRENDING_BEAR → Bear Call Credit Spread with 0.15 Delta rule
  - All 7 theory tests pass (agent loads skill file, uses only what's needed)


PHASE 3: Execution Specialist (Broker Order Placement)
─────────────────────────────────────────────────────────────────

Change: Built agent that translates leg-by-leg JSON into broker API calls.
Zero market-analysis tools. Wings-first sequencing.

Files created:
  tools/execution_tools.py (NEW)
    - class ExecuteTradeTool(BaseTool)     →  places multi-leg orders (SIM by default)
    - class GetOrderStatusTool(BaseTool)   →  queries order book
    - class GetPositionsTool(BaseTool)     →  queries open positions
    - exec_guardrail: validate_lot_sizes() →  blocks any leg > authorized_lots
    - Symbol generation: _build_tsym()     →  NIFTY14MAY202625000CE
    - Wings-first sequencing: BUY phase → 1.5s delay → SELL phase

  skills/executioner.json (NEW)
    - Categories: execution_sequencing, api_mapping, error_handling, execution_workflow
    - Rules: wing-first, never sell before buying, partial fills→report, rejections→halt

  tests/test_execution_specialist.py (NEW)
    - Iron Butterfly 4-leg paper trade test
    - Logs to simulated_trades.log

Files changed:
  crews/ta_crew.py
    + execution_specialist agent (4 tools: execute_broker_trade, get_order_status, get_open_positions, load_skill_file)

Verified:
  - Shoonya API connected successfully (creds found)
  - All 4 legs executed in SIMULATION mode
  - WING phase (BUY 24400PE + BUY 25600CE) → CENTER phase (SELL 25000PE + SELL 25000CE)
  - Lot-size guardrail blocks 5-lot request when authorized_lots=1
  - Trading symbols auto-generated correctly


PHASE 4: Contract Specialist (Symbol Resolution & Enrichment)
─────────────────────────────────────────────────────────────────

Change: Built "Librarian" that translates abstract strikes into exact trading symbols
with lot sizes, expiry dates, LTP, and margin estimates.

Files created:
  tools/contract_tools.py (NEW)
    - class ResolveContractTool(BaseTool)  →  SINGLE/PAIR/SPREAD resolution from DuckDB
    - class EnrichTradePlanTool(BaseTool)  →  enriches leg list with tsym, lot_size, per_lot_value
    - Shared utilities: get_weekly_expiry(), build_tsym(), get_lot_size()
    - Uses DuckDB option_snapshots to verify strikes exist in chain
    - FLAGS missing strikes (never fabricates)

  skills/librarian.json (NEW)
    - Categories: symbol_construction, instrument_matching, workflow, output_format, critical_rules
    - Rules: never guess symbols, flag missing strikes, expiry awareness (Thursday cutoff)

Files changed:
  crews/ta_crew.py
    + contract_specialist agent (3 tools: resolve_contract, enrich_trade_plan, load_skill_file)

Verified:
  - Spot=23810.3 → resolved ATM=23800 correctly (round(spot/50)*50)
  - ATM CE: NIFTY14MAY202623800CE  LTP=120.70  OI=3.29M  Lot=50
  - ATM PE: NIFTY14MAY202623800PE  LTP=74.95   OI=7.65M  Lot=50
  - Iron Condor enrichment: resolved 2 legs, flagged 2 missing (strike not in chain)
  - Net premium + margin estimate calculated for PM


COMPLETE AGENT ROSTER (crews/ta_crew.py)
─────────────────────────────────────────────────────────────────

 1. Technical Scout       →  detect_market_regime, load_skill_file
 2. Trade Validator       →  validate_trade, check_slippage, detect_duplicate
 3. Options Analyst       →  validate_strike_logic, validate_sl_vs_volatility,
                               generate_options_validation_report, load_skill_file
 4. Compliance Reporter   →  generate_compliance_report, generate_execution_ledger
 5. Strategy Architect    →  FetchOptionChainTool, FetchGreeksTool, 4 validation tools,
                               load_skill_file
 6. Contract Specialist   →  ResolveContractTool, EnrichTradePlanTool, load_skill_file
 7. Execution Specialist  →  ExecuteTradeTool, GetOrderStatusTool, GetPositionsTool,
                               load_skill_file


DATA PIPELINE (Assembly Line)
─────────────────────────────────────────────────────────────────

Technical Scout      →  "TRENDING_BEAR, ADX=41.2, SuperTrend=BEARISH, VIX=18.5"
       ↓
Strategy Architect   →  "Bear Call Credit Spread: SELL 24400CE, BUY 24600CE"
       ↓                  [queries DuckDB option_snapshots + market_data + skill file]
Contract Specialist  →  "SELL NIFTY14MAY202624400CE (1 lot=50u, LTP=₹X)"
                        "BUY  NIFTY14MAY202624600CE (1 lot=50u, LTP=₹Y)"
                        "Net Premium: ₹Z | Margin: ₹W"
       ↓                  [queries DuckDB option_snapshots, resolves symbols]
Portfolio Manager     →  [checks margin, approves/rejects]
       ↓
Execution Specialist  →  WING phase (BUY 24600CE) → 1.5s → CENTER phase (SELL 24400CE)
                        All SIMULATED SUCCESS. Order IDs reported. Guardrail: PASSED.
       ↓                  [Shoonya API integration, simulation mode]


SKILL FILES
─────────────────────────────────────────────────────────────────

  skills/technical-scout.json          Existing (ADX, SuperTrend, VIX, RSI, volume)
  skills/options-fundamentals.json     Existing (Greeks, Black-Scholes)
  skills/strategy-architect.json       NEW — 5 strategies + 4-regime decision matrix + 3 strike rules
  skills/executioner.json             NEW — execution sequencing + API mapping + error handling
  skills/librarian.json              NEW — symbol construction + lot-size validation + expiry logic


FILES INVENTORY
─────────────────────────────────────────────────────────────────

  tools/ta_tools.py                    (existing, modified: load_skill_file path)
  tools/ta_strategy_tools.py          NEW — FetchOptionChainTool + FetchGreeksTool
  tools/execution_tools.py            NEW — ExecuteTradeTool + GetOrderStatusTool + GetPositionsTool
  tools/contract_tools.py             NEW — ResolveContractTool + EnrichTradePlanTool
  skills/strategy-architect.json      NEW
  skills/executioner.json             NEW
  skills/librarian.json              NEW
  crews/ta_crew.py                    MODIFIED — 4 new agents + BaseTool conversions
  tests/test_technical_scout.py       MODIFIED — memory=False, clean imports
  tests/test_strategy_architect.py    NEW
  tests/test_architect_iron_condor.py NEW
  tests/test_execution_specialist.py  NEW
  tests/simulated_trades.log          NEW — paper trade audit trail


KNOWN ISSUES
─────────────────────────────────────────────────────────────────

 1. DuckDB lock conflict: When data_capture_v3_duckdb.py holds write lock,
    read-only queries can fail. Tools use copies for testing.
 2. gpt-4o-mini memory errors: Fixed by memory=False. For production,
    override memory_llm to use DeepSeek when memory=True.
 3. Scrip Master table: Not yet in DuckDB. Currently hardcoded lot sizes
    (NIFTY=50, SENSEX=10). See Phase 5 proposal below.


NEXT PHASE: Scrip Master in DuckDB
─────────────────────────────────────────────────────────────────

Goal: Eliminate hardcoded lot sizes by building a proper scrip_master
table in DuckDB. This enables:
  - Dynamic lot size lookup (SEBI updates)
  - Token-based order placement (token, not tsym)
  - Expiry calendar queries (weekly vs monthly)
  - Joins between scrip_master ↔ option_snapshots for delta→strike mapping

Proposed schema:

  CREATE TABLE IF NOT EXISTS scrip_master (
      token      VARCHAR PRIMARY KEY,
      tsym       VARCHAR NOT NULL,    -- 'NIFTY14MAY202625000CE'
      exch       VARCHAR NOT NULL,    -- 'NFO'
      symname    VARCHAR NOT NULL,    -- 'NIFTY'
      exd        DATE    NOT NULL,    -- expiry date
      strprc     DOUBLE  NOT NULL,    -- strike price
      optt       VARCHAR NOT NULL,    -- 'CE' or 'PE'
      ls         INTEGER NOT NULL,    -- lot size
      instrument VARCHAR NOT NULL,    -- 'OPTIDX' or 'OPTSTK'
      imported   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );

  CREATE INDEX idx_scrip_tsym ON scrip_master(tsym);
  CREATE INDEX idx_scrip_strprc ON scrip_master(symname, exd, strprc, optt);

Daily update:
  1. Download master .txt.zip from Shoonya at 8:00 AM
  2. read_csv_auto into DuckDB
  3. Replace/upsert existing records
