"""SQLite State Manager — Persist BrahmandState across restarts."""

import sqlite3
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from brahmand.state import BrahmandState


class StateManager:
    """Manage BrahmandState persistence via SQLite."""

    def __init__(self, db_path: Optional[str] = None, verbose: bool = False):
        """Init SQLite connection and create schema if needed.

        Args:
            db_path: SQLite file path. Defaults to .brahmand_data/state.db
            verbose: Print operations
        """
        self.verbose = verbose
        self.db_path = db_path or str(
            Path.home() / "trading_ceo/antariksh/.brahmand_data/state.db"
        )

        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Create connection
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

        # Create schema
        self._init_schema()

        if self.verbose:
            print(f"✓ StateManager initialized at {self.db_path}")

    def _init_schema(self) -> None:
        """Create brahmand_state table if it doesn't exist."""
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS brahmand_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                state_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                session_date TEXT,
                UNIQUE(session_date)
            )
            """
        )
        self.conn.commit()

    def save_state(self, state: BrahmandState, session_date: Optional[str] = None) -> bool:
        """Save state to SQLite.

        Args:
            state: BrahmandState instance
            session_date: Date key (e.g., "2026-05-15"). Defaults to today.

        Returns:
            True if saved successfully
        """
        session_date = session_date or datetime.now().strftime("%Y-%m-%d")
        state_json = state.model_dump_json()

        try:
            self.cursor.execute(
                """
                INSERT OR REPLACE INTO brahmand_state (state_json, session_date, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (state_json, session_date),
            )
            self.conn.commit()

            if self.verbose:
                print(f"  ✓ State saved for {session_date}")

            return True
        except Exception as e:
            if self.verbose:
                print(f"  ⚠ Failed to save state: {e}")
            return False

    def load_latest_state(self) -> Optional[BrahmandState]:
        """Load the most recent state."""
        try:
            self.cursor.execute(
                "SELECT state_json FROM brahmand_state ORDER BY updated_at DESC LIMIT 1"
            )
            row = self.cursor.fetchone()

            if not row:
                if self.verbose:
                    print("  ⚠ No state found — creating fresh")
                return BrahmandState()

            state = BrahmandState.model_validate_json(row[0])

            if self.verbose:
                print(f"  ✓ Loaded state: PV=₹{state.portfolio_value:,.0f}, P&L=₹{state.daily_pnl:+,.0f}")

            return state

        except Exception as e:
            if self.verbose:
                print(f"  ⚠ Failed to load state: {e}")
            return BrahmandState()

    def load_state_for_date(self, date: str) -> Optional[BrahmandState]:
        """Load state for a specific date.

        Args:
            date: Date string (e.g., "2026-05-13")

        Returns:
            BrahmandState or None
        """
        try:
            self.cursor.execute(
                "SELECT state_json FROM brahmand_state WHERE session_date = ?", (date,)
            )
            row = self.cursor.fetchone()

            if not row:
                return None

            return BrahmandState.model_validate_json(row[0])

        except Exception as e:
            if self.verbose:
                print(f"  ⚠ Failed to load state for {date}: {e}")
            return None

    def get_all_states(self, limit: int = 30) -> list:
        """Get recent state snapshots (for trend analysis).

        Args:
            limit: Max number of snapshots to return

        Returns:
            List of {date, portfolio_value, daily_pnl, active_trades_count}
        """
        try:
            self.cursor.execute(
                """
                SELECT session_date, state_json FROM brahmand_state
                ORDER BY session_date DESC LIMIT ?
                """,
                (limit,),
            )
            rows = self.cursor.fetchall()

            snapshots = []
            for row in rows:
                state = BrahmandState.model_validate_json(row[1])
                snapshots.append(
                    {
                        "date": row[0],
                        "portfolio_value": state.portfolio_value,
                        "daily_pnl": state.daily_pnl,
                        "active_trades_count": len(state.active_trades),
                        "margin_used": state.margin_used,
                    }
                )

            return snapshots

        except Exception as e:
            if self.verbose:
                print(f"  ⚠ Failed to fetch snapshots: {e}")
            return []

    def clear(self) -> None:
        """Clear all states (for testing)."""
        try:
            self.cursor.execute("DELETE FROM brahmand_state")
            self.conn.commit()
            if self.verbose:
                print("  ✓ Cleared all states")
        except Exception as e:
            if self.verbose:
                print(f"  ⚠ Failed to clear: {e}")

    def close(self) -> None:
        """Close SQLite connection."""
        try:
            self.conn.close()
            if self.verbose:
                print("  ✓ StateManager closed")
        except Exception:
            pass
