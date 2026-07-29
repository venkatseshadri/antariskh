"""Coverage for proton_live.py's real-broker-order code path — the ONE part
of PROTON+ (real money, live since 2026-07-17) that has never executed even
once, because Gate1 blocked every cycle until 2026-07-19's fix. Can't
safely test this against a real broker (that would place real orders), so
this exercises the actual functions (place_leg/place_resting_sl/cancel_order/
check_account_margin/broker_position_qty/broker_confirms_flat/
_orbiter_enter_legs/_orbiter_exit_side/_orbiter_price_side_broker) against a
FakeApi that mimics the Shoonya response shape ({"stat": "Ok", ...}),
verifying the code's own logic rather than the broker's.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import proton_live as pl  # noqa: E402


class FakeApi:
    """Records every call it receives; scripted responses per call type."""

    def __init__(self, place_order_resp=None, cancel_resp=None,
                 limits_resp=None, positions_resp=None, quotes_resp=None):
        self.calls = []
        self._place_order_resp = place_order_resp if place_order_resp is not None else {
            "stat": "Ok", "norenordno": "ORD1"
        }
        self._cancel_resp = cancel_resp if cancel_resp is not None else {"stat": "Ok"}
        self._limits_resp = limits_resp if limits_resp is not None else {
            "cash": "100000", "collat": "0", "marginavailable": "100000"
        }
        self._positions_resp = positions_resp if positions_resp is not None else []
        self._quotes_resp = quotes_resp if quotes_resp is not None else {"stat": "Ok", "lp": "50.0"}

    def place_order(self, **kwargs):
        self.calls.append(("place_order", kwargs))
        resp = self._place_order_resp
        return resp(kwargs) if callable(resp) else resp

    def cancel_order(self, **kwargs):
        self.calls.append(("cancel_order", kwargs))
        return self._cancel_resp

    def get_limits(self):
        self.calls.append(("get_limits", {}))
        return self._limits_resp

    def get_positions(self):
        self.calls.append(("get_positions", {}))
        return self._positions_resp

    def get_quotes(self, exchange, token):
        self.calls.append(("get_quotes", {"exchange": exchange, "token": token}))
        # Real broker echoes back the requested token/exch in every quote
        # response — _leg_ltp validates against this (2026-07-29 fix), so
        # the mock must match unless a test explicitly overrides token/exch
        # to test the mismatch-rejection path itself.
        resp = dict(self._quotes_resp)
        resp.setdefault("token", token)
        resp.setdefault("exch", exchange)
        return resp


LEG = {"exchange": "NFO", "token": "12345", "tsym": "NIFTY28JUL26P24250"}


# ── place_leg / place_resting_sl / cancel_order ──────────────────────────


def test_place_leg_success_returns_ok_result_with_orderno():
    api = FakeApi()
    r = pl.place_leg(api, pl.BUY, "NFO", "NIFTY28JUL26P24250", 75, 100.0, remarks="TEST")
    assert r.ok is True
    assert r.norenordno == "ORD1"
    call_name, kwargs = api.calls[0]
    assert call_name == "place_order"
    assert kwargs["buy_or_sell"] == pl.BUY
    assert kwargs["quantity"] == 75
    assert kwargs["product_type"] == pl.NRML
    assert kwargs["price_type"] == pl.LIMIT
    # BUY gets a marketable price ABOVE ltp (cross the spread to actually fill)
    assert kwargs["price"] > 100.0


def test_place_leg_sell_prices_below_ltp():
    api = FakeApi()
    pl.place_leg(api, pl.SELL, "NFO", "X", 75, 100.0, remarks="TEST")
    _, kwargs = api.calls[0]
    assert kwargs["price"] < 100.0


def test_place_leg_broker_rejection_is_not_ok():
    api = FakeApi(place_order_resp={"stat": "Not_Ok", "emsg": "insufficient margin"})
    r = pl.place_leg(api, pl.BUY, "NFO", "X", 75, 100.0, remarks="TEST")
    assert r.ok is False
    assert r.norenordno is None


def test_place_resting_sl_trigger_and_limit_above_entry_for_short_cover():
    api = FakeApi()
    r = pl.place_resting_sl(api, pl.BUY, "NFO", "X", 75, trigger_price=200.0, remarks="TEST")
    assert r.ok is True
    _, kwargs = api.calls[0]
    assert kwargs["price_type"] == pl.SL_LIMIT
    assert kwargs["trigger_price"] == 200.0
    # limit sits past the trigger so it actually fills like a stop
    assert kwargs["price"] > 200.0


def test_cancel_order_passes_through_orderno():
    api = FakeApi()
    r = pl.cancel_order(api, "ORD1")
    assert r.ok is True
    _, kwargs = api.calls[0]
    assert kwargs["orderno"] == "ORD1"


# ── check_account_margin ─────────────────────────────────────────────────


def test_check_account_margin_passes_when_above_floor():
    api = FakeApi(limits_resp={"cash": "60000", "collat": "0", "marginavailable": "60000"})
    ok, avail = pl.check_account_margin(api)
    assert ok is True
    assert avail == 60000.0


def test_check_account_margin_fails_when_below_floor():
    api = FakeApi(limits_resp={"cash": "10000", "collat": "0", "marginavailable": "10000"})
    ok, avail = pl.check_account_margin(api)
    assert ok is False
    assert avail == 10000.0


def test_check_account_margin_fails_closed_on_malformed_response():
    api = FakeApi(limits_resp="not a dict")
    ok, avail = pl.check_account_margin(api)
    assert ok is False
    assert avail is None


def test_check_account_margin_fails_closed_on_exception():
    class BrokenApi:
        def get_limits(self):
            raise ConnectionError("broker down")
    ok, avail = pl.check_account_margin(BrokenApi())
    assert ok is False
    assert avail is None


# ── broker_position_qty / broker_confirms_flat ───────────────────────────


def test_broker_position_qty_finds_matching_tsym():
    api = FakeApi(positions_resp=[{"tsym": "NIFTY28JUL26P24250", "netqty": "75"}])
    assert pl.broker_position_qty(api, "NIFTY28JUL26P24250") == 75


def test_broker_position_qty_zero_when_not_in_positions():
    api = FakeApi(positions_resp=[])
    assert pl.broker_position_qty(api, "NIFTY28JUL26P24250") == 0


def test_broker_position_qty_none_on_exception():
    class BrokenApi:
        def get_positions(self):
            raise ConnectionError("broker down")
    assert pl.broker_position_qty(BrokenApi(), "X") is None


def test_broker_confirms_flat_true_when_no_open_position():
    assert pl.broker_confirms_flat(FakeApi(), {"open_position": None}) is True


def test_broker_confirms_flat_true_when_broker_shows_zero_qty():
    api = FakeApi(positions_resp=[])
    state = {"open_position": {"legs": {"short": {"tsym": "X"}, "hedge": {"tsym": "Y"}}}}
    assert pl.broker_confirms_flat(api, state) is True


def test_broker_confirms_flat_false_when_broker_shows_nonzero_qty():
    """This is the real-money safety check: state says flat but broker
    disagrees — must refuse to treat it as flat (prevents double-entry)."""
    api = FakeApi(positions_resp=[{"tsym": "X", "netqty": "75"}])
    state = {"open_position": {"legs": {"short": {"tsym": "X"}, "hedge": {"tsym": "Y"}}}}
    assert pl.broker_confirms_flat(api, state) is False


# ── _orbiter_enter_legs (the actual live 2-leg spread entry sequence) ────


def _legs_raw():
    return {
        "hedge": {"exchange": "NFO", "tsym": "NIFTY28JUL26P24150", "token": "63946"},
        "short": {"exchange": "NFO", "tsym": "NIFTY28JUL26P24250", "token": "63950"},
    }


def test_orbiter_enter_legs_success_places_hedge_then_short_then_resting_sl():
    api = FakeApi()
    result = pl._orbiter_enter_legs(api, _legs_raw(), {"hedge": 40.0, "short": 60.0}, 75, sl_mult=1.0)
    assert result["stage"] == "complete"
    assert result["orders"]["hedge"]["ok"] and result["orders"]["short"]["ok"]
    assert result["sl_orders"]["short"]["ok"]
    call_names = [c[0] for c in api.calls]
    # hedge (BUY) must go first — you never want a naked short live even briefly
    assert call_names[0] == "place_order"
    assert api.calls[0][1]["buy_or_sell"] == pl.BUY
    assert api.calls[1][1]["buy_or_sell"] == pl.SELL


def test_orbiter_enter_legs_stops_immediately_if_hedge_fails():
    """If the hedge (protective) leg fails, must NOT proceed to sell the
    naked short — that would be an unhedged real-money position."""
    api = FakeApi(place_order_resp={"stat": "Not_Ok"})
    result = pl._orbiter_enter_legs(api, _legs_raw(), {"hedge": 40.0, "short": 60.0}, 75, sl_mult=1.0)
    assert result["stage"] == "failed_hedge"
    assert "short" not in result["orders"]
    assert len([c for c in api.calls if c[0] == "place_order"]) == 1


def test_orbiter_enter_legs_stops_before_resting_sl_if_short_leg_fails():
    call_count = {"n": 0}

    def scripted(kwargs):
        call_count["n"] += 1
        # hedge (1st call) succeeds, short (2nd call) fails
        return {"stat": "Ok", "norenordno": "H1"} if call_count["n"] == 1 else {"stat": "Not_Ok"}

    api = FakeApi(place_order_resp=scripted)
    result = pl._orbiter_enter_legs(api, _legs_raw(), {"hedge": 40.0, "short": 60.0}, 75, sl_mult=1.0)
    assert result["stage"] == "failed_short_hedge_live"
    assert "short" not in result["sl_orders"]


def test_orbiter_enter_legs_flags_sl_failure_after_position_is_already_live():
    """The most dangerous gap (found by DS review, 2026-07-19): hedge and
    short both fill, but the resting SL fails to place. The position is
    now LIVE, REAL MONEY, with no broker-side protective stop. This must
    be surfaced via a distinct stage — never silently reported as
    "complete" — even though both directional legs did fill correctly."""
    call_count = {"n": 0}

    def scripted(kwargs):
        call_count["n"] += 1
        # hedge + short (calls 1-2) succeed; resting SL (call 3) fails
        return {"stat": "Ok", "norenordno": f"O{call_count['n']}"} if call_count["n"] <= 2 else {"stat": "Not_Ok"}

    api = FakeApi(place_order_resp=scripted)
    result = pl._orbiter_enter_legs(api, _legs_raw(), {"hedge": 40.0, "short": 60.0}, 75, sl_mult=1.0)
    assert result["stage"] == "complete_but_sl_failed"
    assert result["orders"]["hedge"]["ok"] and result["orders"]["short"]["ok"]
    assert result["sl_orders"]["short"]["ok"] is False


# ── _orbiter_exit_side (the actual live close sequence) ──────────────────


def test_orbiter_exit_side_cancels_resting_sl_then_closes_both_legs():
    api = FakeApi()
    side = {
        "legs": _legs_raw(),
        "exit_leg_prices": {"short": 55.0, "hedge": 35.0},
    }
    result = pl._orbiter_exit_side(api, side, 75, sl_order_ids={"short": "SLORD1"})
    assert result["stage"] == "complete"
    assert result["sl_cancel"]["short"]["ok"] is True
    call_names = [c[0] for c in api.calls]
    assert call_names[0] == "cancel_order"  # SL canceled before closing legs
    # short leg closes via BUY (buyback), hedge via SELL
    place_calls = [c for c in api.calls if c[0] == "place_order"]
    assert place_calls[0][1]["buy_or_sell"] == pl.BUY
    assert place_calls[1][1]["buy_or_sell"] == pl.SELL


def test_orbiter_exit_side_stops_if_short_buyback_fails():
    api = FakeApi(place_order_resp={"stat": "Not_Ok"})
    side = {"legs": _legs_raw(), "exit_leg_prices": {"short": 55.0, "hedge": 35.0}}
    result = pl._orbiter_exit_side(api, side, 75, sl_order_ids={})
    assert result["stage"] == "failed_close_short"


def test_orbiter_exit_side_retry_skips_already_closed_leg_not_double_closed():
    """DS review 2026-07-22: short succeeds, hedge fails (partial close).
    A retry with the SAME side dict must NOT re-place the short order — it
    already closed at the broker; doing so again would be a real duplicate
    order. legs_closed (mutated onto `side` in place) is what makes the
    retry remember this."""

    class ShortOkHedgeFailsApi(FakeApi):
        def place_order(self, **kwargs):
            self.calls.append(("place_order", kwargs))
            if kwargs.get("tradingsymbol") == _legs_raw()["hedge"]["tsym"]:
                return {"stat": "Not_Ok", "emsg": "rejected"}
            return {"stat": "Ok", "norenordno": "SHORT_CLOSE_ORD"}

    api = ShortOkHedgeFailsApi()
    side = {"legs": _legs_raw(), "exit_leg_prices": {"short": 55.0, "hedge": 35.0}}

    first = pl._orbiter_exit_side(api, side, 75, sl_order_ids={})
    assert first["stage"] == "failed_close_hedge"
    assert side["legs_closed"] == {"short": "SHORT_CLOSE_ORD"}
    short_orders_after_first = sum(
        1 for name, kw in api.calls
        if name == "place_order" and kw.get("tradingsymbol") == _legs_raw()["short"]["tsym"]
    )
    assert short_orders_after_first == 1

    # Retry with the same (mutated) side dict — hedge still fails, but short
    # must be skipped, not re-placed.
    second = pl._orbiter_exit_side(api, side, 75, sl_order_ids={})
    assert second["stage"] == "failed_close_hedge"
    assert second["orders"]["short"]["skipped_already_closed"] is True
    short_orders_after_second = sum(
        1 for name, kw in api.calls
        if name == "place_order" and kw.get("tradingsymbol") == _legs_raw()["short"]["tsym"]
    )
    assert short_orders_after_second == 1, "short must not be closed a second time"


def test_orbiter_exit_side_still_closes_legs_if_sl_cancel_fails():
    """DS review (2026-07-19): if the resting-SL cancel itself fails (broker
    already filled it, network blip, etc.), the code must still attempt to
    close the actual position — a stale, already-fired SL blocking the real
    exit would leave a real-money position open with no path to close it."""
    api = FakeApi(cancel_resp={"stat": "Not_Ok", "emsg": "order not found"})
    side = {"legs": _legs_raw(), "exit_leg_prices": {"short": 55.0, "hedge": 35.0}}
    result = pl._orbiter_exit_side(api, side, 75, sl_order_ids={"short": "SLORD1"})
    assert result["sl_cancel"]["short"]["ok"] is False
    assert result["stage"] == "complete"
    assert result["orders"]["short"]["ok"] and result["orders"]["hedge"]["ok"]


# ── _orbiter_price_side_broker ───────────────────────────────────────────


def test_orbiter_price_side_broker_returns_ltp_per_leg():
    api = FakeApi(quotes_resp={"stat": "Ok", "lp": "42.5"})
    side = {"legs": _legs_raw()}
    result = pl._orbiter_price_side_broker(api, side)
    assert result == {"hedge": 42.5, "short": 42.5}


def test_orbiter_price_side_broker_maps_each_leg_to_its_own_token_not_swapped():
    """DS review (2026-07-19): a same-price-for-both-legs test can't catch
    a hedge/short quote mixup. Script distinct prices per token and verify
    each leg gets ITS OWN quote, not the other leg's."""
    class TokenAwareApi(FakeApi):
        def get_quotes(self, exchange, token):
            self.calls.append(("get_quotes", {"exchange": exchange, "token": token}))
            prices = {"63946": "35.0", "63950": "60.0"}  # hedge token, short token
            return {"stat": "Ok", "lp": prices[token], "token": token, "exch": exchange}

    side = {"legs": _legs_raw()}  # hedge token=63946, short token=63950
    result = pl._orbiter_price_side_broker(TokenAwareApi(), side)
    assert result == {"hedge": 35.0, "short": 60.0}


