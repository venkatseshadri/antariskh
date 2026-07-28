# WATCHER & SENTINEL — Validation Projects Summary
# Stored: 2026-07-25  |  Auto-improving from Claude Feedback Loop

═══════════════════════════════════════════════════════════════
ORIGIN
═══════════════════════════════════════════════════════════════

Built per the "Trading System Validation Architecture" (Google Doc).
Two independent validators running as algo_validator OS user, with
strict kernel-level isolation from the trading systems they monitor.

Design principle from Claude:
  "Deterministic logic IS the system, LLM is overlay-only"
  → Hard violations never go through an LLM that could soften them.

═══════════════════════════════════════════════════════════════
SENTINEL — Rule-Based Validator (sentinel.py)
═══════════════════════════════════════════════════════════════

  Scope:    ATOM+ only (NIFTY Iron Fly + MCX directional)
  Runs:     Every 5 min (cron: */5 9-23 * * 1-5)
  Method:   Deterministic boolean checks, no external API
  State:    .sentinel_state.json — deduplicates fired alerts per day

  Checks:
    🚨 OPEN while FSM≠FLAT         — Double-entry / orphaned position
    🚨 Not FLAT at EOD              — Position left open past market close
    🚨 >6 SL hits/day               — Strategy drift / whipsaw
    🚨 Dev config running           — "-dev" in frozen config line
    🚨 Unapproved config            — "APPROVED" missing from config
    ⚠️  12+ stale_feed consecutive   — Data feed outage during market hours
    ⚠️  Zero trades in market        — Strategy silently inactive
    ℹ️  EOD summary                  — Daily per-strategy digest

  Log formats:
    ATOM+ Paper: Block-delimited (----- TIMESTAMP -----), actions as text
    ATOM+ MCX:   Block-delimited, actions as Python dict strings

  Alert:  Telegram (urllib, same bot token as ATOM+)

