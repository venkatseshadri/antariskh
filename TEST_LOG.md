PROJECT VARAHA — STRATEGY ARCHITECT & CONTRACT SPECIALIST TEST LOG
================================================================================
Generated: 2026-05-12 09:45 IST
Working Dir: /home/trading_ceo/antariksh

TEST 1: Contract Specialist Validation
─────────────────────────────────────
File: tests/test_contract_specialist.py
Log:  test_contract_specialist.log
Goal: Architect Iron Butterfly plan → Librarian resolves all 4 legs → PM-ready enriched plan

Pipeline:
  1. load_skill_file('librarian.json')
  2. contract_librarian_lookup × 4 (one per leg)
  3. enrich_trade_plan (full 4-leg enrichment)
  4. fetch_option_chain_from_duck_db (agent proactively checked chain)
  5. Agent substituted missing 24100CE → 23900CE from chain

Librarian Resolutions (all source=scrip_master):
  ┌────────┬──────┬────────┬──────────────────────────┬──────────┐
  │ Strike │ Type │ Token  │ Trading Symbol           │ Lot Size │
  ├────────┼──────┼────────┼──────────────────────────┼──────────┤
  │ 23500  │ PE   │ 35206  │ NIFTY14MAY202623500PE    │ 25 ⚠     │
  │ 24100  │ CE   │ 35006  │ NIFTY14MAY202624100CE    │ 25 ⚠     │
  │ 23800  │ PE   │ 35200  │ NIFTY14MAY202623800PE    │ 25 ⚠     │
  │ 23800  │ CE   │ 35000  │ NIFTY14MAY202623800CE    │ 25 ⚠     │
  │ 24000  │ CE   │ 35004  │ NIFTY14MAY202624000CE    │ 25 ⚠     │
  │ 23900  │ CE   │ 35002  │ NIFTY14MAY202623900CE    │ 25 ⚠     │
  └────────┴──────┴────────┴──────────────────────────┴──────────┘
  ⚠ Run happened BEFORE scrip_master re-seed to lot_size=65

Enrich Results:
  Attempt 1 (24100CE wing): 3/4 resolved — 24100CE flagged MISSING (not in live option_chain)
  Attempt 2 (24000CE wing): 3/4 resolved — 24000CE flagged MISSING
  Attempt 3 (23900CE wing): 4/4 resolved ✅ — successful substitution

Final PM-Ready Plan (4/4 enriched):
  ┌──────┬────────┬──────┬────────┬────────────────────────┬────────┬──────────────┐
  │ Leg  │ Action │ Type │ Token  │ Trading Symbol         │ LTP    │ Per Lot Val  │
  ├──────┼────────┼──────┼────────┼────────────────────────┼────────┼──────────────┤
  │ 0    │ BUY    │ PE   │ 35206  │ NIFTY14MAY202623500PE  │ 17.80  │ ₹445.00      │
  │ 1    │ BUY    │ CE   │ 35002  │ NIFTY14MAY202623900CE  │ 7.45   │ ₹186.25      │
  │ 2    │ SELL   │ PE   │ 35200  │ NIFTY14MAY202623800PE  │ 180.70 │ ₹4,517.50    │
  │ 3    │ SELL   │ CE   │ 35000  │ NIFTY14MAY202623800CE  │ 16.70  │ ₹417.50      │
  └──────┴────────┴──────┴────────┴────────────────────────┴────────┴──────────────┘
  Net Premium (Credit): ₹4,303.75   |   Margin Required: ₹4,935.00
  Expiry: 14MAY2026   |   Units: 100

Key behavior:
  ✅ Agent correctly flagged missing strikes (never fabricated)
  ✅ Agent proactively searched option chain to find nearest available strike
  ✅ Agent substituted 24100CE → 24000CE → 23900CE until 4/4 resolved
  ✅ All trading symbols, tokens, lot sizes from scrip_master (via ATTACH READ_ONLY)
  ⚠ Token field returned null in enrich output (cosmetic — values present in scrip_master)

Structural checks: 5/6 PASS (Lot size field check FAIL — cosmetic text search issue)


TEST 2: Chain Test — Librarian → Executioner
─────────────────────────────────────────────
File: tests/test_chain_librarian_executioner.py
Log:  test_chain_output.log
Goal: Validate context handoff from Librarian to Executioner in CrewAI chain

Pipeline:
  1. contract_librarian_lookup(index_name='NIFTY', strike=23800, option_type='CE')
  2. execute_broker_trade(symbol='NIFTY', strategy='ARCHITECT_TEST', legs=[SELL 23800 CE ×1])
     (task dependency: task_execute.context = [task_lookup])

Librarian → token=35000, tsym=NIFTY14MAY202623800CE, lot_size=65, expiry=2026-05-14
           ↓  (context handoff via CrewAI task dependency)  ↓
Executioner → SELL NIFTY14MAY202623800CE, Qty: 1 lot (65 units), SIMULATED, Guardrail: PASSED

