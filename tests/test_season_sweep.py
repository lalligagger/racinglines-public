"""The season sweep for any sport (pipelines/season_sweep.py): the schema decides the engine, stages, kinds, venues and
settings; the search queues another sport's sweep like F1's; then a tiny NASCAR sweep on Kalshi on the test database
(the fixtures' 2026 Cup races, synthetic links and tape) whose params carry the sport and the venue."""

import pytest
from sqlalchemy import text

from racinglines.pipelines import position_replay as P
from racinglines.pipelines import search as S
from racinglines.pipelines import season_sweep as SW
from racinglines.pipelines import sweep_settings as SS


@pytest.mark.quick
def test_the_schema_names_the_engine_kinds_venues_and_settings():
    assert SW.engine_of("f1") == "sessions" and SW.engine_of("nascar") == SW.engine_of("motogp") == "weekend"
    assert SW.settings_class("f1") is SS.Settings                          # F1: the sweep's own settings, unchanged
    assert SW.kinds("f1") == SS.KINDS and SW.kinds("nascar") == tuple(P.spec("nascar")["kinds"])
    assert SW.venues("f1") == ("polymarket", "kalshi", "og")               # OG.com lists F1 (exchanges/og.toml)
    assert SW.venues("nascar") == ("polymarket", "kalshi", "og") and SW.venues("motogp") == ("polymarket", "kalshi")
    assert not SW.supports("mtb_dh") and not SW.supports("indycar")       # no [sweep] engine / no pricing model
    cls = SW.settings_class("nascar")
    st = cls.from_dict()
    labels = tuple(label for label, _ in P.spec("nascar")["stages"])
    assert st["taker_stages"] == labels and st["late_stages"] == ("race eve",)
    assert st["market_kinds"] == SW.kinds("nascar") and SS.venue_of(st) == "polymarket"
    assert "variant" not in st and {"sims", "noise", "min_edge", "half_spread", "venue"} <= set(st)
    assert st.model_key == P.model_for(P.spec("nascar")).Settings.from_dict().model_key   # the model's own settings
    assert SS.venue_of(cls.from_dict({"venue": "kalshi"})) == "kalshi"
    with pytest.raises(ValueError):
        cls.from_dict({"venue": "og", "market_kinds": "race_pole"})       # not a NASCAR sweep kind
    with pytest.raises(ValueError):
        SW.settings_class("motogp").from_dict({"venue": "og"})            # OG.com doesn't list MotoGP


@pytest.mark.quick
def test_the_stage_mode_is_an_explicit_setting_defaulting_to_the_schema():
    """`stages`: "weekend" (the fixed [replay] stages) or "sessions" (the session schedule); unset = the schema's
    [sweep] stages, and unset it stays out of every key, so earlier results and ids are unchanged."""
    assert SW.modes("f1") == ("sessions",)
    assert set(SW.modes("nascar")) == set(SW.modes("motogp")) == {"weekend", "sessions"}     # schedules since C12a
    f1 = SS.Settings.from_dict()
    assert f1["stages"] is None and SS.Settings.from_dict({"stages": "sessions"}).key == f1.key
    assert SW.mode_of("f1", f1) == "sessions"
    with pytest.raises(ValueError, match="stages"):
        SW.mode_of("f1", SS.Settings.from_dict({"stages": "weekend"}))   # F1 has no fixed weekend stages
    cls = SW.settings_class("nascar")
    assert cls.from_dict({"stages": "weekend"}).key == cls.from_dict().key
    assert SW.mode_of("nascar", cls.from_dict()) == "weekend"
    assert SW.mode_of("nascar", cls.from_dict({"stages": "sessions"})) == "sessions"   # opt-in; weekend stays default
    assert cls.from_dict({"stages": "sessions"}).key != cls.from_dict().key


@pytest.mark.quick
def test_the_search_queues_another_sports_sweep(tmp_path):
    q = tmp_path / "q.toml"
    q.write_text('[search]\nname = "t"\n[[job]]\nsport = "nascar"\nkind = "sweep"\nvenue = "kalshi"\nyear = 2025\n'
                 'min_edge = 0.08\n[[job]]\nsport = "nascar"\nyear = 2025\n')
    _, jobs, _ = S.load(q)
    sweeps = [j for j in jobs if j["kind"] == "sweep"]
    assert [(j["sport"], j["venue"], j["settings"]["min_edge"]) for j in sweeps] == [
        ("nascar", "kalshi", 0.05), ("nascar", "kalshi", 0.08)]                # its own baseline first, same venue
    assert any(j["kind"] == "walk_forward" and j["sport"] == "nascar" for j in jobs)   # the default kind is unchanged
    assert S.argv(sweeps[1])[3:] == ["nascar", "sweep", "--year", "2025", "--no-fetch", "--save", "--venue", "kalshi",
                                     "--min-edge", "0.08"]
    assert S._grid_key(sweeps[1]) is None and S._title(sweeps[1]).startswith("nascar sweep ")
    bare = {k: v for k, v in sweeps[1].items() if k not in ("settings", "id")}
    assert S.job_id(bare) == sweeps[1]["id"] != S.job_id(dict(bare, venue="polymarket"))
    assert S.kinds_for("nascar") == ("walk_forward", "sweep") and S.kinds_for("mtb_dh") == ("walk_forward",)
    with pytest.raises(ValueError, match="venue"):
        S.load(_q(tmp_path, '[[job]]\nsport = "motogp"\nkind = "sweep"\nvenue = "og"\n'))
    with pytest.raises(ValueError, match="unknown keys"):
        S.load(_q(tmp_path, '[[job]]\nsport = "nascar"\nkind = "sweep"\nvariant = "gridq"\n'))   # an F1 setting


