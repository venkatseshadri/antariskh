#!/bin/bash
# Quick data capture health check
# Run this any time to verify v3.1 + v4 are operating correctly

set -e

echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║           DATA CAPTURE HEALTH CHECK — v3.1 + v4                   ║"
echo "║                    Status as of $(date '+%Y-%m-%d %H:%M:%S')                         ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

DB_PATH="/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"

# Check 1: Database exists
echo "📊 [1] Database Check"
if [ -f "$DB_PATH" ]; then
    SIZE=$(du -h "$DB_PATH" | cut -f1)
    echo "  ✅ DuckDB found: $SIZE"
else
    echo "  ❌ DuckDB NOT FOUND at $DB_PATH"
    exit 1
fi

# Check 2: v3.1 rows
echo ""
echo "📊 [2] v3.1 Data Population"
python3 << 'EOF'
import duckdb
try:
    conn = duckdb.connect('/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb', read_only=True)

    # v3.1 metrics
    rows = conn.execute('SELECT COUNT(*) FROM market_data').fetchone()[0]
    cols = len(conn.execute('DESCRIBE market_data').fetchall())

    # Latest bar timestamp
    latest = conn.execute('SELECT timestamp FROM market_data ORDER BY timestamp DESC LIMIT 1').fetchone()

    conn.close()

    print(f"  ✅ v3.1 1-min bars: {rows:,}")
    print(f"  ✅ Columns: {cols}")
    if latest:
        print(f"  ✅ Latest bar: {latest[0]}")
except Exception as e:
    print(f"  ❌ Error: {e}")
    exit(1)
EOF

# Check 3: v4 data
echo ""
echo "📊 [3] v4 Multi-Timeframe Aggregation"
python3 << 'EOF'
import duckdb
try:
    conn = duckdb.connect('/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb', read_only=True)

    # Check if table exists
    tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_name='market_data_aggregated'").fetchall()

    if not tables:
        print("  ℹ️  v4 table not yet created (run: python3 data_capture_v4_multitf_aggregator.py)")
    else:
        rows = conn.execute('SELECT COUNT(*) FROM market_data_aggregated').fetchone()[0]

        # Count by timeframe
        by_tf = conn.execute('''
            SELECT timeframe_min, COUNT(*) as cnt
            FROM market_data_aggregated
            GROUP BY timeframe_min
            ORDER BY timeframe_min
        ''').fetchall()

        print(f"  ✅ v4 aggregated bars: {rows}")
        for tf, cnt in by_tf:
            print(f"     • {tf:4d}-min: {cnt:3d} bars")

    conn.close()
except Exception as e:
    print(f"  ⚠️  Warning: {e}")
EOF

# Check 4: v3.1 process
echo ""
echo "📊 [4] v3.1 Process Status"
if pgrep -f "data_capture_v3" > /dev/null; then
    echo "  ✅ v3.1 process running"
    PID=$(pgrep -f "data_capture_v3")
    echo "     PID: $PID"
else
    echo "  ⚠️  v3.1 process not running"
    echo "     Start with: nohup python3 data_capture_v3_duckdb.py > data_capture_v3.log 2>&1 &"
fi

# Check 5: Redis
echo ""
echo "📊 [5] Redis Live Indicators"
if command -v redis-cli &> /dev/null; then
    KEYS=$(redis-cli KEYS '*' 2>/dev/null | wc -l)
    if [ "$KEYS" -gt 0 ]; then
        echo "  ✅ Redis connected: $KEYS keys"
    else
        echo "  ⚠️  Redis empty (no indicators yet)"
    fi
else
    echo "  ⚠️  Redis CLI not found (skip)"
fi

# Check 6: Latest data freshness
echo ""
echo "📊 [6] Data Freshness"
python3 << 'EOF'
from datetime import datetime, timedelta
import duckdb

try:
    conn = duckdb.connect('/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb', read_only=True)

    latest = conn.execute('''
        SELECT MAX(timestamp) FROM market_data
    ''').fetchone()[0]

    conn.close()

    if latest:
        latest_dt = datetime.fromisoformat(latest)
        now = datetime.now()
        age_seconds = (now - latest_dt).total_seconds()

        if age_seconds < 120:  # Less than 2 minutes
            print(f"  ✅ Data is fresh (age: {int(age_seconds)}s)")
        elif age_seconds < 300:  # Less than 5 minutes
            print(f"  ⚠️  Data is slightly stale (age: {int(age_seconds)}s)")
        else:
            print(f"  ❌ Data is STALE (age: {int(age_seconds)}s)")
            print(f"     Last update: {latest}")
    else:
        print(f"  ❌ No data in market_data")
except Exception as e:
    print(f"  ❌ Error: {e}")
EOF

echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║                      CHECK COMPLETE                               ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "📖 For detailed validation, run:"
echo "   python3 validate_data_capture_complete.py"
echo ""
echo "📖 To run v4 aggregator:"
echo "   python3 data_capture_v4_multitf_aggregator.py"
echo ""
echo "📖 View full report:"
echo "   cat DATA_CAPTURE_VALIDATION_REPORT.md"
echo ""