def test_orbiter_price_side_broker_none_on_bad_quote():
    api = FakeApi(quotes_resp={"stat": "Not_Ok"})
    side = {"legs": _legs_raw()}
    assert pl._orbiter_price_side_broker(api, side) is None


# ── _try_enter_orbiter paper-mode persistence (2026-07-20 fix) ──────────
# Before the fix, LIVE_ENABLED=False entries logged "would_place" and
# returned without ever calling _save_state — the cycle was computed fresh
# and forgotten every 15-min tick, so a paper-mode PROTON+ could never
# reach _check_exit_orbiter/_morph_check_orbiter and never produced a
# trackable trade (open->SL/TP/exit->P&L). This drives _try_enter_orbiter
# through a full ENTER with LIVE_ENABLED patched False and asserts the
# cycle actually lands in state["orbiter_position"].


def test_try_enter_orbiter_paper_mode_persists_cycle_to_state(monkeypatch):
    import pandas as pd
    from datetime import date, datetime

    monkeypatch.setattr(pl, "LIVE_ENABLED", False)
    monkeypatch.setattr(pl, "_nearest_expiry_index", lambda now: "NIFTY")
    monkeypatch.setattr(
        pl, "combined_daily_closes",
        lambda index: pd.Series([24000.0], index=[date(2026, 7, 20)]),
    )
    monkeypatch.setattr(pl, "trailing_rv", lambda closes, today: 0.15)
    monkeypatch.setattr(pl, "trailing_median_rv", lambda closes, today: 0.10)
    monkeypatch.setattr(
        pl.orbiter_mod, "_read_enriched_row",
        lambda index, today: {"timestamp": "2026-07-20T09:30:00", "pcr_total": 1.0},
    )
    passed = pl.orbiter_mod.GateResult(True, "GATE1", "PASSED", {})
    monkeypatch.setattr(pl.orbiter_mod, "gate1_regime", lambda row: passed)
    monkeypatch.setattr(pl.orbiter_mod, "gate1_tiger_override", lambda row, g1, ts: passed)
    monkeypatch.setattr(pl.orbiter_mod, "gate3_entry_abort", lambda row: passed)
    monkeypatch.setattr(pl, "_shoonya_session", lambda: FakeApi())
    monkeypatch.setattr(pl, "broker_confirms_flat", lambda api, state: True)
    monkeypatch.setattr(pl, "resolve_weekly_expiry", lambda index, now: date(2026, 7, 24))
    monkeypatch.setattr(pl.orbiter_mod, "phase_machine_direction", lambda row, s0: "bull_put_spread")
    # Must be mocked, not left to hit the real antariksh/data/nucleus_allocation.json
    # (refreshed every 15 min with live numbers) — otherwise this test's pass/fail
    # depends on today's actual NUCLEUS ceiling, not the fixed inputs below.
    monkeypatch.setattr(pl, "_nucleus_ceiling", lambda tier="T3_HYDROGEN": (1_000_000.0, None))

    strike_map = pl.orbiter_mod.StrikeMap(
        put_short=23900, put_hedge=23800, call_short=24100, call_hedge=24200,
        vwap=24000.0, bb_upper=None, bb_lower=None, max_pain=None, atm=24000,
    )
    monkeypatch.setattr(pl.orbiter_mod, "gate2_strikes", lambda row, s0: strike_map)
    monkeypatch.setattr(
        pl, "_orbiter_resolve_two_legs",
        lambda expiry, s0, short_k, hedge_k, opt_type: {
            "short": {"exchange": "NFO", "token": "111", "tsym": "SHORT", "strike": short_k, "opt_type": opt_type},
            "hedge": {"exchange": "NFO", "token": "112", "tsym": "HEDGE", "strike": hedge_k, "opt_type": opt_type},
        },
    )
    monkeypatch.setattr(pl, "_leg_ltp", lambda api, exch, token: float("nan"))

    saved = {}
    monkeypatch.setattr(pl, "_save_state", lambda state: saved.update(state))
    monkeypatch.setattr(pl, "_log_ledger", lambda event: None)

    state = {"open_position": None}
    result = pl._try_enter_orbiter(state, date(2026, 7, 20), datetime(2026, 7, 20, 9, 30))

    assert result["action"] == "ENTER_TRIGGER_ORBITER"
    assert result["dry_run"] is True
    assert state["orbiter_position"] is not None
    assert state["orbiter_position"]["put"]["short_k"] == 23900
    assert saved.get("orbiter_position") is state["orbiter_position"]


