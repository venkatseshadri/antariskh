"""Contract Specialist tools — Symbol resolution, lot size, expiry mapping.

The "Librarian" of the trading system.
Takes abstract concepts (0.15 Delta, NIFTY, CE) and returns concrete contracts
with exact trading symbols, lot sizes, expiry dates, and LTP.

Uses ATTACH pattern: queries static_metadata.db (scrip_master) + live DuckDB
(varaha_data.duckdb) simultaneously without lock contention.
"""

from pathlib import Path
from datetime import datetime, timedelta
from typing import Type, List, Optional, Dict, Any

from pydantic import BaseModel, Field
from crewai.tools import BaseTool

# ── Database paths ───────────────────────────────────────────────────────────
STATIC_DB = Path("/home/trading_ceo/antariksh/data/static_metadata.db")
LIVE_DB = {
    "NIFTY": Path("/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"),
    "SENSEX": Path(
        "/home/trading_ceo/python-trader/varaha/data/varaha_data_sensex.duckdb"
    ),
}
FALLBACK_LOT_SIZE = {"NIFTY": 65, "SENSEX": 20}


# ── Shared utilities ─────────────────────────────────────────────────────────


def get_weekly_expiry() -> str:
    """Return current weekly NIFTY expiry date in DDMMMYYYY format, e.g. '15MAY2026'."""
    today = datetime.now()
    days_until_thu = (3 - today.weekday()) % 7
    if days_until_thu == 0 and today.hour >= 15:
        days_until_thu = 7
    expiry = today + timedelta(days=days_until_thu)
    if (expiry - today).days < 2:
        expiry = expiry + timedelta(days=7)
    return expiry.strftime("%d%b%Y").upper()


def build_tsym(symbol: str, strike: int, option_type: str) -> str:
    """Build Shoonya trading symbol: NIFTY15MAY202625500CE."""
    safe = symbol.upper().strip()
    opt = option_type.upper().strip()
    expiry = get_weekly_expiry()
    return f"{safe}{expiry}{strike}{opt}"


def _get_nonblocking_conn(live_db_path: Path):
    """Open a DuckDB connection with static metadata + live data ATTACHed.

    Uses :memory: primary + ATTACH to avoid lock contention with the capture
    script that holds an exclusive write lock on the live database.
    """
    import duckdb

    con = duckdb.connect(":memory:")

    # Attach static metadata (scrip_master) — never locked by capture script
    if STATIC_DB.exists():
        con.execute(f"ATTACH '{STATIC_DB}' AS static (READ_ONLY)")

    # Attach live market data (option_snapshots, market_data) in read-only mode
    # This bypasses the exclusive write lock held by the capture script
    if live_db_path.exists():
        con.execute(f"ATTACH '{live_db_path}' AS live (READ_ONLY)")

    return con


def get_lot_size(symbol: str) -> int:
    """Return lot size from scrip_master or fallback."""
    safe = symbol.upper().strip()
    try:
        import duckdb

        if STATIC_DB.exists():
            con = duckdb.connect(str(STATIC_DB), read_only=True)
            row = con.execute(
                "SELECT lot_size FROM scrip_master WHERE symbol = ? LIMIT 1",
                [safe],
            ).fetchone()
            con.close()
            if row:
                return int(row[0])
    except Exception:
        pass
    return FALLBACK_LOT_SIZE.get(safe, 50)


# ── Pydantic Schemas ─────────────────────────────────────────────────────────


class ResolveContractInput(BaseModel):
    symbol: str = Field(
        default="NIFTY", description="The index symbol: NIFTY or SENSEX."
    )
    strike: int = Field(
        ...,
        description="The exact strike price to resolve, e.g., 25000. Use 0 if you want ATM resolved automatically.",
    )
    option_type: str = Field(
        default="CE",
        description="CE (Call) or PE (Put). Ignored if requesting ALL for both sides of a spread.",
    )
    request_type: str = Field(
        default="SINGLE",
        description="SINGLE (one contract), PAIR (ATM CE + ATM PE for Iron Butterfly), or SPREAD (OTM CE + OTM PE for Iron Condor).",
    )


