# TA 3-Way Split — PAUL Plan

## P: Plan

### Problem
TA has 2 agents: TradeValidator (mechanical checks) + ComplianceReporter (reports).
Gap: nobody validates the trade plan from an options market perspective.
The system can execute a spec with strikes at wrong IV percentile, unrealistic
premiums, or wings too narrow for current volatility — and TA doesn't flag it.

### Solution
Split TA into 3 agents:
1. **Trade Execution Validator** — spec conformance, slippage, duplicates (same tools)
2. **Options Market Analyst** — greeks sanity, strike logic, premium decay, SL adequacy
3. **Compliance Reporter** — reports to PM/AM (same tools)

### New Tools (tools/ta_tools.py)
- `validate_strike_logic()` — ATM grid check, wing-width vs VIX, expiry distance
- `check_premium_reasonableness()` — premium-to-strike ratio, bid-ask spread
- `validate_sl_vs_volatility()` — is SL adequate for current VIX range?
- `generate_options_report()` — pass/fail with greeks/SL/wings evidence

### Updated Files
- `tools/ta_tools.py` — add 4 new functions
- `crews/ta_crew.py` — 3 agents, 2 tasks (validation + market + report)
- `config/agents.json` — add "options_analyst" entry

## A: Apply (next step)

## U: Unify
- Syntax check 3 files
- Unit test new tools with sample data

## L: Loop
- Wire into session flow so OM validates trades pre-execution
