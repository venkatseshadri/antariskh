# Log & Data File Reference

Last updated: 2026-07-24. Covers every trading system's log/state/data file
locations after the per-system folder rewiring (2026-07-22 to 2026-07-24).

## Quick reference — validator-facing paths

`algo_validator` reads through `/var/log/algo/<system>/` — real-time symlinks
into each system's actual files, source code excluded entirely.

| System | `/var/log/algo/` folder | Real source |
|---|---|---|
| ATOM+ | `atom_plus/logs`, `atom_plus/data` | `atom/logs/`, `atom/data/` (direct symlinks — already clean, no rewrite needed) |
| PROTON (base + PROTON+) | `proton/` | `antariksh/logs/proton/`, `antariksh/data/proton/` |
| NEUTRON (base + NEUTRON+) | `neutron/` | `antariksh/logs/neutron/`, `antariksh/data/neutron/` |
| HYDROGEN+ | `hydrogen/` | `antariksh/logs/hydrogen/`, `antariksh/data/hydrogen/` |
| Penguin | `penguin/` | `antariksh/logs/penguin/` (logs) + `python-trader/varaha/data/` (capture DBs, already clean) |

`atom_plus/` also still has ~66 leftover per-file symlinks from the original
sync-script approach (2026-07-22) sitting alongside the two folder symlinks
— harmless, superseded, not deleted (blanket `rm`/`unlink`/`rmdir` guardrail
in permission settings; use the `logs`/`data` folder symlinks, ignore the rest).

---

## ATOM+ (`atom/` repo)