class TradePlanEnrichInput(BaseModel):
    symbol: str = Field(default="NIFTY", description="Index symbol: NIFTY or SENSEX.")
    legs: List[dict] = Field(
        ...,
        description=(
            "List of leg specifications from the Strategy Architect. "
            "Each leg: {action: BUY/SELL, strike: int, option_type: CE/PE, quantity: int (lots)}"
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 1: Resolve Single / Pair / Spread Contracts
# ══════════════════════════════════════════════════════════════════════════════


class ResolveContractTool(BaseTool):
    name: str = "resolve_contract"
    description: str = (
        "Resolve abstract contract specifications into exact trading symbols, "
        "lot sizes, LTP, and expiry dates using DuckDB data.\n\n"
        "SINGLE: Returns one contract (e.g., ATM CE). Use strike=0 for ATM auto-resolution.\n"
        "PAIR: Returns ATM CE + ATM PE (for Iron Butterfly body). Use strike=0.\n"
        "SPREAD: Returns OTM CE + OTM PE at the specified strike offsets (for Iron Condor). "
        "Pass strike as the ATM center — the tool finds OTM strikes.\n\n"
        "ALWAYS call this BEFORE sending to the Portfolio Manager — the PM needs "
        "exact symbols and lot sizes to check margin, not abstract concepts."
    )
    args_schema: Type[BaseModel] = ResolveContractInput

    def _run(
        self,
        symbol: str = "NIFTY",
        strike: int = 0,
        option_type: str = "CE",
        request_type: str = "SINGLE",
    ) -> str:
        import json

        safe_symbol = symbol.upper().strip()
        live_path = LIVE_DB.get(safe_symbol)
        if not live_path:
            return json.dumps({"error": f"Unknown symbol: {safe_symbol}"})

        lot = get_lot_size(safe_symbol)
        expiry = get_weekly_expiry()

        try:
            con = _get_nonblocking_conn(live_path)
            # Try static scrip_master first, fall back to live option_snapshots
            spot_row = con.execute(
                "SELECT spot FROM live.market_data WHERE spot IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            spot = float(spot_row[0]) if spot_row else 0

            df = con.execute(
                "SELECT strike, strike_offset, option_type, ltp, iv, oi "
                "FROM live.option_snapshots "
                "WHERE timestamp = (SELECT MAX(timestamp) FROM live.option_snapshots) "
                "ORDER BY strike ASC"
            ).fetchdf()
        except Exception as e:
            return json.dumps({"error": f"Database query failed: {e}"})
        finally:
            if "con" in locals():
                con.close()

        if df.empty:
            return json.dumps({"error": f"No option chain data for {safe_symbol}"})

        # Resolve ATM if strike=0
        atm_strike = strike if strike > 0 else round(spot / 50) * 50

        atm_row = df[(df["strike"] == atm_strike) & (df["strike_offset"] == 0)]

        def _make_contract(stk: int, opt: str) -> dict:
            match = df[(df["strike"] == stk) & (df["option_type"] == opt)]
            ltp_raw = float(match.iloc[0]["ltp"]) if not match.empty else 0
            iv_raw = float(match.iloc[0]["iv"]) if not match.empty else 0
            oi_raw = int(match.iloc[0]["oi"]) if not match.empty else 0
            return {
                "tsym": build_tsym(safe_symbol, stk, opt),
                "strike": stk,
                "option_type": opt,
                "ltp": round(ltp_raw, 2),
                "iv": round(iv_raw, 2),
                "oi": oi_raw,
                "expiry": expiry,
                "lot_size": lot,
                "per_lot_value": round(ltp_raw * lot, 2),
            }

        if request_type == "SINGLE":
            contract = _make_contract(atm_strike, option_type)
        elif request_type == "PAIR":
            contract = {
                "ce": _make_contract(atm_strike, "CE"),
                "pe": _make_contract(atm_strike, "PE"),
            }
        elif request_type == "SPREAD":
            # Find OTM strikes ~200pts out each side
            otm_put_strike = atm_strike - 200
            otm_call_strike = atm_strike + 200
            contract = {
                "put_leg": _make_contract(otm_put_strike, "PE"),
                "call_leg": _make_contract(otm_call_strike, "CE"),
            }
        else:
            contract = {"error": f"Unknown request_type: {request_type}"}

        result = {
            "symbol": safe_symbol,
            "spot": spot,
            "atm_strike": atm_strike,
            "expiry": expiry,
            "lot_size": lot,
            "request_type": request_type,
            "contracts": contract,
        }
        return json.dumps(result, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 2: Enrich Architect Trade Plan with Contracts
# ══════════════════════════════════════════════════════════════════════════════


class EnrichTradePlanTool(BaseTool):
    name: str = "enrich_trade_plan"
    description: str = (
        "Take a Strategy Architect's leg list and enrich every leg with exact "
        "trading symbols, lot sizes, LTP per leg, and per-lot value.\n\n"
        "Use this AFTER the Architect has selected strikes. The enriched output "
        "is the ONLY format the Portfolio Manager accepts for margin checks.\n\n"
        "Input: symbol + legs [{action, strike, option_type, quantity}].\n"
        "Output: same legs but enriched with tsym, ltp, lot_size, per_lot_value, expiry.\n\n"
        "If any leg's strike is missing from the option chain, it is flagged and excluded."
    )
    args_schema: Type[BaseModel] = TradePlanEnrichInput

    def _run(self, symbol: str = "NIFTY", legs: list = None) -> str:
        import json

        if not legs:
            return json.dumps({"error": "No legs provided"})

        safe_symbol = symbol.upper().strip()
        live_path = LIVE_DB.get(safe_symbol)
        if not live_path:
            return json.dumps({"error": f"Unknown symbol: {safe_symbol}"})

        lot = get_lot_size(safe_symbol)
        expiry = get_weekly_expiry()
        token_cache = {}  # (strike, opt) → token

        try:
            con = _get_nonblocking_conn(live_path)

            # Pre-load scrip_master tokens if available
            try:
                master_rows = con.execute(
                    "SELECT strike, option_type, token FROM static.scrip_master "
                    "WHERE symbol = ? AND expiry = ?",
                    [safe_symbol, expiry],
                ).fetchall()
                for mr in master_rows:
                    token_cache[(int(mr[0]), str(mr[1]))] = mr[2]
            except Exception:
                pass  # static DB may not exist yet

            df = con.execute(
                "SELECT strike, option_type, ltp, iv, oi "
                "FROM live.option_snapshots "
                "WHERE timestamp = (SELECT MAX(timestamp) FROM live.option_snapshots)"
            ).fetchdf()
        except Exception as e:
            return json.dumps({"error": f"Database query failed: {e}"})
        finally:
            if "con" in locals():
                con.close()

        enriched_legs = []
        missing_legs = []
        total_margin_estimate = 0

        for i, leg in enumerate(legs):
            stk = int(leg.get("strike", 0))
            opt = leg.get("option_type", "CE").upper().strip()
            qty = int(leg.get("quantity", 1))
            action = leg.get("action", "SELL").upper().strip()

            match = df[(df["strike"] == stk) & (df["option_type"] == opt)]
            if match.empty:
                missing_legs.append(
                    {
                        "index": i,
                        "strike": stk,
                        "option_type": opt,
                        "error": "Strike not found in option chain",
                    }
                )
                continue

            row = match.iloc[0]
            ltp_val = float(row["ltp"])
            broker_token = token_cache.get((stk, opt))  # From scrip_master
            enriched = {
                "index": i,
                "action": action,
                "tsym": build_tsym(safe_symbol, stk, opt),
                "token": broker_token,
                "strike": stk,
                "option_type": opt,
                "quantity_lots": qty,
                "quantity_units": qty * lot,
                "ltp": round(ltp_val, 2),
                "iv": round(float(row["iv"]), 2),
                "oi": int(row["oi"]),
                "lot_size": lot,
                "expiry": expiry,
                "per_lot_value": round(ltp_val * lot, 2),
                "total_value": round(ltp_val * lot * qty, 2),
            }
            enriched_legs.append(enriched)

            # SELL legs = premium received (credit), BUY legs = premium paid (debit)
            if action == "SELL":
                total_margin_estimate += ltp_val * lot * qty

        total_units = sum(leg["quantity_units"] for leg in enriched_legs)
        net_premium = sum(
            (leg["ltp"] * leg["quantity_units"])
            * (1 if leg["action"] == "SELL" else -1)
            for leg in enriched_legs
        )

        result = {
            "symbol": safe_symbol,
            "expiry": expiry,
            "lot_size": lot,
            "total_legs_requested": len(legs),
            "total_legs_resolved": len(enriched_legs),
            "missing_legs": missing_legs,
            "total_units": total_units,
            "net_premium": round(net_premium, 2),
            "margin_estimate": round(total_margin_estimate, 2),
            "legs": enriched_legs,
        }
        return json.dumps(result, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 3: Single Contract Lookup — The Librarian's primary hammer
# ══════════════════════════════════════════════════════════════════════════════


class SymbolLookupInput(BaseModel):
    index_name: str = Field(
        default="NIFTY",
        description="Index name: NIFTY, BANKNIFTY, FINNIFTY, or SENSEX.",
    )
    strike: int = Field(
        ..., description="The exact strike price requested by the Architect."
    )
    option_type: str = Field(..., description="CE or PE.")
    expiry_offset: int = Field(
        default=0,
        description=(
            "CRITICAL for Calendar Spreads: 0 = nearest current expiry (SELL leg), "
            "1 = next expiry (BUY leg). The tool discovers available expiries from "
            "scrip_master — you do NOT need to know exact dates. "
            "Omit (default 0) for non-calendar strategies."
        ),
    )


class LibrarianContractTool(BaseTool):
    name: str = "contract_librarian_lookup"
    description: str = (
        "Find the exact Shoonya trading symbol, token ID, lot size, and expiry "
        "for a specific index + strike + option_type combination.\n\n"
        "Uses the lock-free ATTACH pattern: queries static_metadata.db (Scrip Master) "
        "while optionally verifying ATM strike against live market data.\n\n"
        "CRITICAL for Calendar Spreads (Horizontal Spreads):\n"
        "Use expiry_offset=0 for the SELL (near-term) leg.\n"
        "Use expiry_offset=1 for the BUY (far-term) leg.\n"
        "The tool discovers available expiries automatically — you do NOT need to "
        "know exact dates. The offset selects: 0 = nearest, 1 = next, 2 = month.\n\n"
        "NEVER resolve two legs of a Calendar Spread in the same expiry — that "
        "creates a wash trade with zero Greek exposure.\n\n"
        "Available expiries are returned in the response for verification."
    )
    args_schema: Type[BaseModel] = SymbolLookupInput

    def _run(
        self,
        index_name: str = "NIFTY",
        strike: int = 0,
        option_type: str = "CE",
        expiry_offset: int = 0,
    ) -> str:
        import json

        safe_index = index_name.upper().strip()
        opt = option_type.upper().strip()

        try:
            con = _get_nonblocking_conn(LIVE_DB.get(safe_index, LIVE_DB["NIFTY"]))

            # Discover available expiries for this index from scrip_master
            expiries = con.execute(
                "SELECT DISTINCT expiry FROM static.scrip_master "
                "WHERE symbol = ? AND expiry >= CURRENT_DATE "
                "ORDER BY expiry ASC",
                [safe_index],
            ).fetchall()

            # Select target expiry by offset
            if expiries and expiry_offset < len(expiries):
                target_expiry = str(expiries[expiry_offset][0])
                row = con.execute(
                    "SELECT token, tsym, lot_size, expiry FROM static.scrip_master "
                    "WHERE symbol = ? AND strike = ? AND option_type = ? "
                    "AND expiry = ?",
                    [safe_index, float(strike), opt, target_expiry],
                ).fetchone()

                if row:
                    con.close()
                    return json.dumps(
                        {
                            "token": row[0],
                            "trading_symbol": row[1],
                            "lot_size": row[2],
                            "expiry": str(row[3]),
                            "strike": strike,
                            "option_type": opt,
                            "expiry_offset": expiry_offset,
                            "available_expiries": [str(e[0]) for e in expiries[:3]],
                            "source": "scrip_master",
                            "status": "SUCCESS",
                        },
                        indent=2,
                    )

            # Fallback: try without expiry filter (original behavior)
            if expiry_offset == 0:
                row = con.execute(
                    "SELECT token, tsym, lot_size, expiry FROM static.scrip_master "
                    "WHERE symbol = ? AND strike = ? AND option_type = ? "
                    "AND expiry >= CURRENT_DATE "
                    "ORDER BY expiry ASC LIMIT 1",
                    [safe_index, float(strike), opt],
                ).fetchone()

                if row:
                    con.close()
                    return json.dumps(
                        {
                            "token": row[0],
                            "trading_symbol": row[1],
                            "lot_size": row[2],
                            "expiry": str(row[3]),
                            "strike": strike,
                            "option_type": opt,
                            "source": "scrip_master",
                            "status": "SUCCESS",
                        },
                        indent=2,
                    )

            # Last resort: live option_snapshots
            if expiry_offset == 0:
                row2 = con.execute(
                    "SELECT ltp, iv, oi FROM live.option_snapshots "
                    "WHERE strike = ? AND option_type = ? "
                    "AND timestamp = "
                    "(SELECT MAX(timestamp) FROM live.option_snapshots) LIMIT 1",
                    [float(strike), opt],
                ).fetchone()
            else:
                row2 = None

            con.close()

            if row2:
                expiry = get_weekly_expiry()
                tsym = build_tsym(safe_index, strike, opt)
                lot = get_lot_size(safe_index)
                return json.dumps(
                    {
                        "token": None,
                        "trading_symbol": tsym,
                        "lot_size": lot,
                        "expiry": expiry,
                        "strike": strike,
                        "option_type": opt,
                        "ltp": round(row2[0], 2) if row2[0] else None,
                        "iv": round(row2[1], 2) if row2[1] else None,
                        "source": "live_option_snapshots",
                        "warning": "Token missing — scrip_master not available for this strike",
                        "status": "SUCCESS",
                    },
                    indent=2,
                )

            return json.dumps(
                {
                    "status": "NOT_FOUND",
                    "error": (
                        f"No matching contract for {safe_index} {strike}{opt} "
                        f"at expiry_offset={expiry_offset}. "
                        f"Available expiries: {[str(e[0]) for e in expiries][:5]}"
                    ),
                }
            )

        except Exception as e:
            return json.dumps({"status": "ERROR", "error": str(e)[:300]})
