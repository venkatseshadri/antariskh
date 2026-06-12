"""Resolve rotating option tokens from scrip master files at feed startup.

Downloads/reads fresh master CSVs from Shoonya, finds near-ATM weekly/monthly
option contracts for NIFTY and SENSEX.

Usage:
    tokens = TokenResolver().resolve_weekly_options()
    # → [dict(exchange='NFO', token='57049', tsym='NIFTY02JUN26C23950', ...), ...]
"""

import csv
import io
import zipfile
import tempfile
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional

MASTER_DIR = Path(__file__).resolve().parent.parent / "data" / "masters"
MASTER_URLS = {
    "NFO": "https://api.shoonya.com/NFO_symbols.txt.zip",
    "BFO": "https://api.shoonya.com/BFO_symbols.txt.zip",
    "MCX": "https://api.shoonya.com/MCX_symbols.txt.zip",
    "NSE": "https://api.shoonya.com/NSE_symbols.txt.zip",
    "BSE": "https://api.shoonya.com/BSE_symbols.txt.zip",
}

NIFTY_WEEKDAY = 1  # Tuesday
SENSEX_WEEKDAY = 3  # Thursday

MONTH_NAMES = {
    1: "JAN",
    2: "FEB",
    3: "MAR",
    4: "APR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AUG",
    9: "SEP",
    10: "OCT",
    11: "NOV",
    12: "DEC",
}

# Weekly: single-char month. Oct/Nov/Dec → O/N/D, Jan-Sep → digit 1-9
WEEKLY_MONTH = {
    1: "1",
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
    10: "O",
    11: "N",
    12: "D",
}


def _download_master(exchange: str) -> Path:
    MASTER_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{exchange}_symbols.txt"
    path = MASTER_DIR / fname
    if path.exists():
        return path
    import urllib.request

    url = MASTER_URLS.get(exchange)
    if not url:
        raise ValueError(f"No master URL for {exchange}")
    with urllib.request.urlopen(url) as resp:
        with zipfile.ZipFile(io.BytesIO(resp.read())) as zf:
            zf.extract(fname, MASTER_DIR)
    return path


def _broker_weekly_expiries(index: str) -> list[date]:
    """Extract distinct weekly expiry dates from broker master files (holiday-aware).
    Broker master txts list ONLY actually-traded contracts — holiday-aware by construction."""
    exchange = "NFO" if index.upper() == "NIFTY" else "BFO"
    path = MASTER_DIR / f"{exchange}_symbols.txt"
    if not path.exists():
        return []
    expiries = set()
    with open(path) as f:
        for row in csv.DictReader(f):
            if row.get("Instrument") != "OPTIDX":
                continue
            tsym = row.get("TradingSymbol", "")
            # NIFTY: NFO OPTIDX, tsym starts with "NIFTY"
            # SENSEX: BFO OPTIDX, Symbol = "BSXOPT" (not SENSEX50 — different index)
            if index.upper() == "NIFTY":
                if not tsym.upper().startswith("NIFTY"):
                    continue
            elif row.get("Symbol", "") != "BSXOPT":
                continue
            expiry_str = row.get("Expiry", "")
            if not expiry_str:
                continue
            try:
                expiries.add(datetime.strptime(expiry_str, "%d-%b-%Y").date())
            except (ValueError, TypeError):
                continue
    return sorted(expiries)


def resolve_weekly_expiry(index: str = "NIFTY", now: Optional[datetime] = None) -> date:
    """Single expiry oracle — authoritative + holiday-aware by construction.

    Reads scrip_master (broker contract list) to find the nearest unexpired weekly
    expiry. Falls back to simple weekday calc if scrip_master is unavailable.

    Rule: nearest unexpired weekly ≥ today, held until 15:25 IST on expiry day.
    NO early roll for trading — 0DTE IS the trade day (Board directive 06-12).
    Rollover: at/after 15:25 on expiry day → next week.
    """
    if now is None:
        now = datetime.now()
    today = now.date()
    weekday_map = {"NIFTY": 1, "SENSEX": 3}
    weekday = weekday_map.get(index.upper(), 1)

    # Try broker master files first (holiday-aware by construction —
    # the master file lists only actually-traded contracts)
    expiries = _broker_weekly_expiries(index)
    if expiries:
        for expiry in expiries:
            if expiry >= today:
                if expiry == today and (now.hour, now.minute) >= (15, 25):
                    continue
                return expiry

    # Fallback: simple weekday calculation (no <2 day guard — 0DTE IS valid)
    days_ahead = (weekday - today.weekday()) % 7
    if days_ahead == 0 and (now.hour, now.minute) >= (15, 25):
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def _next_expiry(weekday: int) -> date:
    """Thin adapter — delegates to resolve_weekly_expiry for NIFTY/SENSEX."""
    index = "NIFTY" if weekday == NIFTY_WEEKDAY else "SENSEX"
    return resolve_weekly_expiry(index)


