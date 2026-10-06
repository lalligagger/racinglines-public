"""Portable preview checks: synthetic quotes/models only, no database or network."""

import csv
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from racinglines.markets.strategies import taker_weekend as rb
from racinglines.pipelines import profiles
from racinglines.pipelines import sweep_settings as ss
from scripts import strategy_preview as preview

pytestmark = pytest.mark.quick
ROOT = Path(__file__).resolve().parents[1]


def link(**changes):
    return dict(
        token_id="yes-token",
        condition_id="condition",
        prediction="race_h2h",
        athlete_id=1.0,
        params={"opponent_id": 2.0},
        closed=False,
        last_bid=0.35,
        last_ask=0.40,
        synced_at="2026-10-05T12:00:00Z",
        question="One ahead of Two?",
        outcome="One",
        invert=False,
        **changes,
    )


def snapshot():
    return {
        "schema_version": 1,
        "asof": "2026-10-05 12:01:00",
        "commit": "code",
        "source_run": 17,
        "event_key": "2026-99",
        "cutoff": "2026-10-05 10:00:00",
        "data_key": "inputs",
        "sizing": {"bankroll": 1000, "max_market": 50, "max_total": 250},
        "snapshot": {
            "polymarket": {"links": [link()], "volumes": {"condition": 0}},
            "kalshi": {"links": [], "volumes": {}},
        },
    }


def frozen_check(value):
    preview.validate_frozen(
        value,
        commit="code",
        source_run=17,
        event_key="2026-99",
        cutoff="2026-10-05 10:00:00",
        data_key="inputs",
    )


@pytest.mark.parametrize("value", [2, 2.0, "2"])
def test_integer_h2h_id(value):
    assert preview.integer_id(value) == "2"


@pytest.mark.parametrize("value", [2.1, None, float("nan"), True])
def test_invalid_h2h_id(value):
    with pytest.raises(ValueError, match="integer ID"):
        preview.integer_id(value)


@pytest.mark.parametrize("key", ["commit", "source_run", "event_key", "cutoff", "data_key"])
def test_frozen_identity_guard(key):
    frozen = snapshot()
    frozen_check(frozen)
    frozen[key] = "different"
    with pytest.raises(ValueError, match=key):
        frozen_check(frozen)


def test_frozen_empty_venue_and_liquidity_guards():
    frozen = snapshot()
    frozen_check(frozen)
    del frozen["snapshot"]["kalshi"]
    with pytest.raises(ValueError, match="both venues"):
        frozen_check(frozen)
    frozen = snapshot()
    frozen["snapshot"]["polymarket"]["volumes"] = {}
    with pytest.raises(ValueError, match="liquidity"):
        frozen_check(frozen)
    frozen = snapshot()
    frozen["snapshot"]["polymarket"]["volumes"]["condition"] = float("nan")
    with pytest.raises(ValueError, match="liquidity"):
        frozen_check(frozen)


def test_unsupported_markets_and_fields_fail_closed():
    with pytest.raises(ValueError, match="Unsupported venue"):
        preview.validate_links([link()], "kalshi")
    unsupported = link()
    unsupported["prediction"] = "race_top10"
    with pytest.raises(ValueError, match="Unsupported prediction"):
        preview.validate_links([unsupported], "polymarket")
    unsupported = link()
    unsupported["params"]["unimplemented"] = 1
    with pytest.raises(ValueError, match="Unsupported market parameters"):
        preview.validate_links([unsupported], "polymarket")
    del unsupported["last_bid"]
    with pytest.raises(ValueError, match="Missing link fields"):
        preview.validate_links([unsupported], "polymarket")


def market(key="one", fair=0.8, tradeable=True):
    return {
        "key": key,
        "kind": "race_h2h",
        "subject": key,
        "outcome": None,
        "stages": [
            {
                "label": "preview now",
                "t": pd.Timestamp("2026-10-05"),
                "fair": fair,
                "price": 0.375,
                "bid": 0.35,
                "ask": 0.40,
                "tradeable": tradeable,
            }
        ],
    }


@pytest.mark.parametrize("sizing,kelly", [("HK", 0.5), ("QK", 0.25)])
def test_sizing_touch_slippage_and_custom_caps(sizing, kelly):
    settings = ss.Settings.from_dict(profiles.PROFILES["T1"]["settings"])
    params = preview.sizing_params(
        settings,
        profiles.PROFILES["T1"],
        sizing,
        bankroll=1000,
        max_market=1000,
        max_total=1000,
    )
    trades, _ = rb.run_weekend([market()], params)
    row = trades.iloc[0]
    cost_per_share = 0.40 + settings["cost"]
    expected = 1000 * kelly * (0.8 - cost_per_share) / (1 - cost_per_share)
    assert row["price"] == pytest.approx(cost_per_share)
    assert row["shares"] * row["price"] == pytest.approx(expected)
    params = preview.sizing_params(
        settings,
        profiles.PROFILES["T1"],
        sizing,
        bankroll=2000,
        max_market=30,
        max_total=65,
    )
    trades, _ = rb.run_weekend([market(str(i)) for i in range(6)], params)
    costs = trades["shares"] * trades["price"]
    assert max(costs) <= 30 + 1e-6
    assert sum(costs) == pytest.approx(65)