# ── run_live_once paper-mode ROLL_FORWARD dispatch (2026-07-22 fix) ─────
# Bug: _check_exit_orbiter's dry-run branch returned action="EXIT_TRIGGER_ORBITER"
# with no "fully_closed" key, but run_live_once's roll-to-opposite-exchange
# gate only checked for action=="EXIT_ORBITER" + fully_closed truthy — a
# LIVE-only pair of conditions. So in paper mode a full exit never triggered
# the opposite-exchange re-entry; it just went flat and re-entered the SAME
# index next tick. Observed live 2026-07-21: 9 same-index NIFTY entries in a
# row instead of alternating NIFTY/SENSEX. Fixed by (1) the dry-run event now
# sets fully_closed=True (paper exits can't partially fail — no broker calls
# to fail partially), and (2) run_live_once accepts either action string.


def test_run_live_once_rolls_to_opposite_exchange_on_paper_exit(monkeypatch):
    from datetime import date, datetime

    exit_event = {
        "action": "EXIT_TRIGGER_ORBITER",
        "index": "NIFTY",
        "spot": 24200.0,
        "exits": [{"side": "put", "reason": "HARVEST_50", "pnl": 500.0}],
        "dry_run": True,
        "would_close_sides": ["put"],
        "fully_closed": True,
    }
    reentry_event = {"action": "ENTER_TRIGGER_ORBITER", "index": "SENSEX", "dry_run": True}

    monkeypatch.setattr(pl, "_load_state", lambda: {"orbiter_position": {"index": "NIFTY"}})
    monkeypatch.setattr(pl, "_check_exit_orbiter", lambda state, today, now: dict(exit_event))
    captured = {}

    def fake_try_enter(state, today, now, force_index=None):
        captured["force_index"] = force_index
        return dict(reentry_event)

    monkeypatch.setattr(pl, "_try_enter_orbiter", fake_try_enter)

    result = pl.run_live_once(now=datetime(2026, 7, 22, 9, 30), use_orbiter=True)

    assert captured["force_index"] == "SENSEX"
    assert result["action"] == "ROLL_FORWARD"
    assert result["exit"] == exit_event
    assert result["re_entry"] == reentry_event