def _q(tmp_path, body):
    p = tmp_path / "q2.toml"
    p.write_text('[search]\nname = "t"\n' + body)
    return p


# --- a NASCAR sweep on the test database ------------------------------------------------------------------

from test_nascar import db, raw  # noqa: E402,F401  (fixtures)
from test_nascar_links import world  # noqa: E402,F401  (fixture: the fixtures' 2026 Cup races and drivers)
from test_position_replay import _seed, _wipe  # noqa: E402


def test_a_tiny_nascar_sweep_on_kalshi_carries_sport_and_venue(world, test_engine):
    from conftest import TEST_DB
    from racinglines.pipelines import weekend_sweep as WS
    with world() as s:
        rs = P.races(s.connection(), P.spec("nascar"), [2026])
        assert len(rs) >= 2
        race = rs.iloc[-1]
        res = P.race_results(s.connection(), race.race_id)
        top = res.sort_values("position")["athlete_id"].astype(int).tolist()
        _wipe(s)
        _seed(s, race, res, {top[0]: 0.05, top[1]: 0.40, top[2]: 0.25, top[-1]: 0.30})      # a coherent group
        rid = None
        try:
            st = SW.settings_class("nascar").from_dict({"venue": "kalshi", "sims": 500, "market_kinds": "race_win"})
            out = SW.run(test_engine, TEST_DB, "nascar", 2026, settings=st, echo=lambda *a: None)
            p = out["params"]
            assert p["sport"] == "nascar" and p["venue"] == "kalshi" and p["stages_mode"] == "weekend"
            assert p["settings"]["venue"] == "kalshi" and p["settings_key"] == st.key and p["kinds"] == ["race_win"]
            assert p["taker_fee"] == 0.07 and p["model"]                          # Kalshi's fee schedule on the taker
            w = out["weekends"].set_index("event_key")
            assert list(w.index) == [race.event_key]                             # only the race with markets
            assert w.loc[race.event_key, "markets"] == 4 and w.loc[race.event_key, "tradeable_pre"] == 4
            assert set(out["totals"]) == set(WS.TAKER_MODES) | set(WS.MAKERS)    # every taker mode and maker variant
            assert out["totals"]["update"]["weekends"] == 1 and len(out["trades"])
            assert out["trades"]["pnl"].notna().all()                            # settled on the classification
            assert set(out["trades"]["stage"]) <= {"T-3d", "T-1d", "race eve"}
            again = SW.run(test_engine, TEST_DB, "nascar", 2026, rounds=[len(rs)], settings=st, echo=lambda *a: None)
            assert again["totals"] == out["totals"]                              # one race priced alone: the same
            last = SW.run(test_engine, TEST_DB, "nascar", 2026, echo=lambda *a: None,
                          settings=SW.settings_class("nascar").from_dict(
                              {"venue": "kalshi", "sims": 500, "market_kinds": "race_win", "taker_stages": "race eve"}))
            assert set(last["trades"]["stage"]) <= {"race eve"}                  # entry timing from the schema's labels
            rid = SW.save(TEST_DB, "nascar", 2026, None, out)
            row = s.execute(text("""SELECT mr.kind, mr.params, co.code FROM model_runs mr
                                    JOIN competitions co ON co.id = mr.competition_id WHERE mr.id = :i"""),
                            dict(i=rid)).one()
            assert row[0] == "sweep" and row[2] == "nascar_cup"
            assert row[1]["sport"] == "nascar" and row[1]["venue"] == "kalshi" and row[1]["year"] == 2026
        finally:
            s.rollback()
            if rid:
                s.execute(text("DELETE FROM model_runs WHERE id = :i"), dict(i=rid))
                s.commit()
            _wipe(s)


@pytest.mark.quick
def test_f1_taker_pays_the_venues_fee():
    """The F1 sweep on OG.com: OG.com's flat fee per contract on the taker's cost; Polymarket and Kalshi as before."""
    from racinglines.pipelines import weekend_sweep as WS
    st = SS.Settings.from_dict({"venue": "og"})
    base, plist = WS.taker_params(st)
    assert base.cost == pytest.approx(0.01 + 0.02) and base.taker_fee == 0.0    # OG.com: its flat fee per contract
    assert [q.mode for q in plist] == list(WS.TAKER_MODES)
    assert WS.taker_params(SS.Settings.from_dict())[0].cost == 0.01             # Polymarket: as before
    k = WS.taker_params(SS.Settings.from_dict({"venue": "kalshi"}))[0]
    assert k.cost == 0.01 and k.taker_fee == 0.07
