"""
Sandwich Step 1 — Connect & Inspect

Goal: confirm we can read the existing DuckDB market_data table, validate basic
data shape (rows, cadence, nulls, DTE distribution), and produce one spot plot.

This is a standalone script. It does NOT import from any other Sandwich module,
and it does NOT import from any existing antariksh code.

Run from repo root:
    python sandwich/steps/step01_connect_and_inspect.py
"""

from pathlib import Path

import duckdb
import pandas as pd
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# Config — adjust DB_PATH if needed
# ---------------------------------------------------------------------------
DB_PATH = (
    Path("/home/trading_ceo")
    / "python-trader"
    / "varaha"
    / "data"
    / "varaha_data.duckdb"
)
# Number of most-recent trading days to inspect. Keep small for Step 1.
LOOKBACK_DAYS = 5
# Index to study. We're starting with NIFTY only.
INDEX = "NIFTY"
# Where to save the plot. PNG saved alongside the script for visibility.
PLOT_PATH = Path(__file__).parent / "step01_spot_curve.png"


# ---------------------------------------------------------------------------
# Step A: verify DB
# ---------------------------------------------------------------------------
def verify_db():
    assert DB_PATH.exists(), f"DB not found at {DB_PATH}. Adjust DB_PATH and re-run."
    print(f"DB found at: {DB_PATH}")
    print(f"DB size: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")
    print()


# ---------------------------------------------------------------------------
# Step B: pull last N trading days of NIFTY spot
# ---------------------------------------------------------------------------
def pull_recent_data():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    recent_dates = con.execute(f"""
        SELECT DISTINCT date 
        FROM market_data 
        WHERE index_name = '{INDEX}'
        ORDER BY date DESC 
        LIMIT {LOOKBACK_DAYS}
    """).df()
    assert len(recent_dates) > 0, "No NIFTY rows found in market_data."
    min_date = recent_dates["date"].min()
    df = con.execute(f"""
        SELECT 
            timestamp,
            date,
            time,
            spot,
            india_vix,
            days_to_weekly,
            atm_strike
        FROM market_data
        WHERE index_name = '{INDEX}'
          AND date >= '{min_date}'
        ORDER BY timestamp ASC
    """).df()
    con.close()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    print(f"Pulled {len(df):,} rows across {df['date'].nunique()} dates.")
    print()
    return df


# ---------------------------------------------------------------------------
# Step C: sanity printouts
# ---------------------------------------------------------------------------
def print_sanity_checks(df):
    print("=== Date coverage ===")
    print(f"From: {df['date'].min()}  ->  To: {df['date'].max()}")
    print(f"Distinct dates: {df['date'].nunique()}")
    print()
    print("=== Rows per date ===")
    print(df.groupby("date").size().to_string())
    print()
    print("=== Null counts ===")
    print(df.isna().sum().to_string())
    print()
    print("=== Spot stats ===")
    print(df["spot"].describe().to_string())
    print()
    print("=== VIX stats ===")
    print(df["india_vix"].describe().to_string())
    print()
    print("=== Capture cadence (seconds between consecutive rows, first 10) ===")
    print(df["timestamp"].diff().dt.total_seconds().head(11).tolist())
    print()
    print("=== days_to_weekly distribution ===")
    print(df["days_to_weekly"].value_counts().sort_index().to_string())
    print()
    print("=== Head ===")
    print(df.head(3).to_string())
    print()
    print("=== Tail ===")
    print(df.tail(3).to_string())
    print()


# ---------------------------------------------------------------------------
# Step D: plot
# ---------------------------------------------------------------------------
def plot_spot(df):
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(df["timestamp"], df["spot"], linewidth=0.7)
    ax.set_title(
        f"{INDEX} spot — last {df['date'].nunique()} trading days (Sandwich Step 1)"
    )
    ax.set_ylabel("Spot")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(PLOT_PATH, dpi=100)
    plt.close(fig)
    print(f"Plot saved to: {PLOT_PATH}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Sandwich Step 1 — Connect & Inspect")
    print("=" * 60)
    print()
    verify_db()
    df = pull_recent_data()
    print_sanity_checks(df)
    plot_spot(df)
    print("Sandwich Step 1 complete. Capture outputs and report back.")
    print("Do not proceed to Step 2.")


if __name__ == "__main__":
    main()
