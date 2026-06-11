"""LIVE diagnostic — why do SENSEX (BFO) option LTPs capture as 0.0 while NIFTY (NFO) work?

Read-only: subscribes a few NIFTY + SENSEX ATM option tokens and dumps the RAW
WebSocket messages so we can see which field carries the price for each exchange.
Does NOT write to Redis or any DB. Run during market hours (09:15-15:30).

Usage (at the open):
    python3 tools/diag_option_feed.py --nifty-spot 23900 --sensex-spot 74700 --secs 90

If spots are omitted, the resolver's fallbacks are used (may pick illiquid strikes).
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from feed import load_creds, IST  # reuse exact cred loader + tz
from config.token_resolver import TokenResolver
from api_helper import NorenApiPy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nifty-spot", type=float, default=None)
    ap.add_argument("--sensex-spot", type=float, default=None)
    ap.add_argument("--secs", type=int, default=90)
    ap.add_argument("--range", type=int, default=1, help="ATM +/- N strikes per index")
    args = ap.parse_args()

    # Resolve a small ATM window for each index.
    nres = TokenResolver(nifty_spot=args.nifty_spot)
    sres = TokenResolver(sensex_spot=args.sensex_spot)
    tokens = nres.resolve_weekly_nifty(args.range) + sres.resolve_weekly_sensex(args.range)

    # (exchange, token) -> label, so matching is exchange-safe in the diagnostic.
    watch = {}
    for t in tokens:
        watch[(t["exchange"], str(t["token"]))] = f"{t['exchange']}:{t['tsym']}"
    print(f"Watching {len(watch)} option tokens:")
    for k, v in watch.items():
        print(f"  {k} -> {v}")
    if not watch:
        print("No tokens resolved — pass --nifty-spot/--sensex-spot near current levels.")
        return

    creds = load_creds()
    api = NorenApiPy()
    if not api.injectOAuthHeader(creds["Access_token"], creds["UID"], creds["Account_ID"]):
        print("OAuth injection failed"); return
    api.set_credentials(creds["Access_token"], creds["UID"], creds["Account_ID"])

    stats = defaultdict(lambda: {"msgs": 0, "with_lp": 0, "max_lp": 0.0, "samples": []})
    opened = {"v": False}

    def on_tick(msg):
        key = (msg.get("e", ""), str(msg.get("tk", "")))
        label = watch.get(key)
        if not label:
            return
        s = stats[label]
        s["msgs"] += 1
        if "lp" in msg:
            s["with_lp"] += 1
            s["max_lp"] = max(s["max_lp"], float(msg.get("lp") or 0))
        if len(s["samples"]) < 2:
            s["samples"].append(dict(msg))  # raw — show every field the exchange sends

    def on_open():
        opened["v"] = True
        for (exch, tok) in watch:
            api.subscribe(f"{exch}|{tok}", feed_type="d")
        print("subscribed; collecting...")

    api.start_websocket(
        order_update_callback=lambda m: None,
        subscribe_callback=on_tick,
        socket_open_callback=on_open,
    )
    for _ in range(30):
        if opened["v"]:
            break
        time.sleep(1)
    time.sleep(args.secs)

    print("\n================ RESULT ================")
    for label in sorted(stats):
        s = stats[label]
        verdict = "OK" if s["max_lp"] > 0 else "*** ltp stuck at 0 ***"
        print(f"{label:32} msgs={s['msgs']:4} with_lp={s['with_lp']:4} max_lp={s['max_lp']:>10}  {verdict}")
    print("\n--- RAW SAMPLES (compare NFO vs BFO field sets) ---")
    for label in sorted(stats):
        for samp in stats[label]["samples"]:
            print(f"{label}: {json.dumps(samp)}")
    # Tokens that received ZERO messages = subscription/exchange problem, not a price problem.
    silent = [v for v in watch.values() if v not in stats]
    if silent:
        print("\nNO MESSAGES AT ALL for:", silent)


if __name__ == "__main__":
    main()
