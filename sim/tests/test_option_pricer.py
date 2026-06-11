"""Guards the PORCUPINE toy option pricer: the *shape* invariants the path-driver
relies on (right sign on adverse/favourable moves, theta decay, ATM richness)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sim.option_pricer import option_ltp, time_fraction

_fails = []


def chk(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        _fails.append(name)


def main():
    K = 23000
    t = time_fraction("11:00")  # mid-session, theta still alive

    # 1. Sold CE: adverse = spot UP → mark rises (drives SL on a short call).
    ce_flat = option_ltp(23000, K, "CE", t)
    ce_up = option_ltp(23150, K, "CE", t)
    chk("sold CE mark rises as spot rises", ce_up > ce_flat, f"{ce_flat}→{ce_up}")

    # 2. Sold CE: favourable = spot DOWN past OTM → mark falls toward TP.
    ce_down = option_ltp(22700, K, "CE", t)
    chk("CE mark falls as spot falls", ce_down < ce_flat, f"{ce_flat}→{ce_down}")

    # 3. Sold PE: mirror — spot DOWN → PE mark rises.
    pe_flat = option_ltp(23000, K, "PE", t)
    pe_down = option_ltp(22850, K, "PE", t)
    chk("sold PE mark rises as spot falls", pe_down > pe_flat, f"{pe_flat}→{pe_down}")

    # 4. Theta: same spot, later in the day → less extrinsic → cheaper.
    early = option_ltp(23000, K, "CE", time_fraction("09:30"))
    late = option_ltp(23000, K, "CE", time_fraction("15:25"))
    chk("ATM extrinsic decays toward the close (theta)", late < early, f"{early}→{late}")

    # 5. At the close, an OTM option is worthless (no intrinsic, no extrinsic).
    eod_otm = option_ltp(22900, K, "CE", time_fraction("15:30"))
    chk("OTM option ~0 at the close", eod_otm == 0.0, f"={eod_otm}")

    # 6. Deep ITM is at least intrinsic.
    itm = option_ltp(23500, K, "CE", time_fraction("15:30"))
    chk("deep ITM >= intrinsic at close", itm >= 500, f"={itm}")

    print(f"\noption pricer regression: {6 - len(_fails)}/6 passed")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