def test_run_live_once_no_roll_forward_when_paper_exit_not_fully_closed(monkeypatch):
    """Sanity check the flag is actually load-bearing: without fully_closed,
    no roll-forward, no forced re-entry attempt."""
    from datetime import datetime

    exit_event = {
        "action": "EXIT_TRIGGER_ORBITER",
        "index": "NIFTY",
        "exits": [],
        "dry_run": True,
        "would_close_sides": [],
        # fully_closed intentionally omitted
    }
    monkeypatch.setattr(pl, "_load_state", lambda: {"orbiter_position": {"index": "NIFTY"}})
    monkeypatch.setattr(pl, "_check_exit_orbiter", lambda state, today, now: dict(exit_event))

    called = {"try_enter": False}

    def fake_try_enter(*a, **k):
        called["try_enter"] = True
        return None

    monkeypatch.setattr(pl, "_try_enter_orbiter", fake_try_enter)

    result = pl.run_live_once(now=datetime(2026, 7, 22, 9, 30), use_orbiter=True)

    assert called["try_enter"] is False
    assert result == exit_event


# ── _check_exit_orbiter: fully_closed must reflect active_sides, not be
# unconditional (DS review 2026-07-22 — the gate that keeps a partial exit
# from being mislabeled a full close and triggering an unsafe roll-forward
# on top of an orphaned still-open leg) ──────────────────────────────────