def _build_tsym_weekly_nifty(expiry: date, strike: int, opt: str) -> str:
    """NIFTY{DD}{Mmm}{YY}{C/P}{5-digit-strike}  →  NIFTY02JUN26C23950"""
    return (
        f"NIFTY"
        f"{expiry.day:02d}"
        f"{MONTH_NAMES[expiry.month]}"
        f"{str(expiry.year)[-2:]}"
        f"{opt[0]}"  # C or P
        f"{strike}"
    )


def _build_tsym_weekly_sensex(expiry: date, strike: int, opt: str) -> str:
    """SENSEX{YY}{M}{DD}{5-digit-strike}{CE/PE}  →  SENSEX2652975500PE (29-MAY-2026)"""
    return (
        f"SENSEX"
        f"{str(expiry.year)[-2:]}"
        f"{WEEKLY_MONTH[expiry.month]}"
        f"{expiry.day:02d}"
        f"{strike}"
        f"{opt[:2].upper()}"  # CE or PE
    )


def _build_tsym_monthly_sensex(expiry: date, strike: int, opt: str) -> str:
    """SENSEX{YY}{Mmm}{5-digit-strike}{CE/PE}  →  SENSEX26JUN75800PE"""
    return f"SENSEX{str(expiry.year)[-2:]}{MONTH_NAMES[expiry.month]}{strike}{opt[:2].upper()}"


