"""Polymarket Grand Prix names -> our races (markets/polymarket/sync.py GP_ALIASES). Synthetic race rows,
no database."""

from datetime import date, datetime, timezone

import pytest

from racinglines.markets.polymarket.sync import Resolver

pytestmark = pytest.mark.quick


def _resolver():
    r = Resolver.__new__(Resolver)
    r.races = [(133, "Azerbaijan Grand Prix FORMULA 1 QATAR AIRWAYS AZERBAIJAN GRAND PRIX 2026", "2026-15", date(2026, 9, 26)),
               (134, "Bahrain Grand Prix FORMULA 1 GULF AIR BAHRAIN GRAND PRIX IN MALAYSIA 2026", "2026-16", date(2026, 10, 4)),
               (135, "Singapore Grand Prix FORMULA 1 SINGAPORE AIRLINES SINGAPORE GRAND PRIX 2026", "2026-17", date(2026, 10, 11))]
    return r


@pytest.mark.parametrize("name", ["Bahrain Grand Prix", "Malaysia Grand Prix", "Malaysian Grand Prix",
                                  "Sepang Grand Prix", "Kuala Lumpur Grand Prix", "Bahrain Grand Prix in Malaysia"])
def test_round_16_names_resolve(name):
    end = datetime(2026, 10, 4, 9, tzinfo=timezone.utc)
    assert _resolver().race(name, end) == (134, "2026-16")


def test_other_rounds_unchanged():
    r = _resolver()
    assert r.race("Singapore Grand Prix")[1] == "2026-17"
    assert r.race("Azerbaijan Grand Prix")[1] == "2026-15"
    # the original April Bahrain market's date is outside the match window: not round 16
    assert r.race("Bahrain Grand Prix", datetime(2026, 4, 12, tzinfo=timezone.utc)) == (None, None)