def _partial_exit_setup(monkeypatch):
    import pandas as pd
    from datetime import date, datetime

    monkeypatch.setattr(pl, "LIVE_ENABLED", False)
    monkeypatch.setattr(
        pl, "combined_daily_closes",
        lambda index: pd.Series([24000.0], index=[date(2026, 7, 22)]),
    )
    monkeypatch.setattr(pl, "_shoonya_session", lambda: FakeApi())
    monkeypatch.setattr(pl.orbiter_mod, "_read_enriched_row", lambda index, today: {"atr_daily": None})
    monkeypatch.setattr(
        pl.orbiter_mod, "orbiter_tp_check",
        lambda *a, **k: pl.orbiter_mod.OrbiterExit(False, None, None, ""),
    )
    # short_k/hedge_k values only matter for routing to the right canned BS price
    monkeypatch.setattr(
        pl, "black_scholes_put",
        lambda S, K, T, r, sigma: 100.0 if K == 100 else 40.0,  # value = 60 -> hits static_sl
    )
    monkeypatch.setattr(
        pl, "black_scholes_call",
        lambda S, K, T, r, sigma: 50.0 if K == 200 else 20.0,  # value = 30 -> no trigger
    )
    monkeypatch.setattr(pl, "_save_state", lambda state: None)
    monkeypatch.setattr(pl, "_log_ledger", lambda event: None)

    pos = {
        "index": "NIFTY",
        "expiry": "2026-08-04",
        "entry_ts": "2026-07-22T09:30:00",
        "sigma": 0.12,
        "qty": 75,
        "put": {
            "opt_type": "PE", "short_k": 100, "hedge_k": 90,
            "entry_credit": 30.0, "entry_short_ltp": 100.0, "dynamic_sl": 130.0,
        },
        "call": {
            "opt_type": "CE", "short_k": 200, "hedge_k": 210,
            "entry_credit": 30.0, "entry_short_ltp": 50.0, "dynamic_sl": 65.0,
        },
    }
    return {"orbiter_position": pos}


