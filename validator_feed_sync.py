"""Populates /var/log/algo/{atom_plus,proton,neutron,hydrogen,penguin}/ with
symlinks to each system's actual log/data/state files, so algo_validator has
a clean per-system view instead of antariksh/atom's mixed logs/ directories
(606+ files spanning CFO audits, kalki/OUROBOROUS build-loop tracking, CrewAI
dispatch logs, disk monitoring, etc. alongside the actual trading logs).

Filenames rotate daily (e.g. atom_paper_20260722.log), so this re-syncs on
every run rather than being a one-time snapshot — install on a cron alongside
permission_guard.py. Only ever creates/replaces symlinks (never touches the
real files); safe to run as often as needed.

Run: python3 validator_feed_sync.py
"""

import glob
import os
from pathlib import Path

FEED_ROOT = Path("/var/log/algo")
ATOM = Path("/home/trading_ceo/atom")
ANTARIKSH = Path("/home/trading_ceo/antariksh")
VARAHA_DATA = Path("/home/trading_ceo/python-trader/varaha/data")

# Each system: list of glob patterns (absolute) to symlink into its feed folder.
# PROTON folder covers both proton_live (base, disabled 2026-07-21) and
# proton_plus_live (active) — same underlying script, real-money vs paper mode.
# NEUTRON folder covers both monthly_ic_pilot (base, still active) and
# monthly_ic_pilot_orbiter (NEUTRON+) — same reasoning.
SYSTEMS = {
    "atom_plus": [
        str(ATOM / "logs" / "atom_paper*.log"),
        str(ATOM / "logs" / "atom_decision_ledger.jsonl"),
        str(ATOM / "logs" / "atom_mcx*.log"),
        str(ATOM / "logs" / "notify_eod_pnl*.log"),
        str(ATOM / "logs" / "notify_hourly*.log"),
        str(ATOM / "logs" / "preflight*.log"),
        str(ATOM / "data" / "atom_state.sqlite"),
        str(ATOM / "data" / "atom_state_sensex.sqlite"),
        str(ATOM / "data" / "mcx_state.sqlite"),
        str(ATOM / "data" / "audit_nifty.sqlite"),
        str(ATOM / "data" / "audit_sensex.sqlite"),
        str(ATOM / "data" / "audit_mcx.sqlite"),
        str(ATOM / "data" / "live_canary_state.sqlite"),
        str(ATOM / "data" / "live_canary_meta.json"),
        str(ATOM / "data" / "parameter_sets.sqlite"),
    ],
    "proton": [
        str(ANTARIKSH / "logs" / "proton" / "proton_live_cron*.log"),
        str(ANTARIKSH / "logs" / "proton" / "proton_plus_live_cron*.log"),
        str(ANTARIKSH / "logs" / "proton" / "proton_live.jsonl"),
        str(ANTARIKSH / "logs" / "proton" / "proton_live_dry.jsonl"),
        str(ANTARIKSH / "logs" / "proton" / "proton_live_dry_plus.jsonl"),
        str(ANTARIKSH / "data" / "proton" / "proton_live_dry_state_plus.json"),
    ],
    "neutron": [
        str(ANTARIKSH / "logs" / "neutron" / "monthly_ic_pilot_cron*.log"),
        str(ANTARIKSH / "logs" / "neutron" / "monthly_ic_pilot_orbiter_nifty_cron*.log"),
        str(ANTARIKSH / "logs" / "neutron" / "monthly_ic_pilot_orbiter_sensex_cron*.log"),
        str(ANTARIKSH / "logs" / "neutron" / "monthly_ic_pilot.jsonl"),
        str(ANTARIKSH / "logs" / "neutron" / "monthly_ic_pilot_orbiter_nifty.jsonl"),
        str(ANTARIKSH / "logs" / "neutron" / "monthly_ic_pilot_orbiter_sensex.jsonl"),
        str(ANTARIKSH / "data" / "neutron" / "monthly_ic_pilot_state.json"),
        str(ANTARIKSH / "data" / "neutron" / "monthly_ic_pilot_orbiter_nifty_state.json"),
        str(ANTARIKSH / "data" / "neutron" / "monthly_ic_pilot_orbiter_sensex_state.json"),
    ],
    "hydrogen": [
        str(ANTARIKSH / "logs" / "hydrogen" / "hydrogen_ic_pilot_orbiter_nifty_cron*.log"),
        str(ANTARIKSH / "logs" / "hydrogen" / "hydrogen_ic_pilot_orbiter_sensex_cron*.log"),
        str(ANTARIKSH / "logs" / "hydrogen" / "hydrogen_ic_pilot_orbiter_nifty.jsonl"),
        str(ANTARIKSH / "logs" / "hydrogen" / "hydrogen_ic_pilot_orbiter_sensex.jsonl"),
        str(ANTARIKSH / "data" / "hydrogen" / "hydrogen_ic_pilot_orbiter_nifty_state.json"),
        str(ANTARIKSH / "data" / "hydrogen" / "hydrogen_ic_pilot_orbiter_sensex_state.json"),
    ],
    "penguin": [
        str(ANTARIKSH / "logs" / "feed*.log"),
        str(ANTARIKSH / "logs" / "enricher_nifty*.log"),
        str(ANTARIKSH / "logs" / "enricher_sensex*.log"),
        str(ANTARIKSH / "logs" / "enricher_mcx*.log"),
        str(ANTARIKSH / "logs" / "consumer_nifty*.log"),
        str(ANTARIKSH / "logs" / "consumer_sensex*.log"),
        str(ANTARIKSH / "logs" / "consumer_mcx*.log"),
        str(ANTARIKSH / "logs" / "penguin_report*.log"),
        str(ANTARIKSH / "logs" / "multitf_live*.log"),
        str(VARAHA_DATA / "capture_*.sqlite"),
        str(VARAHA_DATA / "market_data_multitf*.duckdb"),
    ],
}


def sync() -> dict:
    counts = {}
    for system, patterns in SYSTEMS.items():
        dest_dir = FEED_ROOT / system
        dest_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        for pattern in patterns:
            for src in glob.glob(pattern):
                link = dest_dir / os.path.basename(src)
                if link.is_symlink() or link.exists():
                    if os.path.realpath(link) == os.path.realpath(src):
                        n += 1
                        continue
                    os.remove(link)  # replacing a stale/wrong symlink, not a real file
                os.symlink(src, link)
                n += 1
        counts[system] = n
    return counts


if __name__ == "__main__":
    result = sync()
    for system, n in result.items():
        print(f"{system}: {n} files linked")
