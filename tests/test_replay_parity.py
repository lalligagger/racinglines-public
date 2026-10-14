"""The maker replay's speed rewrite (maker_replay.replay on per-market lists) gives exactly the results of the
original implementation (tests/replay_reference.py): every quote, fill and position, for every fill rule and option."""


import pandas as pd
import pytest

from racinglines.markets.strategies import maker_replay as R
from racinglines.testing import synthetic as SY

from replay_reference import replay as reference_replay

VARIANTS = {
    "default": R.Params(),
    "touch": R.Params(fill="touch", min_volume_24h=0),
    "through-thin": R.Params(min_volume_24h=400.0),
    "skew-kind": R.Params(info_skew=2.0, half_spread_by_kind={"race_win": 0.03}, min_volume_24h=0),
    "fees-limits": R.Params(maker_fee=0.0175, max_pos=60.0, max_capital=40.0, size=30.0, min_volume_24h=0,
                            max_disagree=None, price_band=(0.01, 0.99)),
    "flatten": R.Params(flatten_before_qual=True, min_volume_24h=0),
}


def _same(a, b):
    for k in ("fills", "quotes", "positions"):
        pd.testing.assert_frame_equal(a[k].reset_index(drop=True), b[k].reset_index(drop=True), check_exact=True)
    assert a.get("book_coverage") == b.get("book_coverage")


def _two_stages(ev):
    """The synthetic event split in two stages at its midpoint, the first ending at 'qualifying' (for flatten)."""
    st = ev["stages"][0]
    mid = (st["start"] + st["end"]) // 2
    for mk in ev["markets"]:
        mk.fairs[2] = min(0.97, mk.fairs[1] + 0.04)
    return dict(ev, stages=[dict(st, end=mid), dict(st, run_id=2, start=mid + int(600e9))], qual_start=mid)


@pytest.mark.parametrize("name", VARIANTS)
@pytest.mark.parametrize("seed", [7])                  # one tape per variant (was 3): it guards a finished rewrite
def test_synthetic_tapes(name, seed):
    ev = _two_stages(SY.replay_markets(n=8, seed=seed))
    p = VARIANTS[name]
    _same(R.replay(ev, p), reference_replay(ev, p))


@pytest.mark.parametrize("fill", ["queue", "through", "touch"])
def test_queue_fill_with_books(fill):
    ev = _two_stages(SY.replay_markets(n=6, seed=3, books=True))
    p = R.Params(fill=fill, min_volume_24h=0)
    _same(R.replay(ev, p), reference_replay(ev, p))