def test_partial_exit_not_labeled_fully_closed_when_a_leg_stays_active(monkeypatch):
    from datetime import date, datetime

    state = _partial_exit_setup(monkeypatch)
    result = pl._check_exit_orbiter(state, date(2026, 7, 22), datetime(2026, 7, 22, 11, 0))

    assert result["action"] == "EXIT_TRIGGER_ORBITER"
    exited_sides = {e["side"] for e in result["exits"]}
    assert exited_sides == {"put"}, "only the put leg should have triggered its own SL"
    assert result["fully_closed"] is False, (
        "call leg never hit an exit condition — must NOT be labeled fully_closed, "
        "or ROLL_FORWARD would fire while a leg is still open and untracked"
    )
    # The actual orphan-leg bug: position must survive with the untouched
    # call leg intact, not get wiped from state entirely.
    survivor = state["orbiter_position"]
    assert survivor is not None, "position must NOT be dropped while call leg is still open"
    assert survivor["put"] is None, "exited put leg should be cleared"
    assert survivor["call"] is not None, "surviving call leg must stay tracked"
    assert survivor["phase"] == "DIRECTIONAL_ANCHOR", (
        "reverted so _morph_check_orbiter can re-engage for the survivor later"
    )


def test_full_exit_both_legs_labeled_fully_closed(monkeypatch):
    from datetime import date, datetime

    state = _partial_exit_setup(monkeypatch)
    # Force the call leg's own SL to also trigger this time (200 -> SL-crossing value)
    monkeypatch.setattr(
        pl, "black_scholes_call",
        lambda S, K, T, r, sigma: 100.0 if K == 200 else 20.0,  # value = 80 -> hits static_sl (60)
    )
    result = pl._check_exit_orbiter(state, date(2026, 7, 22), datetime(2026, 7, 22, 11, 0))

    exited_sides = {e["side"] for e in result["exits"]}
    assert exited_sides == {"put", "call"}
    assert result["fully_closed"] is True
    assert state["orbiter_position"] is None, "both legs gone -> position must be cleared"