class TokenResolver:
    """Loads master files and resolves rotating option + futures tokens."""

    def __init__(self, nifty_spot: Optional[float] = None, sensex_spot: Optional[float] = None):
        self.nifty_spot = nifty_spot
        self.sensex_spot = sensex_spot
        self._masters: dict[str, dict[(str, str), dict]] = {}
        self._futures: dict[str, dict[str, list[dict]]] = {}
        self._load_masters()

    def _load_masters(self):
        for exchange in ["NFO", "BFO", "MCX"]:
            path = MASTER_DIR / f"{exchange}_symbols.txt"
            if not path.exists():
                _download_master(exchange)
                path = MASTER_DIR / f"{exchange}_symbols.txt"
            if not path.exists():
                print(f"WARNING: master file missing: {path}")
                continue
            idx = {}
            fut = {}
            with open(path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    inst = row.get("Instrument", "")
                    if inst == "OPTIDX":
                        tsym = row.get("TradingSymbol", "")
                        key = (exchange, tsym)
                        idx[key] = {
                            "token": row.get("Token", ""),
                            "strike": float(row.get("StrikePrice", "0")),
                            "opt_type": row.get("OptionType", ""),
                            "expiry": row.get("Expiry", ""),
                            "lot_size": row.get("LotSize", ""),
                            "tsym": tsym,
                            "exchange": exchange,
                            "feed_type": "d",
                        }
                    elif inst in ("FUTIDX", "FUTCOM"):
                        symbol = row.get("Symbol", "").strip()
                        if symbol not in fut:
                            fut[symbol] = []
                        try:
                            expiry_date = datetime.strptime(row["Expiry"], "%d-%b-%Y").date()
                        except (ValueError, KeyError):
                            continue
                        fut[symbol].append(
                            {
                                "token": row.get("Token", ""),
                                "tsym": row.get("TradingSymbol", ""),
                                "expiry": expiry_date,
                                "lot_size": int(row.get("LotSize", 0) or 0),
                                "exchange": exchange,
                                "instrument": inst,
                            }
                        )
            if exchange in ("NFO", "BFO"):
                self._masters[exchange] = idx
            for symbol in fut:
                fut[symbol].sort(key=lambda x: x["expiry"])
            self._futures[exchange] = fut

    def _lookup(self, exchange: str, tsym: str) -> Optional[dict]:
        idx = self._masters.get(exchange, {})
        return idx.get((exchange, tsym))

    def resolve_nearest_future(
        self, product_root: str, exchange: str, _today: Optional[date] = None
    ) -> dict:
        """Resolve nearest unexpired futures contract. Rolls at T-2 before expiry.
        Returns dict with token, tsym, exchange, expiry, lot_size, instrument."""
        fut = self._futures.get(exchange, {}).get(product_root)
        if not fut:
            raise ValueError(f"No futures found for {product_root} on {exchange}")
        today = _today or date.today()
        for i, contract in enumerate(fut):
            if contract["expiry"] >= today:
                if (contract["expiry"] - today).days <= 2 and i + 1 < len(fut):
                    successor = fut[i + 1]
                    if successor["expiry"] >= today:
                        return successor
                return contract
        raise ValueError(
            f"No unexpired futures for {product_root} on {exchange} "
            f"(latest expired {fut[-1]['expiry']})"
        )

    def atm_strike(self, spot: float, gap: int) -> int:
        """Round spot to nearest strike gap. e.g., 23907 → 23900 (gap=50)."""
        return int(round(spot / gap) * gap)

    def resolve_weekly_nifty(self, atm_range: int = 5) -> list[dict]:
        expiry = _next_expiry(NIFTY_WEEKDAY)
        return self._weekly_for_expiry(
            expiry, self.nifty_spot or 23900, 50, "NFO", _build_tsym_weekly_nifty, atm_range
        )

    def resolve_weekly_nifty_for_expiry(self, expiry_date: date, atm_range: int = 5) -> list[dict]:
        return self._weekly_for_expiry(
            expiry_date, self.nifty_spot or 23900, 50, "NFO", _build_tsym_weekly_nifty, atm_range
        )

    def _weekly_for_expiry(self, expiry, spot, gap, exchange, builder, atm_range):
        atm = self.atm_strike(spot, gap)
        tokens = []
        for offset in range(-atm_range, atm_range + 1):
            strike = atm + offset * gap
            for opt in ["CE", "PE"]:
                tsym = builder(expiry, strike, opt)
                row = self._lookup(exchange, tsym)
                if row:
                    row["strike"] = strike
                    row["expiry_date"] = expiry.isoformat()
                    tokens.append(row)
        return tokens

    def resolve_weekly_sensex(self, atm_range: int = 5) -> list[dict]:
        expiry = _next_expiry(SENSEX_WEEKDAY)
        return self._weekly_for_expiry(
            expiry, self.sensex_spot or 75800, 100, "BFO", _build_tsym_weekly_sensex, atm_range
        )

    def resolve_weekly_sensex_for_expiry(self, expiry_date: date, atm_range: int = 5) -> list[dict]:
        return self._weekly_for_expiry(
            expiry_date, self.sensex_spot or 75800, 100, "BFO", _build_tsym_weekly_sensex, atm_range
        )

    def resolve_monthly_sensex(self, atm_range: int = 5) -> list[dict]:
        """SENSEX monthly options — last Thursday of the month."""
        today = date.today()
        # Find next month-end expiry
        expiry = today.replace(day=28) + timedelta(days=4)
        expiry = expiry - timedelta(days=expiry.weekday())
        while expiry.weekday() != 3:  # Thursday
            expiry = expiry + timedelta(days=1)
        spot = self.sensex_spot or 75800
        gap = 100
        atm = self.atm_strike(spot, gap)
        tokens = []
        for offset in range(-atm_range, atm_range + 1):
            strike = atm + offset * gap
            for opt in ["CE", "PE"]:
                tsym = _build_tsym_monthly_sensex(expiry, strike, opt)
                row = self._lookup("BFO", tsym)
                if row:
                    row["strike"] = strike
                    row["expiry_date"] = expiry.isoformat()
                    tokens.append(row)
        return tokens

    def resolve_all(self, nifty_range: int = 5, sensex_range: int = 5) -> list[dict]:
        return (
            self.resolve_weekly_nifty(nifty_range)
            + self.resolve_weekly_sensex(sensex_range)
            + self.resolve_monthly_sensex(sensex_range)
        )
