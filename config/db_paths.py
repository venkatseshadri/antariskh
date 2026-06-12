import os
from pathlib import Path

_DATA_DIR = Path("/home/trading_ceo/python-trader/varaha/data")


def _sandbox_dir():
    d = os.environ.get("BRAHMAND_SANDBOX", "")
    return Path(d) if d else None


def get_v31_db_path(index: str) -> Path:
    sb = _sandbox_dir()
    if sb:
        return (
            sb / f"varaha_data{'_sensex' if index.upper() == 'SENSEX' else ''}.duckdb"
        )
    if index.upper() == "SENSEX":
        return _DATA_DIR / "varaha_data_sensex.duckdb"
    return _DATA_DIR / "varaha_data.duckdb"


def get_multitf_db_path(index: str) -> Path:
    sb = _sandbox_dir()
    if sb:
        return sb / f"market_data_multitf_{index.lower()}.duckdb"
    return _DATA_DIR / f"market_data_multitf_{index.lower()}.duckdb"