@pytest.mark.parametrize("field,value", [("thin_edge_mult", 2), ("venue", "kalshi"), ("size", 25)])
def test_unsupported_profile_settings(field, value):
    settings = ss.Settings.from_dict({field: value})
    with pytest.raises(ValueError, match="Unsupported"):
        preview.sizing_params(settings, profiles.PROFILES["T1"], "HK")


def test_original_sizing_preserves_supported_profile_fields():
    settings = ss.Settings.from_dict({"kelly": 0.4, "bankroll": 2000, "max_deployed": 150})
    params = preview.sizing_params(settings, profiles.PROFILES["T1"], "original")
    assert (params.kelly, params.bankroll, params.max_deployed) == (0.4, 2000, 150)


def test_rejected_decisions_cover_every_market():
    details = {
        key: {
            "market_key": key,
            "fair_yes": 0.8,
            "bid": 0.35,
            "ask": 0.40,
            "edge_threshold": 0.05,
        }
        for key in ("liquid", "dry", "excluded", "no-fair")
    }
    details["no-fair"]["fair_yes"] = None
    reasons = dict(
        liquid="",
        dry="zero recorded tape",
        excluded="market kind excluded",
        **{"no-fair": "no probability"},
    )
    links = {key: link() for key in details}
    params = rb.TakerParams(kelly=0.5, bankroll=1000, max_deployed=250)
    passing, _ = rb.run_weekend([market("liquid")], params)
    watched, _ = rb.run_weekend([market("dry")], params)
    rows = preview.decision_rows(details, reasons, links, passing, watched, "HK")
    assert {row["market_key"] for row in rows} == set(details)
    for row in rows:
        if row["status"] != "picked":
            assert row["cost"] == row["shares"] == 0
            assert row["reasons"]
    dry = next(row for row in rows if row["market_key"] == "dry")
    assert 0 < dry["standalone_watchlist_cost"] <= 50


@pytest.fixture
def workspace_folder():
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="preview-tests-", dir=reports) as folder:
        yield Path(folder)


