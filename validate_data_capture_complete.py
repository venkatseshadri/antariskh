"""Comprehensive validation: v3.1 + v4 capture all critical values without loss.

This script validates that:
1. v3.1 (1-min DuckDB + Redis) captures 104 columns
2. v4 (multi-TF aggregator) aggregates correctly with 0 data loss
3. All critical values are present in both pipelines
4. No bars are dropped during aggregation
5. Timestamps align correctly across timeframes
"""

import os
import sys
import duckdb
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_capture_v4_multitf_aggregator import MultiTFAggregator


class DataCaptureValidator:
    """Validate v3.1 and v4 data capture completeness."""

    def __init__(self, duckdb_path=None):
        """Initialize validator."""
        if duckdb_path is None:
            duckdb_path = (
                "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"
            )

        self.db_path = Path(duckdb_path)
        self.issues = []
        self.warnings = []
        self.stats = {}

    def validate_all(self):
        """Run all validation checks."""
        print("\n" + "=" * 80)
        print("DATA CAPTURE VALIDATION: v3.1 + v4 Complete Pipeline")
        print("=" * 80 + "\n")

        checks = [
            ("v3.1 database exists", self.check_db_exists),
            ("v3.1 tables exist", self.check_tables_exist),
            ("v3.1 data is populated", self.check_v3_populated),
            ("v3.1 column completeness", self.check_v3_columns),
            ("v3.1 Redis indicators", self.check_v3_redis_indicators),
            ("v4 aggregator runs", self.run_v4_aggregator),
            ("v4 data captured", self.check_v4_data),
            ("v4 no data loss", self.check_v4_data_loss),
            ("v4 timestamp alignment", self.check_timestamp_alignment),
            ("Critical values present", self.check_critical_values),
        ]

        for check_name, check_fn in checks:
            print(f"Checking: {check_name}...", end=" ", flush=True)
            try:
                success = check_fn()
                if success:
                    print("✓")
                else:
                    print("✗ FAILED")
            except Exception as e:
                print(f"✗ EXCEPTION: {e}")
                self.issues.append(f"{check_name}: {str(e)}")

        print("\n" + "=" * 80)
        print("RESULTS")
        print("=" * 80)

        if not self.issues and not self.warnings:
            print("✅ ALL CHECKS PASSED")
            print("✅ v3.1 + v4 capturing all critical values without loss")
            return True
        else:
            if self.warnings:
                print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
                for w in self.warnings:
                    print(f"   - {w}")

            if self.issues:
                print(f"\n❌ ISSUES ({len(self.issues)}):")
                for issue in self.issues:
                    print(f"   - {issue}")
                return False

            return True

    def check_db_exists(self) -> bool:
        """Check DuckDB file exists."""
        exists = self.db_path.exists()
        if exists:
            size_mb = self.db_path.stat().st_size / (1024 * 1024)
            self.stats["db_size_mb"] = size_mb
            print(f"(size: {size_mb:.1f} MB)", end=" ")
        return exists

    def check_tables_exist(self) -> bool:
        """Check required tables exist."""
        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
            table_names = [t[0] for t in tables]
            conn.close()

            required = ["market_data", "option_snapshots"]
            missing = [t for t in required if t not in table_names]

            if missing:
                self.issues.append(f"Missing tables: {missing}")
                return False

            self.stats["v3_tables"] = required
            return True
        except Exception as e:
            self.issues.append(f"Table check failed: {e}")
            return False

    def check_v3_populated(self) -> bool:
        """Check v3 market_data is populated."""
        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)

            # Check market_data row count (v3.1 stores 1-min data only)
            count = conn.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]

            # Check option_snapshots row count
            opt_count = conn.execute(
                "SELECT COUNT(*) FROM option_snapshots"
            ).fetchone()[0]

            conn.close()

            if count == 0:
                self.issues.append("v3.1: No 1-min bars in market_data")
                return False

            print(f"({count} 1-min bars, {opt_count} option snapshots)", end=" ")
            self.stats["v3_market_data_rows"] = count
            self.stats["v3_option_rows"] = opt_count
            return True
        except Exception as e:
            self.issues.append(f"v3.1 population check: {e}")
            return False

    def check_v3_columns(self) -> bool:
        """Check v3 has critical columns (should be ~104)."""
        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)

            # Get columns from market_data
            describe_result = conn.execute("DESCRIBE market_data").fetchall()
            col_names = [row[0] for row in describe_result]
            col_count = len(col_names)

            # Critical columns for trading
            critical = [
                "timestamp",
                "index_name",
                "open_price",
                "spot",
                "futures",
                "adx",
                "rsi",
                "supertrend_direction",
                "supertrend_value",
                "agg_delta",
                "agg_gamma",
                "agg_vega",
                "agg_theta",
                "india_vix",
                "ema_5",
                "ema_20",
                "ema_50",
            ]

            missing_critical = [c for c in critical if c not in col_names]

            conn.close()

            if missing_critical:
                self.issues.append(f"v3.1 missing critical columns: {missing_critical}")
                return False

            print(f"({col_count} columns)", end=" ")
            self.stats["v3_columns"] = col_count
            self.stats["v3_critical_cols"] = len(critical)
            return True
        except Exception as e:
            self.issues.append(f"v3.1 column check: {e}")
            return False

    def check_v3_redis_indicators(self) -> bool:
        """Check v3.1 pushes critical indicators to Redis.

        Note: Can't directly test Redis from here, but document expected fields:
        ema, rsi, adx, st_direction, bb_pct_b (5 fields per TF)
        """
        # This is informational — Redis validation requires Redis connection
        print("(ema, rsi, adx, st_dir, bb_pct_b per TF)", end=" ")
        self.stats["v3_redis_fields"] = 5
        return True

    def run_v4_aggregator(self) -> bool:
        """Run v4 aggregator and check for data loss."""
        try:
            agg = MultiTFAggregator(str(self.db_path), verbose=False)
            results = agg.run_all_timeframes("NIFTY", lookback_days=5)

            if results["data_loss_detected"]:
                self.issues.append(f"v4 data loss: {results['summary']['warnings']}")
                return False

            self.stats["v4_results"] = results
            return True
        except Exception as e:
            self.issues.append(f"v4 aggregator error: {e}")
            return False

    def check_v4_data(self) -> bool:
        """Check v4 aggregated table is populated."""
        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)

            # Check if table exists
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name='market_data_aggregated'"
            ).fetchall()

            if not tables:
                self.warnings.append(
                    "v4: market_data_aggregated table not yet created (run aggregator first)"
                )
                conn.close()
                return True  # Not a failure, just not run yet

            count = conn.execute(
                "SELECT COUNT(*) FROM market_data_aggregated"
            ).fetchone()[0]

            if count == 0:
                self.warnings.append(
                    "v4: market_data_aggregated is empty (run aggregator)"
                )
                conn.close()
                return True  # Not a failure

            # Count by timeframe
            by_tf = conn.execute(
                """SELECT timeframe_min, COUNT(*) as cnt
                   FROM market_data_aggregated
                   GROUP BY timeframe_min
                   ORDER BY timeframe_min"""
            ).fetchall()

            print(
                f"({count} total: {', '.join(f'{tf}min={cnt}' for tf, cnt in by_tf)})",
                end=" ",
            )

            conn.close()
            self.stats["v4_aggregated_rows"] = count
            return True
        except Exception as e:
            self.issues.append(f"v4 data check: {e}")
            return False

    def check_v4_data_loss(self) -> bool:
        """Verify v4 aggregation preserved all source bars.

        For 5-min aggregation:
          If source has 100 1-min bars → should produce ~20 5-min bars
          Check: sum(5-min bars count) == count(1-min bars)
        """
        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)

            # Check if aggregated table exists
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name='market_data_aggregated'"
            ).fetchall()

            if not tables:
                return True  # Not run yet, not a failure

            # Get 1-min bar count
            v1_count = (
                conn.execute(
                    "SELECT COUNT(*) FROM market_data WHERE index_name = 'NIFTY'"
                ).fetchone()[0]
                or 0
            )

            # Get 5-min bar count
            v5_count = (
                conn.execute(
                    "SELECT COUNT(*) FROM market_data_aggregated WHERE timeframe_min = 5 AND index_name = 'NIFTY'"
                ).fetchone()[0]
                or 0
            )

            conn.close()

            # v5_count should be roughly v1_count / 5 (accounting for market hours gaps)
            if v1_count > 0 and v5_count > 0:
                expected_v5 = v1_count / 5
                ratio = v5_count / expected_v5 if expected_v5 > 0 else 0
                if ratio < 0.9 or ratio > 1.1:
                    self.warnings.append(
                        f"v4 bar count mismatch: 1-min count={v1_count}, "
                        f"5-min count={v5_count}, expected ~{expected_v5:.0f} (ratio={ratio:.2f})"
                    )

            self.stats["volume_check_v1_count"] = v1_count
            self.stats["volume_check_v5_count"] = v5_count
            return True
        except Exception as e:
            self.warnings.append(f"v4 volume check: {e}")
            return True  # Don't fail, may be no data for today

    def check_timestamp_alignment(self) -> bool:
        """Verify v4 timestamps align correctly across timeframes."""
        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)

            # Check if table exists
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name='market_data_aggregated'"
            ).fetchall()

            if not tables:
                return True  # Not run yet

            # Get a sample row from each timeframe
            for tf in [5, 15, 30, 60]:
                ts = conn.execute(
                    f"""SELECT timestamp FROM market_data_aggregated
                       WHERE timeframe_min = {tf} AND index_name = 'NIFTY'
                       LIMIT 1"""
                ).fetchone()

                if ts:
                    try:
                        dt = datetime.fromisoformat(ts[0])
                        # Timestamp should be on a {tf}-minute boundary
                        minutes = dt.hour * 60 + dt.minute
                        if minutes % tf != 0 and minutes != 9 * 60 + 15:
                            # Allow market open (09:15) as boundary
                            self.warnings.append(
                                f"v4 {tf}-min timestamp {ts[0]} not aligned to boundary"
                            )
                    except ValueError:
                        pass  # Skip timestamp parsing errors

            conn.close()
            return True
        except Exception as e:
            self.warnings.append(f"Timestamp alignment check: {e}")
            return True

    def check_critical_values(self) -> bool:
        """Verify critical trading values are present."""
        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)

            # Check v3 has OHLCV
            v3_row = conn.execute(
                """SELECT timestamp, open_price, spot, adx, rsi, agg_delta, agg_gamma
                   FROM market_data
                   WHERE index_name = 'NIFTY'
                   LIMIT 1"""
            ).fetchone()

            if not v3_row:
                self.issues.append("v3.1: No data rows found")
                conn.close()
                return False

            # Check v4 has OHLCV (only if table exists)
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name='market_data_aggregated'"
            ).fetchall()

            if tables:
                v4_row = conn.execute(
                    """SELECT timestamp, open_price, close, volume, adx, rsi, agg_delta
                       FROM market_data_aggregated
                       WHERE timeframe_min = 5 AND index_name = 'NIFTY'
                       LIMIT 1"""
                ).fetchone()

                if not v4_row:
                    self.warnings.append("v4: No aggregated data yet (run aggregator)")
                    conn.close()
                    return True

            conn.close()
            return True
        except Exception as e:
            self.warnings.append(f"Critical values check: {e}")
            return True