No rewrite was needed — `atom/logs/` and `atom/data/` were already
atom-exclusive (some ATOM dev/test debug logs mixed in — `harness*.log`,
`phase0_*`, `phase1_*` — but no *other system's* files).

| File | Purpose |
|---|---|
| `logs/atom_paper_YYYYMMDD.log` | Daily cron stdout, NIFTY/SENSEX cycles |
| `logs/atom_mcx_YYYYMMDD.log` | Daily cron stdout, MCX cycles |
| `logs/atom_decision_ledger.jsonl` | Decision-level audit trail (Module 16 config, GO/NOGO, etc.) |
| `logs/notify_eod_pnl_YYYYMMDD.log`, `notify_hourly_YYYYMMDD.log` | Notification cron logs |
| `logs/preflight_YYYYMMDD.log` | Pre-open health check |
| `data/atom_state.sqlite` | NIFTY position/trade state (`paper_trades` table) |
| `data/atom_state_sensex.sqlite` | SENSEX position/trade state |
| `data/mcx_state.sqlite` | MCX position/trade state |
| `data/audit_{nifty,sensex,mcx}.sqlite` | Audit databases |
| `data/live_canary_state.sqlite`, `live_canary_meta.json` | Live broker canary test state |
| `data/parameter_sets.sqlite` | Research-loop parameter versions |

---

## PROTON (`antariksh/` repo — `proton_live.py`)

One script, two cron entries: `run_proton_live.sh` (base, **disabled** since
2026-07-21 — commented out in root's crontab) and `run_proton_plus_live.sh`
(PROTON+, active, paper mode since 2026-07-20). Real money only ever ran
2026-07-17 to 2026-07-20 and never actually placed an order (always blocked
by Gate1/margin).

| File | Purpose |
|---|---|
| `logs/proton/proton_live_cron_YYYYMMDD.log` | Base PROTON cron stdout (dry-run) |
| `logs/proton/proton_plus_live_cron_YYYYMMDD.log` | PROTON+ cron stdout |
| `logs/proton/proton_live.jsonl` | Real-money ledger (LIVE_ENABLED=True, unused since flip) |
| `logs/proton/proton_live_dry.jsonl` | Base PROTON paper ledger |
| `logs/proton/proton_live_dry_plus.jsonl` | **PROTON+ paper trade ledger — the one that matters** |
| `data/proton/proton_live_state.json` | Real-money state (unused since flip) |
| `data/proton/proton_live_dry_state_plus.json` | PROTON+ current position state |

Path constants: `proton_live.py` — `STATE_PATH`, `LEDGER_PATH` (both branch on
`LIVE_ENABLED` and `_INSTANCE_SUFFIX`).

---

## NEUTRON (`antariksh/` repo)

Two scripts: `monthly_ic_pilot.py` (base, **still active**, non-ORBITER) and
`monthly_ic_pilot_orbiter.py` (NEUTRON+, ORBITER v3, NIFTY+SENSEX).

| File | Purpose |
|---|---|
| `logs/neutron/monthly_ic_pilot_cron_YYYYMMDD.log` | Base NEUTRON cron stdout |
| `logs/neutron/monthly_ic_pilot_orbiter_nifty_cron_YYYYMMDD.log` | NEUTRON+ NIFTY cron stdout |
| `logs/neutron/monthly_ic_pilot_orbiter_sensex_cron_YYYYMMDD.log` | NEUTRON+ SENSEX cron stdout |
| `logs/neutron/monthly_ic_pilot.jsonl` | Base NEUTRON trade ledger |
| `logs/neutron/monthly_ic_pilot_orbiter_nifty.jsonl` | NEUTRON+ NIFTY trade ledger |
| `logs/neutron/monthly_ic_pilot_orbiter_sensex.jsonl` | NEUTRON+ SENSEX trade ledger |
| `data/neutron/monthly_ic_pilot_state.json` | Base NEUTRON position state |
| `data/neutron/monthly_ic_pilot_orbiter_nifty_state.json` | NEUTRON+ NIFTY position state |
| `data/neutron/monthly_ic_pilot_orbiter_sensex_state.json` | NEUTRON+ SENSEX position state |

Path constants: `monthly_ic_pilot.py` — `STATE_PATH`, `LEDGER_PATH`.
`monthly_ic_pilot_orbiter.py` — `STATE_FILE`, `LEDGER_FILE` (per-instrument,
set in `__main__`).

---

## HYDROGEN+ (`antariksh/` repo — `hydrogen_ic_pilot_orbiter.py`)

Next-week-expiry IC orbiter, NIFTY+SENSEX. No base/non-orbiter predecessor.

| File | Purpose |
|---|---|
| `logs/hydrogen/hydrogen_ic_pilot_orbiter_nifty_cron_YYYYMMDD.log` | NIFTY cron stdout |
| `logs/hydrogen/hydrogen_ic_pilot_orbiter_sensex_cron_YYYYMMDD.log` | SENSEX cron stdout |
| `logs/hydrogen/hydrogen_ic_pilot_orbiter_nifty.jsonl` | NIFTY trade ledger |
| `logs/hydrogen/hydrogen_ic_pilot_orbiter_sensex.jsonl` | SENSEX trade ledger |
| `data/hydrogen/hydrogen_ic_pilot_orbiter_nifty_state.json` | NIFTY position state |
| `data/hydrogen/hydrogen_ic_pilot_orbiter_sensex_state.json` | SENSEX position state |

Path constants: `STATE_FILE`, `LEDGER_FILE` in `__main__` (same shape as NEUTRON+).

Known behavior: NEUTRON+ and HYDROGEN+ can independently enter the *same*
trade when the current week's next-weekly expiry coincidentally equals the
monthly expiry — not a bug, just two systems agreeing on the same signal off
the same data (see session notes 2026-07-21/22).

---

## Penguin (capture pipeline)

Logs live in `antariksh/`, actual capture databases live in a **third repo**
(`python-trader/varaha/data/`) — pre-existing split, not something this
rewiring changed.

| File | Purpose |
|---|---|
| `antariksh/logs/penguin/feed.log` | `feed.service` — WebSocket ingestion (NIFTY/SENSEX/MCX) |
| `antariksh/logs/penguin/enricher_{nifty,sensex,mcx}.log` | `enricher-*.service` — bars → `market_data_enriched` |
| `antariksh/logs/penguin/consumer_{nifty,sensex,mcx}.log` | `consumer-*.service` — Redis → SQLite |
| `antariksh/logs/penguin/multitf_live.log` | `run_multitf_live.sh` — intraday multi-timeframe refresh |
| `python-trader/varaha/data/capture_{nifty,sensex,mcx,...}.sqlite` | Live tick/bar capture DBs (per-instrument, one per feed) |
| `python-trader/varaha/data/market_data_multitf*.duckdb` | Multi-timeframe aggregated data |

Config: 7 systemd units in `/etc/systemd/system/` (`feed.service`,
`enricher-{nifty,sensex,mcx}.service`, `consumer-{nifty,sensex,mcx}.service`)
— `StandardOutput`/`StandardError` set the log path directly. `penguin_report.log`
(daily EOD report) source not located during this rewiring — still writes to
the old flat `antariksh/logs/` location; low priority, not trade-critical.

---

## Who runs what (roles)

| Role | Identity | Scope |
|---|---|---|
| Developer | `trading_ceo` | Owns/edits source, full rw on `.py`/`.sh` |
| Production — trading crons | `algo_prod` | All 41 trading cron entries (migrated from root 2026-07-21) |
| Production — Penguin | `trading_ceo` (`User=` in each systemd unit) | feed/enricher/consumer services |
| Validator | `algo_validator` | Read-only on `/var/log/algo/*` — logs/data/state only, zero source access |

Source isolation: all `.py`/`.sh` files across `atom/` and `antariksh/` are
group `trading_ceo`, mode `640`/`750` — `algo_validator` is not in that group
and cannot read them. `algo_prod` **is** in that group (needs to execute the
code) but is not in `algo_validator`'s group (can't read `/var/log/algo/` —
not that it would need to).

## Maintenance

`antariksh/permission_guard.py` (cron, every 5 min market hours, runs as
whichever user's crontab entry fires it) does two things on every tick:
1. Re-enforces source-file group/mode (catches Edit-tool-induced group resets)
2. Refreshes `/var/log/algo/{atom_plus,proton,neutron,hydrogen,penguin}/`
   symlinks via `validator_feed_sync.py` — only matters for `atom_plus/`'s
   leftover per-file symlinks and any still-flat dated log files; the
   per-system folder symlinks (`proton/`, `neutron/`, `hydrogen/`,
   `penguin/`) never go stale since the real scripts write directly into
   the real subdirectories now.

Logs of its own runs: `antariksh/logs/permission_guard.jsonl`.