def mocked_compute(monkeypatch, folder, *, writable=False, mutation=None, sims=4000, draws=None, failure=None):
    import sqlalchemy

    from racinglines.db import reads
    from racinglines.models.position_sim import pricing

    frozen = snapshot()
    frozen["commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if mutation:
        mutation(frozen)
    path = folder / "frozen.json"
    path.write_text(json.dumps(frozen))
    engine, conn = MagicMock(), MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.scalar.return_value = "off" if writable else "on"
    conn.execute.return_value.mappings.return_value.one.return_value = {
        "id": 1,
        "race_id": 1,
        "venue": "test",
    }
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(
        reads,
        "model_run",
        lambda *a: {
            "params": {
                "cutoff": frozen["cutoff"],
                "event_key": frozen["event_key"],
                "data_key": "inputs",
                "model_settings": {"sims": 16000},
            }
        },
    )
    sql_reads = []

    def read_sql(query, connection, **kwargs):
        assert connection is conn
        if failure == "database":
            raise RuntimeError("synthetic database read failure")
        sql_reads.append(str(query))
        assert "market_links" not in str(query), "Frozen empty venue must never read current links"
        return pd.DataFrame()

    monkeypatch.setattr(pd, "read_sql", read_sql)
    meas = MagicMock()
    monkeypatch.setattr(pricing.Measurements, "from_frames", lambda *frames: meas)
    monkeypatch.setattr(ss, "data_key", lambda *a: "inputs")
    monkeypatch.setattr(pricing, "history", lambda *a: None)
    summary = pd.DataFrame([{"athlete_id": 1, "h2h": {"2": 0.8}}])

    def price_race(*args, **kwargs):
        if failure == "model":
            raise RuntimeError("synthetic model pricing failure")
        if draws is not None:
            draws.append(kwargs["rng"].random())
        return summary, {"audit": {}, "constructor_top": {}}

    monkeypatch.setattr(pricing, "price_race", price_race)
    from racinglines.pipelines import signals

    monkeypatch.setattr(signals, "_entrants", lambda *a: None)
    monkeypatch.setattr(reads, "model_prob", lambda *a: (0.8, None))
    args = SimpleNamespace(
        snapshot=str(path),
        source_run=17,
        event="2026-99",
        sims=sims,
        bankroll=1000,
        max_market=50,
        max_total=250,
    )
    return preview.compute(args), engine, sql_reads


def test_compute_frozen_full_coverage_float_h2h_and_render(monkeypatch, workspace_folder):
    data, engine, sql_reads = mocked_compute(monkeypatch, workspace_folder)
    assert len(sql_reads) == 3
    engine.dispose.assert_called_once()
    assert len(data["checks"]) == 66
    assert data["coverage"]["kalshi"]["markets"] == 0
    assert len(data["decisions"]) == 22
    assert all(row["fair_yes"] == 0.8 for row in data["decisions"])
    assert all(row["status"] == "not picked" and row["cost"] == 0 for row in data["decisions"])
    assert all(row["reasons"] for row in data["decisions"])
    assert data["snapshot"]["polymarket"]["links"][0]["params"]["opponent_id"] == 2
    preview.render(data, workspace_folder / "rendered")
    for profile in data["profiles"]:
        directory = workspace_folder / "rendered" / profile
        with (directory / "picked.csv").open() as f:
            assert list(csv.DictReader(f)) == []
        with (directory / "considered-not-picked.csv").open() as f:
            assert len(list(csv.DictReader(f))) == 2
    report = (workspace_folder / "rendered" / "report.md").read_text()
    for text in (
        "2026-99",
        "$1,000 balance",
        "$250 aggregate cap",
        "midpoint",
        "not proof",
        "No fetch",
    ):
        assert text in report
    bigger, _, _ = mocked_compute(monkeypatch, workspace_folder, sims=16000)
    assert bigger["snapshot"] == data["snapshot"]
    assert bigger["asof"] == data["asof"]


def test_compute_refuses_writable_connection(monkeypatch, workspace_folder):
    with pytest.raises(RuntimeError, match="writable"):
        mocked_compute(monkeypatch, workspace_folder, writable=True)


@pytest.mark.parametrize("failure", ["database", "model"])
def test_readonly_failures_are_not_empty_results(monkeypatch, workspace_folder, failure):
    with pytest.raises(RuntimeError, match=f"synthetic {failure}"):
        mocked_compute(monkeypatch, workspace_folder, failure=failure)


def test_compute_default_seed_preserves_literal_42(monkeypatch, workspace_folder):
    import numpy as np

    draws = []
    mocked_compute(monkeypatch, workspace_folder, draws=draws)
    assert len(draws) == 4
    assert draws == [np.random.default_rng(42).random()] * 4


def test_compute_honors_explicit_profile_seed(monkeypatch, workspace_folder):
    import numpy as np

    profile = profiles.PROFILES["T1"]
    monkeypatch.setitem(profiles.PROFILES, "T1", dict(profile, settings=dict(profile["settings"], seed=123)))
    draws = []
    mocked_compute(monkeypatch, workspace_folder, draws=draws)
    assert draws[0] == np.random.default_rng(123).random()
    assert draws[1:] == [np.random.default_rng(42).random()] * 4


def test_compute_refuses_changed_frozen_sizing(monkeypatch, workspace_folder):
    with pytest.raises(ValueError, match="sizing"):
        mocked_compute(
            monkeypatch,
            workspace_folder,
            mutation=lambda frozen: frozen["sizing"].update(bankroll=2000),
        )


def test_blend_halves_independent_openings():
    base = {
        "venue": "polymarket",
        "market_key": "x",
        "side": "YES",
        "sizing": "HK",
        "status": "picked",
        "cost": 40,
        "shares": 100,
        "reasons": "",
        "standalone_watchlist_cost": 0,
        "standalone_watchlist_shares": 0,
    }
    data = {
        "rows": [
            dict(base, profile="T1", status="passes preview filters"),
            dict(base, profile="T8", cost=20, shares=50, status="passes preview filters"),
        ],
        "decisions": [
            dict(base, profile="T1"),
            dict(base, profile="T8", cost=20, shares=50),
        ],
        "checks": [],
    }
    preview.blend(data)
    assert data["rows"][-1]["cost"] == data["decisions"][-1]["cost"] == 30
    assert data["rows"][-1]["shares"] == 75


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--source-run", "17"],
        ["--event", "2026-99"],
        ["--render", "file"],
        ["--event", "x", "--source-run", "1", "--bankroll", "nan"],
    ],
)
def test_cli_requires_explicit_safe_inputs(argv):
    with pytest.raises(SystemExit) as error:
        preview.main(argv)
    assert error.value.code == 2
