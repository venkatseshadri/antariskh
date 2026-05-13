"""Strategy Architect tools — Option Chain & Greeks from DuckDB.

Read-only queries against varaha_data.duckdb and varaha_data_sensex.duckdb.
The Quantitative Options Analyst uses these to select strikes and evaluate risk.

Uses BaseTool subclass (not @tool decorator) for strict args_schema enforcement
in CrewAI 1.14.4.
"""

from pathlib import Path
from typing import Type

from pydantic import BaseModel, Field
from crewai.tools import BaseTool

DUCKDB_DATA_DIR = Path("/home/trading_ceo/python-trader/varaha/data")
DUCKDB_NIFTY = DUCKDB_DATA_DIR / "varaha_data.duckdb"
DUCKDB_SENSEX = DUCKDB_DATA_DIR / "varaha_data_sensex.duckdb"


class MarketDataInput(BaseModel):
    symbol: str = Field(
        default="NIFTY",
        description="The index symbol to analyze. Must be either 'NIFTY' or 'SENSEX'. Defaults to 'NIFTY' if the user does not specify.",
    )


def _resolve_db(symbol: str) -> Path:
    safe = symbol.upper().strip()
    return DUCKDB_SENSEX if safe == "SENSEX" else DUCKDB_NIFTY


# ── Tool 1: Option Chain Fetcher ─────────────────────────────────────────────


class FetchOptionChainTool(BaseTool):
    name: str = "Fetch Option Chain from DuckDB"
    description: str = (
        "Fetches the latest option chain data (Strikes, CE/PE, LTP, IV) from DuckDB. "
        "Use this to select specific strike prices for your strategy."
    )
    args_schema: Type[BaseModel] = MarketDataInput

    def _run(self, symbol: str = "NIFTY") -> str:
        safe_symbol = symbol.upper()
        db_path = _resolve_db(safe_symbol)

        if not db_path.exists():
            return f"Error: Database not found at {db_path}"

        try:
            import duckdb

            con = duckdb.connect(str(db_path), read_only=True)
            query = """
                SELECT strike, strike_offset, option_type, ltp, iv
                FROM option_snapshots
                WHERE timestamp = (SELECT MAX(timestamp) FROM option_snapshots)
                ORDER BY strike ASC
            """
            df = con.execute(query).fetchdf()
        except Exception as e:
            return f"Error querying option chain for {safe_symbol}: {e}"
        finally:
            if "con" in locals():
                con.close()

        if df.empty:
            return f"No option chain data found for {safe_symbol} in {db_path}"

        lines = [f"Latest Option Chain for {safe_symbol}:"]
        for _, row in df.iterrows():
            lines.append(
                f"  Strike={int(row['strike']):,}  "
                f"Offset={int(row['strike_offset'])}  "
                f"Type={row['option_type']}  "
                f"LTP={row['ltp']}  "
                f"IV={row['iv']}"
            )
        return "\n".join(lines)


# ── Tool 2: Aggregate Greeks Fetcher ─────────────────────────────────────────


class FetchGreeksTool(BaseTool):
    name: str = "Fetch Aggregate Greeks from DuckDB"
    description: str = (
        "Fetches the latest aggregate Greeks (Delta, Gamma, Vega, Theta) from DuckDB. "
        "Use this to evaluate the risk and time-decay potential of the market. "
        "Theta positive = time decay profit for option sellers. "
        "Delta near 0 = market-neutral position. "
        "Gamma negative = short-gamma risk near expiry."
    )
    args_schema: Type[BaseModel] = MarketDataInput

    def _run(self, symbol: str = "NIFTY") -> str:
        safe_symbol = symbol.upper()
        db_path = _resolve_db(safe_symbol)

        if not db_path.exists():
            return f"Error: Database not found at {db_path}"

        try:
            import duckdb

            con = duckdb.connect(str(db_path), read_only=True)
            query = """
                SELECT agg_delta, agg_gamma, agg_vega, agg_theta,
                       wings_delta, body_delta
                FROM market_data
                WHERE agg_delta IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
            """
            df = con.execute(query).fetchdf()
        except Exception as e:
            return f"Error querying Greeks for {safe_symbol}: {e}"
        finally:
            if "con" in locals():
                con.close()

        if df.empty:
            return f"No Greeks data found for {safe_symbol} in {db_path}"

        g = df.iloc[0]
        return (
            f"Latest Aggregate Greeks for {safe_symbol}:\n"
            f"  Net Delta: {g['agg_delta']}  (0 = neutral, ± = directional)\n"
            f"  Net Gamma: {g['agg_gamma']}  (− = short gamma risk near expiry)\n"
            f"  Net Vega:  {g['agg_vega']}   (− = loses if VIX spikes)\n"
            f"  Net Theta: {g['agg_theta']}  (+ = daily time-decay profit)\n"
            f"  Wings Delta: {g['wings_delta']}  |  Body Delta: {g['body_delta']}"
        )