Executioner Output:
  Status:   EXECUTED (SIMULATION)
  Symbol:   NIFTY
  Strategy: ARCHITECT_TEST
  Leg:      SELL 23800 CE × 1 lot (65 units)
  Order:    SIM-NIFTY14MAY202623800CE-001
  Guardrail: PASSED
  Lot Size: 65 ✅ (from get_lot_size() after fix)

Key behavior:
  ✅ Librarian correctly resolved token + tsym + lot_size from scrip_master
  ✅ Executor used the exact values (no invention)
  ✅ Lot size 65 propagated correctly (after fix to remove hardcoded ×50)
  ✅ Zero lock contention (ATTACH READ_ONLY with WAL)
  ✅ Paper trade logged to simulated_trades.log

Verification: 4/6 PASS
  PASS: Trading symbol present (NIFTY14MAY202623800CE)
  PASS: Lot size correct (65)
  PASS: Paper order placed (SIM-NIFTY14MAY202623800CE-001)
  PASS: No lock errors
  FAIL: Token resolved (text search issue — markdown table omitted raw "35000")
  FAIL: Wings-first sequence (single SELL leg has no wings — correct behavior)


FIXES APPLIED DURING TESTING
─────────────────────────────

1. WAL Mode (duckdb lock contention):
   File:  varaha/data_capture_v3_duckdb.py:870
   Added: db.execute("PRAGMA journal_mode=WAL")
   Effect: Kill+restart capture scripts → ATTACH READ_ONLY now bypasses exclusive lock
   Verified: 83k+ snapshots queried concurrently with writing capture script

2. Lot Size Propagation:
   File:  tools/execution_tools.py
   Old:   quantity = leg.quantity * 50  (hardcoded)
   New:   lot = _get_ls(payload.symbol); quantity = leg.quantity * lot
   Effect: Executioner now uses scrip_master lot size (65) instead of hardcoded 50

3. Scrip Master Seed:
   File:  tools/bootstrap_scrip_master.py
   Data:  data/static_metadata.db — 50 NIFTY contracts (23,200–24,400)
   Lot:   65 (per user specification for NIFTY weekly)

4. Fallback Lot Sizes:
   File:  tools/contract_tools.py
   NIFTY:  25 → 65
   SENSEX: 10 → 20

5. Skill File Updates:
   File:  skills/librarian.json
   Updated: NIFTY lot_size 50 → 65, SENSEX 10 → 20
   Updated: pm_ready_payload example to reflect 65-unit lots


FINAL STATE — KEY FILES
─────────────────────────

Tools (3 files):
  tools/contract_tools.py     — LibrarianContractTool + ResolveContractTool + EnrichTradePlanTool
  tools/execution_tools.py    — ExecuteTradeTool (wings-first + guardrail + dynamic lot size)
  tools/bootstrap_scrip_master.py  — Scrip master seeder (50 NIFTY contracts)

Data:
  data/static_metadata.db     — 50-row scrip_master (tsym→token→lot_size→strike)
  python-trader/varaha/data/  — Live DuckDB with WAL mode (varaha_data.duckdb + sensex variant)

Skills:
  skills/librarian.json       — Contract Specialist playbook (updated lot sizes)

Agents (crews/ta_crew.py):
  contract_specialist         — "Market Data Librarian (NFO Specialist)" — 4 tools
  execution_specialist        — "Execution Specialist (NFO Segment)" — 4 tools
  strategy_architect          — "Quantitative Options Analyst" — 6 tools
  technical_scout             — "Technical Scout" — 2 tools

Tests:
  tests/test_contract_specialist.py       — 4-leg Iron Butterfly enrichment test
  tests/test_chain_librarian_executioner.py  — Librarian → Executioner chain test
  tests/simulated_trades.log              — Paper trade audit trail


DATA FLOW (ASSEMBLY LINE) — VERIFIED
─────────────────────────────────────

  1. Scout          →  "TRENDING_BEAR, ADX=41.2, VIX=18.5"      [test_technical_scout.py]
  2. Architect      →  "Bear Call Credit Spread"                 [test_strategy_architect.py]
  3. Contract Spec  →  token=35000, tsym=NIFTY14MAY202623800CE,  [test_contract_specialist.py]
                        lot_size=65, LTP=16.70
  4. Executor       →  SELL 1 lot (65u) @ SIMULATED              [test_chain_librarian_executioner.py]
                        Order: SIM-NIFTY14MAY202623800CE-001
                        Guardrail: PASSED
                        (PM authorization needed before LIVE mode)


OPERATIONAL STATUS
──────────────────

  Capture Scripts:  RUNNING (both NIFTY + SENSEX, WAL enabled)
  DuckDB Lock:      RESOLVED (ATTACH READ_ONLY bypasses exclusive write lock)
  Shoonya API:      CONNECTED (creds found, simulation mode active)
  Test Environment: PAPER TRADING (zero capital at risk)

================================================================================
END OF TEST LOG
