# WATCHER — LLM-Powered System Audit
# Created: 2026-07-24  |  Updated: 2026-07-25 (v0.2 + feed health)

Project:    WATCHER
Role:       Semantic cross-system validator using DeepSeek API
Owner:      algo_validator
Location:   /home/algo_validator/
Script:     llm_validator.py
Cron:       0 9-23 * * 1-5  (hourly, Mon-Fri market hours)

Model:      DeepSeek API (deepseek-v4-pro, temperature=0, max_tokens=1200)
State:      Stateless — no persisted state between runs

═══════════════════════════════════════════════════════════
LAYER 1 — Deterministic Checks (pre-computed, direct to TG)
═══════════════════════════════════════════════════════════

  a) Instrument whitelist validation
     Hard-coded per system (synced with LOG_FILE_REFERENCE.md):
       ATOM+     → NIFTY, SENSEX, CRUDEOILM, SILVERMIC
       PROTON+   → NIFTY, SENSEX
       NEUTRON+  → NIFTY, SENSEX
       HYDROGEN+ → NIFTY, SENSEX
     Any trade on an unrecognized instrument = 🚨 critical alert

  b) State-vs-ledger reconciliation
     Scans FULL ledger history (not just today) against state JSON.
     Both directions:
       - Ledger shows active position (ENTER without EXIT) → state must show position
       - State shows position → must have matching ENTER in ledger (by date + instrument)
     Detects: ORPHAN positions (ledger yes, state no) and PHANTOM positions (state yes, ledger no)

  c) Cross-system strike overlap
     Compares all active positions across NEUTRON+ and HYDROGEN+ variants.
     If both hold the same instrument+strike (different expiry) → INFO
     Upgrades to ⚠️ WARNING if either system is in real-money mode

═══════════════════════════════════════════════════════════
LAYER 2 — DeepSeek Semantic Analysis
═══════════════════════════════════════════════════════════

  - Broker-vs-log mismatch (system claims trade, broker shows no order)
  - Crash detection (Traceback in stdout)
  - Structural anomalies (stale data, impossible FSM transitions)
  - NOTE: deterministic findings are NOT fed to DeepSeek — LLM never softens hard violations

═══════════════════════════════════════════════════════════
LAYER 3 — Broker Ground Truth (passive)
═══════════════════════════════════════════════════════════

  - Reads capture_orders.sqlite (Penguin pipeline)
  - All order_updates for today → fed to DeepSeek for cross-reference

Systems monitored: ATOM+, PROTON+, NEUTRON+, HYDROGEN+
Log access: /var/log/algo/{atom_plus,proton,neutron,hydrogen,penguin}/

  d) Feed health monitoring (added 2026-07-25)
     Scans penguin/feed.log for WS disconnect signals (WS close 1008,
     Broker rejected session, recursion crash). Checks consumer_*.log
     for stale bar ages. Monitors order_updates table staleness (>24h idle).
     All read from persisted files — WATCHER never touches live WS socket.

Documentation: /home/trading_ceo/antariksh/docs/LOG_FILE_REFERENCE.md
Architecture:  Google Doc — "Trading System Validation Architecture"
