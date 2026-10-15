"""Price one F1 event twice as of one cutoff, without and with the calibration power (C48), and print the race-win
and winning-constructor prices side by side. Read-only on the database (nothing is saved).

    python scripts/models/calib_ab.py --event 2026-18 --cutoff 2026-10-14T06:55 [--calib-power walk_forward]
                                      [--sims 10000] [--csv out.csv]

Both prices come from the same pricing path as the live book and `model combo f1` (an upcoming event priced with the
live path's entrants), the same seed and the same data, so the only difference is the calibration.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from racinglines import progress  # noqa: E402
from racinglines.db.config import get_engine  # noqa: E402
from racinglines.models import calibration as CAL  # noqa: E402
from racinglines.models import combo_job as CJ  # noqa: E402
from racinglines.models.inputs import laps_pricing as run  # noqa: E402


def prices(meas, hist, event, cutoff, sims, calib):
    run.M.CALIB_POWER = calib
    try:
        _, _, summ, ex = CJ.price_event(meas, hist, event, cutoff, n_sims=sims)
    finally:
        run.M.CALIB_POWER = None
    win = summ.set_index("driver")["win_prob"]
    team = summ.set_index("driver")["team_key"]
    return win, team, pd.Series(ex["constructor_top"]), ex["audit"].get("calib_power")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--event", required=True)
    ap.add_argument("--cutoff", required=True)
    ap.add_argument("--calib-power", default="walk_forward")
    ap.add_argument("--sims", type=int, default=10000)
    ap.add_argument("--db", default=None)
    ap.add_argument("--csv", default=None)
    a = ap.parse_args(argv)
    calib = CAL.parse(a.calib_power)
    cutoff = pd.Timestamp(a.cutoff)
    progress.update(item=f"loading data as of {cutoff}")
    meas = run.Measurements.load(get_engine(a.db))
    hist = run.history(meas)
    progress.update(item="pricing without calibration")
    w0, team, c0, _ = prices(meas, hist, a.event, cutoff, a.sims, None)
    progress.update(item=f"pricing with calib_power={calib}")
    w1, _, c1, used = prices(meas, hist, a.event, cutoff, a.sims, calib)
    print(f"{a.event} as of {cutoff} UTC, {a.sims} sims; calibration power used: {used}")
    rows = [dict(market="race_win", selection=d, team=team[d], off=w0[d], on=w1[d]) for d in w0.index]
    rows += [dict(market="race_constructor_top", selection=t, team=t, off=c0[t], on=c1.get(t)) for t in c0.index]
    out = pd.DataFrame(rows).sort_values(["market", "off"], ascending=[False, False])
    print(out.to_string(index=False, formatters=dict(off="{:.4f}".format, on="{:.4f}".format)))
    if a.csv:
        out.to_csv(a.csv, index=False)
        print(f"wrote {a.csv}")


if __name__ == "__main__":
    main()