def test_live_mode_partial_exit_also_preserves_surviving_leg(monkeypatch):
    """Same orphan-leg fix, LIVE_ENABLED=True path — a successful broker close
    of the exited leg(s) must not clear the whole position while another leg
    is still open and untouched."""
    import pandas as pd
    from datetime import date, datetime

    class TwoLegApi(FakeApi):
        def get_quotes(self, exchange, token):
            self.calls.append(("get_quotes", {"exchange": exchange, "token": token}))
            prices = {
                "PSHORT": "100.0", "PHEDGE": "40.0",  # put value = 60 -> hits static_sl(60)
                "CSHORT": "50.0", "CHEDGE": "20.0",    # call value = 30 -> no trigger
            }
            return {"stat": "Ok", "lp": prices[token], "token": token, "exch": exchange}

    monkeypatch.setattr(pl, "LIVE_ENABLED", True)
    monkeypatch.setattr(
        pl, "combined_daily_closes",
        lambda index: pd.Series([24000.0], index=[date(2026, 7, 22)]),
    )
    api = TwoLegApi()
    monkeypatch.setattr(pl, "_shoonya_session", lambda: api)
    monkeypatch.setattr(pl.orbiter_mod, "_read_enriched_row", lambda index, today: {"atr_daily": None})
    monkeypatch.setattr(
        pl.orbiter_mod, "orbiter_tp_check",
        lambda *a, **k: pl.orbiter_mod.OrbiterExit(False, None, None, ""),
    )
    monkeypatch.setattr(pl, "_save_state", lambda state: None)
    monkeypatch.setattr(pl, "_log_ledger", lambda event: None)

    pos = {
        "index": "NIFTY",
        "expiry": "2026-08-04",
        "entry_ts": "2026-07-22T09:30:00",
        "sigma": 0.12,
        "qty": 75,
        "put": {
            "opt_type": "PE", "short_k": 100, "hedge_k": 90,
            "entry_credit": 30.0, "entry_short_ltp": 100.0, "dynamic_sl": 130.0,
            "sl_order_ids": {},
            "legs": {
                "short": {"exchange": "NFO", "tsym": "PUT_SHORT", "token": "PSHORT"},
                "hedge": {"exchange": "NFO", "tsym": "PUT_HEDGE", "token": "PHEDGE"},
            },
        },
        "call": {
            "opt_type": "CE", "short_k": 200, "hedge_k": 210,
            "entry_credit": 30.0, "entry_short_ltp": 50.0, "dynamic_sl": 65.0,
            "sl_order_ids": {},
            "legs": {
                "short": {"exchange": "NFO", "tsym": "CALL_SHORT", "token": "CSHORT"},
                "hedge": {"exchange": "NFO", "tsym": "CALL_HEDGE", "token": "CHEDGE"},
            },
        },
    }
    state = {"orbiter_position": pos}

    result = pl._check_exit_orbiter(state, date(2026, 7, 22), datetime(2026, 7, 22, 11, 0))

    assert result["action"] == "EXIT_ORBITER"
    assert {e["side"] for e in result["exits"]} == {"put"}
    assert result["fully_closed"] is False
    survivor = state["orbiter_position"]
    assert survivor is not None
    assert survivor["put"] is None
    assert survivor["call"] is not None
    assert survivor["phase"] == "DIRECTIONAL_ANCHOR"