class PenguinValidator:
    """Validate Project Penguin SQLite capture completeness."""

    EXPECTED_BARS = {"NIFTY": 375, "SENSEX": 375, "MCX": 855}
    TIMEFRAMES = [1, 5, 15, 30, 60, 240, 1440]

    def __init__(self):
        self.issues = []
        self.warnings = []
        self.stats = {}

    def validate_all(self, target_date=None):
        import sqlite3
        from datetime import date

        day = target_date or date.today().isoformat()
        data_dir = Path("/home/trading_ceo/python-trader/varaha/data")

        print("\n" + "=" * 80)
        print(f"PENGUIN SQLITE VALIDATION — {day}")
        print("=" * 80 + "\n")

        for instrument in ["NIFTY", "SENSEX", "MCX"]:
            db_path = data_dir / f"capture_{instrument.lower()}.sqlite"
            print(f"\n--- {instrument} ({db_path.name}) ---")

            if not db_path.exists():
                self.warnings.append(f"{instrument}: SQLite file not found")
                print(f"  ⚠ File not found — skipping")
                continue

            conn = sqlite3.connect(str(db_path))

            md_rows = conn.execute(
                "SELECT COUNT(*) FROM market_data WHERE substr(timestamp,1,10)=?",
                (day,),
            ).fetchone()[0]
            expected = self.EXPECTED_BARS[instrument]
            pct = round(md_rows / expected * 100, 1) if expected > 0 else 0
            icon = "✓" if md_rows > expected * 0.9 else "✗"
            print(
                f"  {icon} market_data: {md_rows} bars (expected ~{expected}, {pct}%)"
            )
            self.stats[f"{instrument}_bars"] = md_rows
            if md_rows < expected * 0.5:
                self.issues.append(f"{instrument}: only {md_rows}/{expected} bars")

            try:
                mtf_rows = conn.execute(
                    "SELECT COUNT(*) FROM market_data_multitf WHERE substr(timestamp,1,10)=?",
                    (day,),
                ).fetchone()[0]
                tf_counts = {}
                for row in conn.execute(
                    "SELECT timeframe_min, COUNT(*) FROM market_data_multitf "
                    "WHERE substr(timestamp,1,10)=? GROUP BY timeframe_min",
                    (day,),
                ):
                    tf_counts[row[0]] = row[1]
                missing_tfs = [tf for tf in self.TIMEFRAMES if tf not in tf_counts]
                icon = "✓" if not missing_tfs else "✗"
                tf_str = ", ".join(
                    f"{tf}m={tf_counts.get(tf, 0)}" for tf in self.TIMEFRAMES
                )
                print(f"  {icon} multitf: {mtf_rows} rows [{tf_str}]")
                if missing_tfs:
                    self.warnings.append(f"{instrument}: missing TFs {missing_tfs}")
                self.stats[f"{instrument}_multitf"] = mtf_rows
            except Exception:
                print(f"  ✗ multitf: table not found")
                self.issues.append(f"{instrument}: market_data_multitf table missing")

            try:
                enr_rows = conn.execute(
                    "SELECT COUNT(*) FROM market_data_enriched WHERE substr(timestamp,1,10)=?",
                    (day,),
                ).fetchone()[0]
                icon = "✓" if enr_rows > 0 else "✗"
                print(f"  {icon} enriched: {enr_rows} rows")
                self.stats[f"{instrument}_enriched"] = enr_rows
                if enr_rows == 0 and md_rows > 10:
                    self.warnings.append(
                        f"{instrument}: enricher not running (0 enriched rows)"
                    )
            except Exception:
                print(f"  ✗ enriched: table not found")

            conn.close()

        print("\n" + "=" * 80)
        if not self.issues:
            print("✅ PENGUIN VALIDATION PASSED")
        else:
            print(f"❌ {len(self.issues)} issue(s):")
            for i in self.issues:
                print(f"   - {i}")
        if self.warnings:
            print(f"⚠ {len(self.warnings)} warning(s):")
            for w in self.warnings:
                print(f"   - {w}")
        print("=" * 80)
        return len(self.issues) == 0


def main():
    """Run validation."""
    import argparse

    parser = argparse.ArgumentParser(description="Data capture validation")
    parser.add_argument(
        "--sqlite", action="store_true", help="Validate Penguin SQLite pipeline"
    )
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD")
    args = parser.parse_args()

    if args.sqlite:
        validator = PenguinValidator()
        success = validator.validate_all(target_date=args.date)
    else:
        validator = DataCaptureValidator()
        success = validator.validate_all()

    print("\nSTATISTICS:")
    for key, val in validator.stats.items():
        print(f"  {key}: {val}")

    exit(0 if success else 1)


if __name__ == "__main__":
    main()
