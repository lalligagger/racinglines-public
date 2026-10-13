"""markets/rewards.py: venue reward lists parsed from mocked responses (shapes copied from the live APIs on
2026-10-13), and only changes stored."""

import json
from datetime import datetime, timezone

import httpx

from racinglines.markets import rewards as RW
from racinglines.markets.kalshi.client import Client

PM_PAGES = {
    None: {"data": [{"condition_id": "0xABC", "rewards_min_size": 50, "rewards_max_spread": 4.5,
                     "rewards_config": [{"id": 0, "rate_per_day": 0.001, "total_rewards": 0, "start_date": "2026-10-05",
                                         "end_date": "2500-12-31"}]}], "next_cursor": "MQ=="},
    "MQ==": {"data": [], "next_cursor": "LTE="},
}
KALSHI = {"incentive_programs": [{"id": "p1", "market_id": "m1", "market_ticker": "KXF1POLE-BAH26-VER",
                                  "incentive_type": "liquidity", "incentive_description": "", "period_reward": 1000000,
                                  "discount_factor_bps": 5000, "target_size_fp": "1000.00", "paid_out": False,
                                  "start_date": "2026-10-03T03:12:00Z", "end_date": "2026-10-03T10:00:00Z"}],
          "next_cursor": ""}


def test_polymarket_pages_and_units():
    def handler(req):
        return httpx.Response(200, json=PM_PAGES[req.url.params.get("next_cursor")])
    with httpx.Client(base_url=RW.CLOB, transport=httpx.MockTransport(handler)) as c:
        [p] = RW.polymarket_programs(c)
    assert (p["market"], p["min_size"], p["max_spread"], p["rate_per_day"]) == ("0xabc", 50, 4.5, 0.001)


def test_kalshi_centi_cents_to_usd_and_deduped():
    kc = Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=KALSHI)))
    [p] = RW.kalshi_programs(kc)                     # listed under active and upcoming: stored once
    assert (p["period_reward"], p["target_size"], p["discount_bps"], p["kind"]) == (100.0, 1000.0, 5000.0, "liquidity")


def test_only_changes_stored(tmp_path):
    t = datetime(2026, 10, 13, tzinfo=timezone.utc)
    kc = Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=KALSHI)))
    progs = [dict(p, event="KXF1POLE-BAH26") for p in RW.kalshi_programs(kc)]
    rows, state = RW.changes(progs, {}, t)
    assert len(rows) == 1 and rows[0]["active"]
    state = json.loads(json.dumps(state))            # as the state file round-trips it
    assert RW.changes(progs, state, t)[0] == []      # unchanged: nothing stored
    gone, _ = RW.changes([], state, t)
    assert [(r["program"], r["active"]) for r in gone] == [("p1", False)]
    assert RW._write("kalshi", rows + gone, root=tmp_path) == 2
    df = RW.read("kalshi", root=tmp_path)
    assert list(df["active"]) == [True, False] and df["period_reward"].iloc[0] == 100.0


def test_empty_response_saves_nothing(tmp_path):
    (tmp_path / "kalshi-f1.json").write_text(json.dumps({"p1": {"market": "KXF1POLE-BAH26-VER"}}))
    out = RW.record(None, "kalshi", "f1", root=tmp_path, state_dir=tmp_path, fetch=lambda: [])
    assert out.startswith("empty") and not list(tmp_path.rglob("*.parquet"))
    assert json.loads((tmp_path / "kalshi-f1.json").read_text()) == {"p1": {"market": "KXF1POLE-BAH26-VER"}}
