# PROTON+ — ORBITER v3.0 Tier 2 LIVE (2026-07-17)

## What was done
Retrofitted ORBITER v3.0 specs into `proton_live.py` following the same `use_orbiter=True` boolean-flag pattern as ATOM+.

## Architecture
- **Entrypoint**: `proton_live.py` → `run_live_once(use_orbiter=True)`
- **State**: `data/proton_live_state.json` (key: `orbiter_position`, separate from non-ORBITER `open_position`)
- **Real orders**: `PROTON_LIVE_TRADING=YES_REAL_MONEY` set in cron wrapper
- **Same Shoonya token/pool as ATOM** — shares broker session, nucleus ceiling gates capital

## Entry rule
**Nearest-expiry index**: whichever of NIFTY/SENSEX has the closer weekly expiry (`_nearest_expiry_index()`). No EOD time gate — enters as soon as cron fires if conditions met.

### Entry gates (ORBITER 3-Gate sequential)
1. **Vol filter**: trailing 20d realized vol > trailing ~6mo median (from PROTON paper pilot)
2. **Gate 1 (Regime)**: ADX ≤ 25 AND wide CPR/BB (`orbiter_mod.gate1_regime()`)
3. **Gate 3 (PCR abort)**: PCR not in bull/bear divergence zone (`orbiter_mod.gate3_entry_abort()`)
4. **Gate 2 (Strikes)**: BB/VWAP/MaxPain-anchored short strikes (`orbiter_mod.gate2_strikes()`)
5. **Phase 1 direction**: VWAP vs spot → bull_put_spread or bear_call_spread (`orbiter_mod.phase_machine_direction()`)
6. **Margin**: `check_account_margin()`, `broker_confirms_flat()`, `_nucleus_ceiling("T3_HYDROGEN")`

### Entry order placement
- 2-leg directional spread (hedge buy → short sell → resting SL-LMT on short)
- `_orbiter_enter_legs()` — same Shoonya place_leg/place_resting_sl pattern as original proton_live

## Exit
### Per-side checks (across all active sides: put + call if morphed)
1. **Static PT/SL backstop**: 60% credit captured (PT) / 1.0× credit lost (SL)
2. **ATR TSL**: `SL_dynamic = P_entry + 1.5 * ATR`, ratchets down 0.5*ATR at 25% premium drop, catastrophe stop at 50% above dynamic
3. **5-point TP priority array**: VWAP_STRETCH (2.5σ) → IV_CRUSH (55% in <25% time) → PCR_DIVERGENCE → DECAY_80 → EXPIRY
4. **EXPIRY**: hard close at expiry date (multi-day equivalent of ATOM's EOD_HARD)
5. **HARVEST_50**: if total P&L across all active sides ≥ 50% of total max profit, exit ALL sides

### Exit order placement
- Cancel resting SL → buyback short → sell hedge, per side. `_orbiter_exit_side()`

## Morph (Dynamic Legging Phase 2)
- `_morph_check_orbiter()` checks `consolidation_trigger()` (ADX < 20, PCR flat, short strike unbreached)
- If triggered: enters opposite side spread → iron condor, phase moves to CONSOLIDATION
- Same order placement pattern as entry (hedge + short + resting SL)

## Roll-forward rule
**Any fully closed exit → enter opposite index** (NIFTY ↔ SENSEX, alternating). No loss locks, no exceptions. `HARVEST_50` and all other exit reasons use same simple flip.

## ORBITER 3.0 spec coverage

| Spec | Status | Where |
|------|--------|-------|
| Gate 1 (ADX+CPR regime) | ✅ | `orbiter_mod.gate1_regime()` |
| Gate 2 (BB+MaxPain strikes) | ✅ | `orbiter_mod.gate2_strikes()` |
| Gate 3 (PCR entry-abort) | ✅ | `orbiter_mod.gate3_entry_abort()` |
| ATR TSL (1.5×ATR + ratchet) | ✅ | `orbiter_mod.orbiter_initial_tsl/tsl_ratchet/catastrophe_stop()` |
| 5-point TP (VWAP/IV/PCR/DECAY80/EXPIRY) | ✅ | `orbiter_mod.orbiter_tp_check()` |
| Dynamic Legging Ph1 (VWAP direction) | ✅ | `orbiter_mod.phase_machine_direction()` |
| Dynamic Legging Ph2 (morph to condor) | ✅ | `orbiter_mod.consolidation_trigger()` |
| Dynamic Legging Ph3 (asymmetric breakage) | ✅ | In orbiter_weekly.py, mirrors ATOM dead-code status |
| Margin Sweep (nucleus ceiling) | ✅ | `_nucleus_ceiling("T3_HYDROGEN")` |

## Data pipeline dependency
- Reads `market_data_enriched` + `market_data_multitf` from `capture_nifty.sqlite` (ATOM's Penguin)
- `orbiter_mod._read_enriched_row("NIFTY", today)` — read-only, mode=ro
- Gates fail CLOSED if enriched data missing (entry-only); TSL/TP fail OPEN (static PT/SL always runs)

## NUCLEUS capital orchestration
- `_nucleus_ceiling("T3_HYDROGEN")` reads `data/nucleus_allocation.json`
- `nucleus.py` refreshes every ~15 min via cron: `13,28,43,58 8-15 * * 1-5`
- Staleness threshold: 18h (1080 min) — covers overnight gap
- Fails closed: returns None → entry refused
- Latest (Jul 16 close): T3_HYDROGEN = ₹1,37,744.65 out of ₹4,05,131.33 pool

## Cron entries

```
# NUCLEUS — offsets 2 min before PROTON+ to guarantee fresh allocation file
13,28,43,58 8-15 * * 1-5 /home/trading_ceo/antariksh/cron/run_nucleus.sh

# PROTON+ ORBITER v3.0 Tier 2 LIVE — real-money, nearest-expiry entry, roll-forward
0,15,30,45 9-15 * * 1-5 /home/trading_ceo/antariksh/cron/run_proton_plus_live.sh
```

## Key files

| File | Role |
|------|------|
| `proton_live.py` | Main entry — `run_live_once(use_orbiter=True)` |
| `orbiter_weekly.py` | ORBITER 3.0 specs ported for multi-day (329 lines) |
| `weekly_ic_pilot_orbiter.py` | Paper-only sibling pilot (280 lines, NOT live) |
| `cron/run_proton_plus_live.sh` | Cron wrapper with LIVE_TRADING=YES_REAL_MONEY |
| `data/proton_live_state.json` | State: `orbiter_position`, `open_position`, `stranded_legs` |
| `logs/proton_live.jsonl` | Shared ledger (ORBITER + non-ORBITER) |
| `data/nucleus_allocation.json` | Dynamic capital ceilings from nucleus.py |
| `tests/test_orbiter_weekly.py` | 37 tests, all passing |

## Troubleshooting
- **No entry**: check `logs/proton_plus_live_cron_YYYYMMDD.log` for gate/vol/nucleus rejections
- **Stale nucleus**: ensure `nucleus_allocation.json` updated_at is within 18h
- **No enriched data**: Penguin enricher down → gates fail closed, retry next tick
- **Resume after error**: delete `orbiter_position` from state to force flat, system re-enters
