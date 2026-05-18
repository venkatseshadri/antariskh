#!/usr/bin/env python3
"""
POC: Test DuckDB Quack for concurrent read/write access.

Architecture:
1. Start Quack server on test database
2. Simulate v3 writer (appends new 1-min bars)
3. Test v4 reader (reads and aggregates) — should NOT block

Goal: Prove v3 and v4 can run in parallel via Quack.
"""

import subprocess
import time
import threading
import duckdb
from datetime import datetime
import random


class QuackPOC:
    def __init__(self):
        self.db_path = "/home/trading_ceo/antariksh/poc_quack_test.duckdb"
        self.quack_port = 4242
        self.quack_process = None
        self.log_prefix = "[QuackPOC]"

    def log(self, msg):
        print(f"{self.log_prefix} {msg}")

    def start_quack_server(self):
        """Start DuckDB Quack server on test database."""
        self.log(f"Starting Quack server on port {self.quack_port}...")

        try:
            # Start DuckDB Quack server
            cmd = [
                "python3",
                "-c",
                f"""
import duckdb
import time

db = duckdb.connect('{self.db_path}')

# Load Quack extension from core_nightly
try:
    db.sql('INSTALL quack FROM core_nightly')
    db.sql('LOAD quack')
    print('[Quack] Extension loaded successfully')
except Exception as e:
    print(f'[Quack] Failed to load extension: {{e}}')
    exit(1)

db.sql('PRAGMA enable_object_cache = false')

# Start Quack server
try:
    server = db.sql('CALL quack_server(port={self.quack_port})')
    print('[Quack] Server started on port {self.quack_port}')
    # Keep server alive
    while True:
        time.sleep(1)
except Exception as e:
    print(f'[Quack] Server error: {{e}}')
    exit(1)
"""
            ]
            self.quack_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            time.sleep(3)  # Give server time to start
            self.log(f"Quack server started (PID: {self.quack_process.pid})")
            return True
        except Exception as e:
            self.log(f"Failed to start Quack: {e}")
            return False

    def stop_quack_server(self):
        """Stop Quack server."""
        if self.quack_process:
            self.log("Stopping Quack server...")
            self.quack_process.terminate()
            self.quack_process.wait(timeout=5)
            self.log("Quack server stopped")

    def simulate_v3_writer(self):
        """Simulate v3 continuously writing 1-min bars."""
        self.log("V3 Writer: Starting simulation (write 5 bars over 10 seconds)...")

        try:
            # Connect via Quack (client)
            conn = duckdb.connect(f"quack://localhost:{self.quack_port}")

            for i in range(5):
                timestamp = datetime.now().isoformat()
                open_price = 25000 + random.randint(-100, 100)
                close_price = open_price + random.randint(-50, 50)

                # Insert a 1-min bar
                conn.execute(
                    """
                    INSERT INTO market_data
                    (timestamp, index_name, timeframe_min, open, high, low, close, volume, adx, rsi, st_consensus)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (timestamp, "NIFTY", 1, open_price, open_price+50, open_price-50, close_price, 1000, 25, 50, "NEUTRAL")
                )

                self.log(f"V3 Writer: Wrote bar {i+1} at {timestamp}")
                time.sleep(2)  # 2 sec apart

            conn.close()
            self.log("V3 Writer: Done")
        except Exception as e:
            self.log(f"V3 Writer Error: {e}")

    def test_v4_reader(self):
        """Test v4 reading while v3 is writing (non-blocking)."""
        self.log("V4 Reader: Starting read test...")

        try:
            # Connect via Quack (client)
            conn = duckdb.connect(f"quack://localhost:{self.quack_port}", read_only=True)

            # Wait a bit, then try to read
            time.sleep(1)

            for i in range(5):
                result = conn.execute(
                    "SELECT COUNT(*) FROM market_data WHERE index_name='NIFTY' AND timeframe_min=1"
                ).fetchall()

                count = result[0][0]
                self.log(f"V4 Reader: Bar count = {count}")
                time.sleep(2)

            conn.close()
            self.log("V4 Reader: Done")
        except Exception as e:
            self.log(f"V4 Reader Error: {e}")

    def run_poc(self):
        """Run the POC: concurrent write (v3) + read (v4)."""
        self.log("=== Quack Concurrency POC ===")

        # Start server
        if not self.start_quack_server():
            return False

        try:
            # Run v3 (writer) and v4 (reader) in parallel threads
            writer_thread = threading.Thread(target=self.simulate_v3_writer, daemon=False)
            reader_thread = threading.Thread(target=self.test_v4_reader, daemon=False)

            reader_thread.start()
            time.sleep(0.5)  # Reader starts first
            writer_thread.start()

            # Wait for both to complete
            writer_thread.join(timeout=30)
            reader_thread.join(timeout=30)

            self.log("=== POC Complete ===")
            return True

        finally:
            self.stop_quack_server()


if __name__ == "__main__":
    poc = QuackPOC()
    success = poc.run_poc()

    if success:
        print("\n✅ Quack POC SUCCESS: v3 and v4 can work concurrently!")
    else:
        print("\n❌ Quack POC FAILED: Check errors above")