═══════════════════════════════════════════════════════════════
WATCHER — LLM-Powered System Audit (llm_validator.py)
═══════════════════════════════════════════════════════════════

  Scope:    All 4 systems (ATOM+, PROTON+, NEUTRON+, HYDROGEN+) + Penguin feed
  Runs:     Every hour (cron: 0 9-23 * * 1-5)
  Method:   3-layer validation — deterministic pre-checks → DeepSeek API → Telegram
  Model:    DeepSeek v4 Pro (deepseek-v4-pro, temperature=0, max_tokens=1200)
  State:    Stateless per run (config lives in watcher_config.json)

  LAYER 1 — Deterministic Pre-checks (pre-computed, direct to Telegram):
    a) Instrument whitelist
       Hard-coded per system:
         ATOM+     → NIFTY, SENSEX, CRUDEOILM, SILVERMIC
         PROTON+   → NIFTY, SENSEX
         NEUTRON+  → NIFTY, SENSEX
         HYDROGEN+ → NIFTY, SENSEX
       Unknown instrument → 🚨 alert + proactive question to Claude mailbox

    b) State-vs-ledger reconciliation
       Full ledger history scan (not just today), both directions:
         - ORPHAN: ledger shows active position, state shows null
         - PHANTOM: state shows position, no matching ENTER in full ledger
       Matched by date+instrument (exact ts may differ ms between writes)

    c) Cross-system strike overlap
       NEUTRON+ vs HYDROGEN+ active position comparison
       Same instrument + same strikes → ℹ️ INFO (paper mode) / ⚠️ WARNING (real money)
       Known behavior documented in LOG_FILE_REFERENCE.md

    d) Feed health (added per Claude's 2026-07-25 outage investigation)
       Scans penguin/feed.log for:
         - WS close 1008 / Broker rejected session patterns
         - Recursion crash signals
       Checks consumer_*.log for stale bar ages (>configurable threshold)
       Monitors capture_orders.sqlite staleness (>24h idle)

  LAYER 2 — DeepSeek Semantic Analysis:
    - Broker-vs-log mismatch detection
    - Crash propagation (Traceback in stdout)
    - Structural anomalies (stale data, impossible FSM transitions)
    - Deterministic findings are NEVER fed to DeepSeek (LLM cannot soften violations)

  LAYER 3 — Self-Improvement (Claude Feedback Loop):
    Before each analysis run:
      1. Load config overrides from watcher_config.json
      2. Scan /tmp/claude_feedback/responses/watcher_*.md (unread)
      3. Parse CHANGE: directives from Claude's responses
      4. Auto-apply safe changes:
         - Whitelist additions → watcher_config.json
         - Threshold adjustments → watcher_config.json
      5. Log to watcher_change_history.jsonl
      6. Notify via Telegram what was learned
      7. Rename response to .md.read

    Proactive questioning:
      When WATCHER detects an unknown instrument, it writes to:
        /tmp/claude_feedback/requests/watcher_new_instrument_<symbol>.md
      Asking Claude: "Should this be whitelisted?"

    Safety:
      - Only modifies watcher_config.json (never source code)
      - All changes logged with timestamp
      - Human can audit: watcher_change_history.jsonl
      - Can disable auto-apply: set learning.enabled = false in config

═══════════════════════════════════════════════════════════════
ARCHITECTURE
═══════════════════════════════════════════════════════════════

  OS user:     algo_validator (uid 1004)
  Groups:      algo_validator, users, algolog
  Home:        /home/algo_validator/ (chmod 700)
  Log access:  /var/log/algo/{atom_plus,proton,neutron,hydrogen,penguin}/
               Read-only via symlinks maintained by validator_feed_sync.py

  Isolation:
    - Cannot read /home/algo_prod/ (chmod 700, PermissionError)
    - Cannot read /home/trading_ceo/ source code (group isolation)
    - Cannot access broker credentials directly
    - Only reads persisted log/state/data files

  Credentials (in /home/algo_validator/.env, mode 600):
    - TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (same as ATOM+)
    - DEEPSEEK_API_KEY (from antariksh/.env)

  Key files in /home/algo_validator/:
    sentinel.py                  — SENTINEL (rule-based, every 5 min)
    llm_validator.py             — WATCHER (LLM + deterministic + self-improvement)
    watcher_config.json          — Learned config overrides (whitelist, thresholds)
    .sentinel_state.json         — SENTINEL alert dedup state
    watcher_change_history.jsonl — WATCHER auto-change audit trail
    .env                         — Telegram + DeepSeek credentials
    SENTINEL.md, WATCHER.md      — Reference docs (also in antariksh/docs/)

  Crontab (algo_validator):
    */5 9-23 * * 1-5  sentinel.py        — SENTINEL
    0 9-23 * * 1-5    llm_validator.py   — WATCHER (self-improvement piggybacks)

  Claude Feedback Loop (separate cron, runs as root):
    0 * * * *  antariksh/cron/check_claude_feedback.sh
    Mailbox: /tmp/claude_feedback/requests/ + responses/
    Access:  group users rwx (algo_validator + algo_prod can write)

═══════════════════════════════════════════════════════════════
SYSTEMS MONITORED
═══════════════════════════════════════════════════════════════

  1. ATOM+     — NIFTY Iron Fly + MCX directional (atom/ repo)
                 Intraday, per-minute cron, block-based stdout logs
                 Paper: OPEN_IRON_FLY → HOLD → EXIT, FSM: FLAT/IRON_FLY
                 MCX:   OPEN → HOLD → EXIT, FSM: FLAT/POSITION
                 Instruments: NIFTY, CRUDEOILM, SILVERMIC

  2. PROTON+   — NIFTY/SENSEX bull-put-spread orbiter (antariksh/proton_live.py)
                 Per-minute cron, JSONL ledger
                 Actions: ENTER_TRIGGER_ORBITER, EXIT_TRIGGER_ORBITER, GATE_BLOCKED
                 State: proton_live_dry_state_plus.json (orbiter_position)
                 Instruments: NIFTY, SENSEX

  3. NEUTRON+  — Monthly IC orbiter NIFTY+SENSEX (antariksh/monthly_ic_pilot_orbiter.py)
                 Daily cron, JSON blocks + JSONL ledger
                 Actions: ENTER, HOLD, EXIT, MORPH, SKIP, STALE_ENRICHED_DATA
                 State: monthly_ic_pilot_orbiter_{nifty,sensex}_state.json
                 Instruments: NIFTY, SENSEX

  4. HYDROGEN+ — Next-week IC orbiter NIFTY+SENSEX (antariksh/hydrogen_ic_pilot_orbiter.py)
                 Same format as NEUTRON+
                 Different expiry horizon (next-week vs monthly)
                 Can overlap with NEUTRON+ on same strikes (expected, not a bug)

  Penguin    — Data capture pipeline (feed/enricher/consumer services)
                 capture_orders.sqlite — broker order_updates (ground truth)
                 capture_{nifty,mcx,...}.sqlite — market data, option prices
                 WebSocket health via feed.log scan

═══════════════════════════════════════════════════════════════
KNOWN GAPS (per Claude's 2026-07-25 feedback)
═══════════════════════════════════════════════════════════════

  1. Portfolio/holdings polling NOT captured in Penguin (HIGH)
     Order-status events resume when WS session stabilizes.
     But positions/holdings need new periodic poll → capture table.
     Required before any system goes LIVE with real money.

  2. WATCHER cannot see live WebSocket state (by design)
     Only reads persisted files. Can infer feed health indirectly
     (stale bars, WS close patterns in logs) but cannot detect
     auth rejections or thread leaks as they happen.

  3. SENTINEL covers ATOM+ only
     PROTON+/NEUTRON+/HYDROGEN+ deterministic validation
     lives in WATCHER's Layer 1.

═══════════════════════════════════════════════════════════════
DOCUMENTATION
═══════════════════════════════════════════════════════════════

  Local:     /home/algo_validator/SENTINEL.md, WATCHER.md
  Shared:    /home/trading_ceo/antariksh/docs/SENTINEL.md, WATCHER.md
  Systems:   /home/trading_ceo/antariksh/docs/LOG_FILE_REFERENCE.md
  Loop:      /home/trading_ceo/antariksh/docs/CLAUDE_FEEDBACK_LOOP.md
  README:    /tmp/README.md (project overview)
