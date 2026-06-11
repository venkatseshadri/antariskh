"""Offline tests for the option-LTP publish path (feed.py → Redis hash).

Goal: isolate the SENSEX `ltp=0.0` bug seen in capture_sensex.sqlite without a
live broker. These exercise the *real* feed._publish_option_tick and the real
TokenResolver with mock/offline data, so a failure here means a code bug and a
pass here means the bug is in the live tick stream (lp not delivered for BFO).

Run: python3 -m pytest tests/test_option_feed_publish.py -q
"""
import json
import feed
from config.token_resolver import TokenResolver


class FakeRedis:
    """Minimal hset capture — _publish_option_tick only calls hset()."""

    def __init__(self):
        self.h = {}

    def hset(self, key, field, value):
        self.h.setdefault(key, {})[field] = value


def test_publish_real_ltp_roundtrips():
    """When an option has a real ltp, it lands in the hash unchanged (NIFTY path)."""
    r = FakeRedis()
    opt = {"tsym": "NIFTY09JUN26C23800", "strike": 23800, "opt_type": "CE", "ltp": 221.3}
    feed._publish_option_tick(r, opt, "NIFTY")
    rec = json.loads(r.h["feed:NIFTY:options:ltp"]["NIFTY09JUN26C23800"])
    assert rec["ltp"] == 221.3
    assert rec["option_type"] == "CE"
    assert rec["strike"] == 23800


def test_publish_without_ltp_writes_zero():
    """Reproduces the SENSEX failure mode: a strike that never received an lp tick
    is published with ltp=0.0 — exactly what we see in capture_sensex.sqlite.
    The publish code is *correct*; the defect is upstream (no lp arrives)."""
    r = FakeRedis()
    opt = {"tsym": "SENSEX2661174400PE", "strike": 74400, "opt_type": "PE"}  # no 'ltp'
    feed._publish_option_tick(r, opt, "SENSEX")
    rec = json.loads(r.h["feed:SENSEX:options:ltp"]["SENSEX2661174400PE"])
    assert rec["ltp"] == 0.0


def test_apply_option_tick_never_clobbers_with_zero():
    """THE regression: an lp-less (or lp=0) tick must NOT zero a known-good ltp.
    Reproduces the production symptom where stale/depth ticks zeroed every strike."""
    opt = {"tsym": "SENSEX26JUL74400CE", "strike": 74400, "opt_type": "CE"}
    feed._apply_option_tick(opt, {"lp": "2602.25"})   # real trade
    assert opt["ltp"] == 2602.25
    feed._apply_option_tick(opt, {"tk": "1"})          # depth packet, no 'lp'
    assert opt["ltp"] == 2602.25                        # preserved, not 0.0
    feed._apply_option_tick(opt, {"lp": "0"})          # explicit zero (no print)
    assert opt["ltp"] == 2602.25                        # still preserved
    feed._apply_option_tick(opt, {"lp": "2650.0"})     # new trade updates
    assert opt["ltp"] == 2650.0


def test_apply_option_tick_guards_oi_volume():
    """oi/volume update only when present (unchanged behaviour)."""
    opt = {"tsym": "NIFTY09JUN26C23500", "strike": 23500, "opt_type": "CE", "oi": 100.0}
    feed._apply_option_tick(opt, {"lp": "50"})          # price-only tick
    assert opt["oi"] == 100.0                            # oi not clobbered
    feed._apply_option_tick(opt, {"lp": "51", "oi": "250", "v": "12"})
    assert opt["oi"] == 250.0 and opt["volume"] == 12.0


def test_lp_parse_contract():
    """on_tick does `float(msg.get("lp", 0))` — a tick with no 'lp' yields 0.0."""
    assert float({}.get("lp", 0)) == 0.0            # depth packet w/o trade price
    assert float({"lp": "105.5"}.get("lp", 0)) == 105.5


def test_sensex_resolution_returns_valid_bfo_tokens():
    """Rules out symbol/exchange resolution as the cause: SENSEX weekly strikes
    resolve to non-empty BFO tokens with well-formed tsyms."""
    wk = TokenResolver(sensex_spot=74700).resolve_weekly_sensex(2)
    assert wk, "no SENSEX weekly strikes resolved"
    for t in wk:
        assert t["token"], f"empty token for {t['tsym']}"
        assert t["exchange"] == "BFO"
        assert t["tsym"].startswith("SENSEX")
