import math

import pytest

from racinglines.reporting.metrics import curve_stats


pytestmark = pytest.mark.quick


def test_curve_stats_tracks_cumulative_returns_and_drawdown():
    stats, cumulative = curve_stats([100.0, -40.0, -80.0, 60.0])

    assert cumulative == [100.0, 60.0, -20.0, 40.0]
    assert stats["pnl"] == 40.0
    assert stats["weekends"] == 4
    assert stats["weekends_up"] == 2
    assert stats["max_drawdown"] == 120.0
    assert stats["mean_weekend"] == 10.0
    assert stats["sharpe"] == pytest.approx(10.0 / math.sqrt(21200 / 3) * math.sqrt(24))