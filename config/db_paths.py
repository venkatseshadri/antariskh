from pathlib import Path

_DATA_DIR = Path("/home/trading_ceo/python-trader/varaha/data")


def get_v31_db_path(index: str) -> Path:
    if index.upper() == "SENSEX":
        return _DATA_DIR / "varaha_data_sensex.duckdb"
    return _DATA_DIR / "varaha_data.duckdb"


def get_multitf_db_path(index: str) -> Path:
    return _DATA_DIR / f"market_data_multitf_{index.lower()}.duckdb"
