# Sandwich — Progress Log

## Step 1: Connect & Inspect ✅ 2026-05-16

**Goal:** Confirm Sandwich can read the existing DuckDB market_data table and produce one plot + one printout.

**Files created:**
- `sandwich/README.md` — project overview and rules
- `sandwich/steps/step01_connect_and_inspect.py` — standalone inspect script
- `sandwich/steps/step01_spot_curve.png` — NIFTY spot plot (129 KB)

**Acceptance criteria met: 8/8**
1. ✅ `antariksh/sandwich/` exists with correct structure
2. ✅ README.md matches spec
3. ✅ `step01_connect_and_inspect.py` exists with exact 5-function structure
4. ✅ Script runs to completion without error
5. ✅ All print() outputs produced
6. ✅ `step01_spot_curve.png` written
7. ✅ Committed and pushed to `github.com/venkatseshadri/antariskh`
8. ✅ No files outside `antariksh/sandwich/` modified

**Key findings:**
- DB: 27.5 MB, 1,557 rows across 5 dates (May 8-15)
- Spot range: 23,464 – 24,244 (mean 23,881)
- VIX range: 16.22 – 18.99 (mean 18.16)
- Capture cadence: exactly 60 seconds (solid)
- Zero nulls in spot, VIX, DTE, or atm_strike columns
- May 12 has only 20 rows (partial capture / infra event)
- May 14-15 have higher row counts (535 on May 15)

**Anomalies noted:**
- DB_PATH needed hardcoding — `Path.home()` is `/root`, data lives under `/home/trading_ceo`
- matplotlib required `--break-system-packages` install on this environment

**Link:** `github.com/venkatseshadri/antariskh/tree/master/sandwich`
