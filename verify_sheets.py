"""Writes verify_trades.py output to a Google Sheet for human review — no
grepping log files. Reuses the existing trade-google-sheet-bot service
account (already used by python-trader/orbiter/bot/sheets.py) but targets
a DEDICATED spreadsheet, not orbiter's own "trade_log" — keeps this
validator's output isolated from orbiter's live trading bot data.

One tab per system (ATOM / PROTON / PROTON+ / NEUTRON). Rows are appended,
never rewritten — this sheet is itself a ledger: if a row is in here, this
tool actually queried a real source table/file for it.
"""

import os
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
CREDS_PATH = Path("/home/trading_ceo/python-trader/orbiter/bot/credentials.json")
SHEET_NAME = "ATOM Trade Validation Ledger"
SHARE_WITH_EMAIL = "venkatseshadri@gmail.com"

HEADER = ["Checked At", "System", "Trade ID / Entry TS", "Event", "Strike(s)",
          "Opt Type", "Recorded Price", "Independent Price", "Verdict", "Detail"]

ROW_KEYS = ["checked_at", "system", "trade_id", "event", "strike",
            "opt_type", "recorded_price", "independent_price", "verdict", "detail"]


def _client() -> gspread.Client:
    creds = Credentials.from_service_account_file(str(CREDS_PATH), scopes=SCOPE)
    return gspread.authorize(creds)


def _get_or_create_book(client: gspread.Client) -> gspread.Spreadsheet:
    try:
        return client.open(SHEET_NAME)
    except gspread.SpreadsheetNotFound:
        book = client.create(SHEET_NAME)
        book.share(SHARE_WITH_EMAIL, perm_type="user", role="writer")
        return book


def _get_or_create_worksheet(book: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        return book.worksheet(title)
    except gspread.WorksheetNotFound:
        return book.add_worksheet(title=title, rows="2000", cols=str(len(HEADER)))


def _ensure_header(sheet: gspread.Worksheet):
    if not sheet.row_values(1):
        sheet.insert_row(HEADER, 1)


def write_rows(system: str, rows: list[dict]) -> int:
    """Appends `rows` (from verify_trades.py) to `system`'s tab. Returns
    the number of rows written (0 if `rows` is empty — no sheet call made)."""
    if not rows:
        return 0
    client = _client()
    book = _get_or_create_book(client)
    sheet = _get_or_create_worksheet(book, system)
    _ensure_header(sheet)
    values = [[r.get(k, "") for k in ROW_KEYS] for r in rows]
    sheet.append_rows(values, value_input_option="USER_ENTERED")
    return len(values)


def write_all(results_by_system: dict[str, list[dict]]) -> dict[str, int]:
    return {system: write_rows(system, rows) for system, rows in results_by_system.items()}


if __name__ == "__main__":
    from verify_trades import run_all
    counts = write_all(run_all())
    for system, n in counts.items():
        print(f"{system}: {n} rows written")