def test_live_mode_failed_close_leg_stays_tracked_not_orphaned(monkeypatch):
    """DS review 2026-07-22: a leg whose broker close FAILS must not be
    nulled from pos — that would silently orphan a real open position with
    no further monitoring. Both put and call hit their own exit condition,
    but the put's close order is rejected by the broker."""
    import pandas as pd
    from datetime import date, datetime

    class RejectPutCloseApi(FakeApi):
        def get_quotes(self, exchange, token):
            self.calls.append(("get_quotes", {"exchange": exchange, "token": token}))
            prices = {
                "PSHORT": "100.0", "PHEDGE": "40.0",   # put value = 60 -> hits static_sl(60)
                "CSHORT": "100.0", "CHEDGE": "20.0",   # call value = 80 -> also hits static_sl(60)
            }
            return {"stat": "Ok", "lp": prices[token], "token": token, "exch": exchange}

        def place_order(self, **kwargs):
            self.calls.append(("place_order", kwargs))
            if kwargs.get("tradingsymbol") == "PUT_SHORT":
                return {"stat": "Not_Ok", "emsg": "rejected"}
            return {"stat": "Ok", "norenordno": "ORD1"}

    monkeypatch.setattr(pl, "LIVE_ENABLED", True)
    monkeypatch.setattr(
        pl, "combined_daily_closes",
        lambda index: pd.Series([24000.0], index=[date(2026, 7, 22)]),
    )
    api = RejectPutCloseApi()
    monkeypatch.setattr(pl, "_shoonya_session", lambda: api)
    monkeypatch.setattr(pl.orbiter_mod, "_read_enriched_row", lambda index, today: {"atr_daily": None})
    monkeypatch.setattr(
        pl.orbiter_mod, "orbiter_tp_check",
        lambda *a, **k: pl.orbiter_mod.OrbiterExit(False, None, None, ""),
    )
    monkeypatch.setattr(pl, "_save_state", lambda state: None)
    monkeypatch.setattr(pl, "_log_ledger", lambda event: None)

    pos = {
        "index": "NIFTY", "expiry": "2026-08-04", "entry_ts": "2026-07-22T09:30:00",
        "sigma": 0.12, "qty": 75,
        "put": {
            "opt_type": "PE", "short_k": 100, "hedge_k": 90,
            "entry_credit": 30.0, "entry_short_ltp": 100.0, "dynamic_sl": 130.0,
            "sl_order_ids": {},
            "legs": {
                "short": {"exchange": "NFO", "tsym": "PUT_SHORT", "token": "PSHORT"},
                "hedge": {"exchange": "NFO", "tsym": "PUT_HEDGE", "token": "PHEDGE"},
            },
        },
        "call": {
            "opt_type": "CE", "short_k": 200, "hedge_k": 210,
            "entry_credit": 30.0, "entry_short_ltp": 50.0, "dynamic_sl": 65.0,
            "sl_order_ids": {},
            "legs": {
                "short": {"exchange": "NFO", "tsym": "CALL_SHORT", "token": "CSHORT"},
                "hedge": {"exchange": "NFO", "tsym": "CALL_HEDGE", "token": "CHEDGE"},
            },
        },
    }
    state = {"orbiter_position": pos}

    result = pl._check_exit_orbiter(state, date(2026, 7, 22), datetime(2026, 7, 22, 11, 0))

    assert {e["side"] for e in result["exits"]} == {"put", "call"}, "both legs hit their own SL"
    assert result["fully_closed"] is False, "put's close order was rejected — not actually closed"
    survivor = state["orbiter_position"]
    assert survivor is not None, "must not be dropped while put is still open at the broker"
    assert survivor["put"] is not None, "failed close -> put must stay tracked, not orphaned"
    assert survivor["call"] is None, "call's close succeeded -> correctly cleared"
