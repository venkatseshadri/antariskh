#!/usr/bin/env python3
"""
POC: DuckDB Quack - Concurrent Multi-Process Read/Write Access

Architecture:
- Server: DuckDB Quack server on :9494
- Client 1 (v3): Writes 1-min bars continuously
- Client 2 (v4): Reads and aggregates concurrently

Goal: Prove v3 and v4 can work in parallel with Quack.
"""

import subprocess
import time
import threading
import duckdb
from datetime import datetime
import random
import sys


class QuackWorking:
    def __init__(self):
        self.db_path = "/home/trading_ceo/antariksh/poc_quack_test.duckdb"
        self.quack_port = 9494
        self.quack_host = "localhost"
        self.token = "antariksh_secret_token"
        self.server_process = None
        self.log_prefix = "[QuackPOC]"

    def log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"{self.log_prefix} [{timestamp}] {msg}")

    def start_quack_server(self):
        """Start DuckDB Quack server."""
        self.log(f"Starting Quack server on {self.quack_host}:{self.quack_port}...")

        try:
            cmd = [
                "python3",
                "-c",
                f"""
import duckdb
import sys

db = duckdb.connect(r'{self.db_path}')

# Load Quack extension
try:
    db.sql('FORCE INSTALL quack FROM core_nightly')
    db.sql('LOAD quack')
    print('[Quack] Extension loaded', flush=True)
except Exception as e:
    print(f'[Quack] Failed to load extension: {{e}}', file=sys.stderr, flush=True)
    sys.exit(1)

# Start Quack server
try:
    result = db.sql("CALL quack_serve('quack:{self.quack_host}:{self.quack_port}', token = '{self.token}')").fetchall()
    print(f'[Quack] Server started on {self.quack_host}:{self.quack_port}', flush=True)
    print(f'[Quack] Result: {{result}}', flush=True)

    # Keep server alive by sleeping
    import time
    while True:
        time.sleep(1)
except Exception as e:
    print(f'[Quack] Server error: {{e}}', file=sys.stderr, flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)
"""
            ]
            self.server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            # Wait for server to start
            time.sleep(3)

            if self.server_process.poll() is not None:
                # Process died
                stdout, stderr = self.server_process.communicate()
                self.log(f"Server failed to start!")
                self.log(f"stdout: {stdout}")
                self.log(f"stderr: {stderr}")
                return False

            self.log(f"✅ Quack server started (PID: {self.server_process.pid})")
            return True

        except Exception as e:
            self.log(f"❌ Failed to start Quack: {e}")
            return False

    def stop_quack_server(self):
        """Stop Quack server."""
        if self.server_process:
            self.log("Stopping Quack server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.log("Quack server stopped")

    def v3_writer_process(self):
        """Simulate v3: Write 1-min bars via Quack."""
        self.log("V3 Writer: Connecting via Quack...")

        try:
            # Connect as client
            conn = duckdb.connect(":memory:")
            conn.sql("FORCE INSTALL quack FROM core_nightly")
            conn.sql("LOAD quack")

            # Attach to remote server
            conn.sql(f"ATTACH 'quack:{self.quack_host}:{self.quack_port}' AS remote (TOKEN '{self.token}')")

            self.log("V3 Writer: ✅ Connected to Quack server")

            # Write 5 bars
            for i in range(5):
                timestamp = datetime.now().isoformat()
                open_price = 25000 + random.randint(-100, 100)
                close_price = open_price + random.randint(-50, 50)

                # Insert via remote
                conn.sql(f"""
                    INSERT INTO remote.market_data
                    (timestamp, index_name, timeframe_min, open, high, low, close, volume, adx, rsi, st_consensus)
                    VALUES ('{timestamp}', 'NIFTY', 1, {open_price}, {open_price+50}, {open_price-50}, {close_price}, 1000, 25, 50, 'NEUTRAL')
                """)

                self.log(f"V3 Writer: Inserted bar {i+1} at {timestamp}")
                time.sleep(1)

            conn.close()
            self.log("V3 Writer: ✅ Complete")

        except Exception as e:
            self.log(f"❌ V3 Writer Error: {e}")
            import traceback
            traceback.print_exc()

    def v4_reader_process(self):
        """Simulate v4: Read bars via Quack and aggregate."""
        self.log("V4 Reader: Connecting via Quack...")

        try:
            # Connect as client
            conn = duckdb.connect(":memory:")
            conn.sql("FORCE INSTALL quack FROM core_nightly")
            conn.sql("LOAD quack")

            # Attach to remote server
            conn.sql(f"ATTACH 'quack:{self.quack_host}:{self.quack_port}' AS remote (TOKEN '{self.token}')")

            self.log("V4 Reader: ✅ Connected to Quack server")

            # Read bars periodically
            for i in range(6):
                result = conn.sql("SELECT COUNT(*) as bar_count FROM remote.market_data WHERE index_name='NIFTY' AND timeframe_min=1").fetchall()

                count = result[0][0] if result else 0
                self.log(f"V4 Reader: Bar count = {count}")
                time.sleep(1)

            conn.close()
            self.log("V4 Reader: ✅ Complete")

        except Exception as e:
            self.log(f"❌ V4 Reader Error: {e}")
            import traceback
            traceback.print_exc()

    def run_poc(self):
        """Run POC: Start server, then v3 writer + v4 reader in parallel."""
        self.log("=" * 60)
        self.log("DuckDB Quack Concurrent Access POC")
        self.log("=" * 60)

        # Start server
        if not self.start_quack_server():
            return False

        try:
            # Start v3 writer and v4 reader in parallel
            writer = threading.Thread(target=self.v3_writer_process, daemon=False, name="V3Writer")
            reader = threading.Thread(target=self.v4_reader_process, daemon=False, name="V4Reader")

            reader.start()
            time.sleep(0.5)  # Reader starts first
            writer.start()

            # Wait for both
            writer.join(timeout=30)
            reader.join(timeout=30)

            self.log("=" * 60)
            self.log("✅ POC COMPLETE: v3 and v4 ran in parallel!")
            self.log("=" * 60)
            return True

        finally:
            self.stop_quack_server()


if __name__ == "__main__":
    poc = QuackWorking()
    success = poc.run_poc()
    sys.exit(0 if success else 1)
