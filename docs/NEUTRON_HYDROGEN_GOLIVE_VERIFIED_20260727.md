# NEUTRON & HYDROGEN Go-Live Concerns — Verified 2026-07-27

Source: `/tmp/neutron_hydrogen_golive_concerns.md` (user-planted, ~11:35 IST). Checked each claim directly ~11:38 IST. Mostly holds, one major correction.

## Confirmed true

- **Feed pipeline recovered**: `feed_NIFTY.heartbeat`, `enricher_NIFTY.heartbeat` both stamped 11:38 IST, matching wall clock — pipeline is live, not just claimed.
- **Flattrade ₹0 cash**: verified live earlier today, `cash: 0.00`, `collateral: 9843.23`.
- **`broker_manager.py:81` bug real**: `Flattrade.load_token()` reads `data.get("token")`, `tokens.json` stores `access_token` — confirmed identical in both `antariksh/broker_manager.py` and `brahmand/broker_manager.py` (byte-identical file), still unfixed. Independently found earlier this session too.
- **No margin checks in NEUTRON+/HYDROGEN+**: grepped `monthly_ic_pilot_orbiter.py` and `hydrogen_ic_pilot_orbiter.py` for "margin" — zero hits in either. `proton_live.py` by contrast has `check_account_margin()` called at 3 call sites (lines 606, 1252, 1317). Real asymmetry, real gap.
- **TRADE_MODE=PAPER**: confirmed in `antariksh/.env`.
- **Untracked git files**: confirmed — `hydrogen_ic_pilot_orbiter.py`, `hydrogen_sl_atr_sweep.py`, both hydrogen orbiter state JSONs, `data/hydrogen/`, `data/neutron/`, both hydrogen cron wrappers all show `??`.

## Correction — claim #3 is wrong

File says "ALL NEUTRON/HYDROGEN crons commented out." **False.** `crontab -u algo_prod -l` shows all 4 orbiter lines active, uncommented:
```
0,15,30,45 9-15 * * 1-5 ... run_monthly_ic_pilot_orbiter_nifty.sh
0,15,30,45 9-15 * * 1-5 ... run_monthly_ic_pilot_orbiter_sensex.sh
0,15,30,45 9-15 * * 1-5 ... run_hydrogen_ic_pilot_orbiter_nifty.sh
0,15,30,45 9-15 * * 1-5 ... run_hydrogen_ic_pilot_orbiter_sensex.sh
```
Only the **deprecated base** (non-orbiter) `run_monthly_ic_pilot.sh` / `run_weekly_ic_pilot.sh` lines are commented — correctly, per existing memory: superseded by the `+`/orbiter tiers on 2026-07-20. File conflated "NEUTRON base" with "NEUTRON+." Today's WATCHER report already showed NEUTRON+/HYDROGEN+ (both NIFTY+SENSEX) running fine — consistent with crons being live, not dead.

## Minor discrepancy — claim #5 strikes

`data/monthly_ic_pilot_state.json` (base NEUTRON, not NEUTRON+): entry 2026-07-22, expiry 2026-07-28, strikes SP23850/LP23700/**SC24550/LC24700**. File claimed SC24500/LC24650 — both call-side strikes off by 50. Not a fabrication-scale error like the earlier two planted files, but worth a recheck if this number matters for a decision.

## Not independently re-verified this pass

- Claim #4 sub-point "nucleus ceiling provides no runtime enforcement" — plausible given no margin-check calls found, not separately traced through nucleus.py's call graph.
- Claim #7 SENSEX negative-EV numbers (-₹57.93/lot 1SD, -₹62.58/lot 0.20Delta) — consistent with prior memory (`hydrogen_project`, SENSEX-Tue known-negative) but exact figures not re-run.
- Claim #10 backtest sample sizes (53 trades, 71.7% win) — not re-verified.

## Net

Real, current list — not a planted-garbage file like the DNS one. One correction: crons are NOT all dead, only the intentionally-retired base tier is. Everything else in the "blocking" and "high risk" tiers checks out as stated (with the one minor strike-number mismatch).
