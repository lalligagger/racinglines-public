"""Road cycling on the one engine (sports/road_cycling.toml [model]): the PCS results / start-list ingest
(racinglines/sources/pcs_ingest.py), the schema, the engine pricing a big synthetic road field, and the sport forecast's
[forecast] options. Hand-written CSV text only (no PCS data in git); the database test skips without Postgres."""

from datetime import date
from io import StringIO

import numpy as np
import pandas as pd
import pytest

from racinglines import sports
from racinglines.models import model_global as G
from racinglines.models import race_model as RM
from racinglines.models.race_model import Event
from racinglines.pipelines import sport_forecast as SF
from racinglines.sources import pcs
from racinglines.sources import pcs_ingest as PI

RESULTS = """race,kind,date,race_class,distance_km,vert_m,profile_score,profile_icon,rider,rider_url,nationality,position,gap_s,winner_time_s,status,source_url
tre-valli-varesine-2025,oneday,2025-10-07,1.Pro,196.0,3100,180,p4,POGACAR Tadej,rider/tadej-pogacar,SI,1,0,16800,OK,race/tre-valli-varesine/2025/result
tre-valli-varesine-2025,oneday,2025-10-07,1.Pro,196.0,3100,180,p4,PIDCOCK Thomas,rider/thomas-pidcock,GB,2,12,16800,OK,race/tre-valli-varesine/2025/result
tre-valli-varesine-2025,oneday,2025-10-07,1.Pro,196.0,3100,180,p4,ROGLIC Primoz,rider/primoz-roglic,SI,,,16800,DNF,race/tre-valli-varesine/2025/result
tre-valli-varesine-2025,oneday,2025-10-07,1.Pro,196.0,3100,180,p4,NOBODY Someone,rider/someone-nobody,IT,,,,DNS,race/tre-valli-varesine/2025/result
tre-valli-varesine-2025,oneday,2025-10-07,1.Pro,196.0,3100,180,p4,POGACAR Tadej,rider/tadej-pogacar,SI,1,0,16800,OK,race/tre-valli-varesine/2025/result
tre-valli-varesine-2025,oneday,2025-10-07,1.Pro,196.0,3100,180,p4,NO URL,,IT,5,40,16800,OK,race/tre-valli-varesine/2025/result
tour-de-france-2025,gc,2025-07-27,2.UWT,3338.8,52500,,,POGACAR Tadej,rider/tadej-pogacar,SI,1,0,274000,OK,race/tour-de-france/2025/gc
tour-de-france-2025,gc,2025-07-27,2.UWT,3338.8,52500,,,VINGEGAARD Jonas,rider/jonas-vingegaard,DK,2,262,274000,OK,race/tour-de-france/2025/gc
tour-de-france-2025,gc,2025-07-27,2.UWT,3338.8,52500,,,ROGLIC Primoz,rider/primoz-roglic,SI,,,274000,OK,race/tour-de-france/2025/gc
"""

STARTLIST = """rider,rider_url,nationality,team
POGACAR Tadej,rider/tadej-pogacar,,UAE Team Emirates XRG
PIDCOCK Thomas,rider/thomas-pidcock,,Q36.5 Pro Cycling Team
NEW Rider,rider/new-rider,,Q36.5 Pro Cycling Team
POGACAR Tadej,rider/tadej-pogacar,,UAE Team Emirates XRG
"""


def _csv(text):
    return pd.read_csv(StringIO(text))


# --- the ingest's pure parts -----------------------------------------------------------------------------------

@pytest.mark.quick
def test_results_file_parses_into_one_race_per_label():
    races, skipped = PI.parse(_csv(RESULTS), "road")
    assert skipped == 1                                             # the row without a rider_url
    assert [r["key"] for r in races] == ["tour-de-france-2025", "tre-valli-varesine-2025"]   # date order
    tdf, tre = races
    assert tdf["name"] == "Tour de France (GC)" and tdf["date"] == date(2025, 7, 27)
    assert tdf["format"]["page"] == "gc" and tdf["format"]["race_class"] == "2.UWT"
    assert tre["name"] == "Tre Valli Varesine" and tre["format"]["profile_icon"] == "p4"
    by = {r["rider_url"]: r for r in tre["rows"]}
    assert len(tre["rows"]) == 4                                    # the repeated row is dropped
    assert by["rider/tadej-pogacar"] == dict(rider_url="rider/tadej-pogacar", name="POGACAR Tadej", nation="SI",
                                             position=1, status="OK", time_ms=16_800_000, extra={"gap_s": 0.0})
    assert by["rider/thomas-pidcock"]["time_ms"] == 16_812_000
    assert by["rider/primoz-roglic"]["position"] is None and by["rider/primoz-roglic"]["status"] == "DNF"
    assert by["rider/someone-nobody"]["status"] == "DNS"
    rog = {r["rider_url"]: r for r in tdf["rows"]}["rider/primoz-roglic"]
    assert rog["status"] == "DNF" and rog["position"] is None      # "OK" with no position is not a finish


@pytest.mark.quick
def test_parse_is_stable_and_names_the_source():
    a, _ = PI.parse(_csv(RESULTS), "road")
    b, _ = PI.parse(_csv(RESULTS), "road")
    assert [r["sha"] for r in a] == [r["sha"] for r in b]          # idempotence key: same rows, same hash
    assert PI.source("road") == "pcs_road" == sports.load("road_cycling")["model"]["source"]
    assert PI.source("itt") == "pcs_itt"
    with pytest.raises(ValueError):
        PI.source("cx")
    with pytest.raises(ValueError, match="lacks columns"):
        PI.parse(_csv(RESULTS).drop(columns=["rider_url"]), "road")
    assert set(pcs.COLUMNS) >= {"race", "date", "rider", "rider_url", "position", "status"}


@pytest.mark.quick
def test_start_list_and_event_keys():
    rows = PI.parse_startlist(_csv(STARTLIST))
    assert [r["rider_url"] for r in rows] == ["rider/tadej-pogacar", "rider/thomas-pidcock", "rider/new-rider"]
    assert rows[0]["team"] == "UAE Team Emirates XRG" and rows[0]["nation"] is None
    assert PI.event_key("race/tre-valli-varesine/2026") == "tre-valli-varesine-2026"
    assert PI.event_key("race/uec-road-european-championships-itt/2026/") == "uec-road-european-championships-itt-2026"
    with pytest.raises(ValueError):
        PI.event_key("tre-valli-varesine")
    assert PI.title("giro-d-italia-2025-stage-1") == "Giro d Italia Stage 1"


# --- the schema ----------------------------------------------------------------------------------------------

@pytest.mark.quick
def test_schema_puts_road_cycling_on_the_one_engine():
    s = sports.load("road_cycling")
    assert sports.modeled("road_cycling")
    assert s["sport"]["pricing_model"] == "racinglines.models.model_global:GlobalModel"
    assert sports.audience("road_cycling") == "admin" and s["sport"]["calibration"] == "baseline"
    assert "road_cycling" in sports.admin_only()
    m = RM.model_class("road_cycling")
    assert issubclass(m, G.GlobalModel) and m.core == "results" and m.inputs == ("results",)
    assert m.cfg == dict(competition="uci_road_wt", source="pcs_road", group="team", prior=None)
    st = m.Settings.from_dict({})
    assert {k: st[k] for k in s["model"]["defaults"]} == s["model"]["defaults"]   # the schema's a priori defaults
    from racinglines.markets import private_book as house
    assert set(s["markets"]["standard_kinds"]) <= set(house.PROB_FIELD)          # the board's per-rider columns
    assert sports.kalshi_series("road_cycling")[0] == "KXCYCLING"                 # the tape settings are kept
    assert SF.options("road_cycling") == dict(field="entry_list", h2h=True)
    assert SF.spec("road_cycling") == dict(sport="road_cycling", source="pcs_road", competition="uci_road_wt",
                                           model="racinglines.models.model_global:GlobalModel")
    assert SF.options("nascar") == dict(field="last_race", h2h=False)            # unchanged for the others
    from racinglines.models import cycling as C                    # the book model still reads its blocks
    assert set(C.model_block("road")["grid"]) <= set(C.model_block("road")["defaults"])


# --- the engine on a synthetic road field ---------------------------------------------------------------------

def _road_history(n_riders=220, races=40, field=150, seed=3):
    """Races of 150 riders drawn from 220 (fields change from race to race), ~25% DNF, a few DNS."""
    rng = np.random.default_rng(seed)
    skill = rng.normal(0, 1, n_riders)
    skill[0] += 3.0                                                 # rider 1 is the strongest by far
    rows = []
    for r in range(races):
        day = pd.Timestamp("2025-02-01") + pd.Timedelta(days=7 * r)
        ids = np.r_[0, rng.choice(np.arange(1, n_riders), field - 1, replace=False)]
        perf = skill[ids] + rng.normal(0, 0.7, field)
        out = rng.random(field) < 0.25
        dns = rng.random(field) < 0.02
        order = [i for i in np.argsort(-perf) if not out[i] and not dns[i]]
        for p, i in enumerate(order, 1):
            rows.append(dict(season=day.year, race=f"r{r}", name=f"Race {r}", date=day, athlete_id=int(ids[i]) + 1,
                             position=p, status="OK", team=None))
        for i in np.flatnonzero(out | dns):
            rows.append(dict(season=day.year, race=f"r{r}", name=f"Race {r}", date=day, athlete_id=int(ids[i]) + 1,
                             position=None, status="DNS" if dns[i] else "DNF", team=None))
    return pd.DataFrame(rows)


@pytest.mark.quick
def test_the_engine_prices_a_big_road_field_with_new_riders():
    m = RM.get("road_cycling")
    data = m.load(data=_road_history())
    st = m.Settings.from_dict({"seed": 7})
    field = list(range(1, 176)) + [9001, 9002]                     # 175 known riders and two with no results
    sims = m.price(m.history(data, st), Event(id="next", season=2025, cutoff=pd.Timestamp("2025-12-01"), name="next",
                                              info={"field": field}), st, np.random.default_rng(st.rng_seed))
    assert sims.entrants == field and sims.rank.shape == (4000, len(field))
    win = (sims.rank == 1).mean(axis=0)
    assert abs(win.sum() - 1) < 1e-9 and int(np.argmax(win)) == 0  # one winner per draw; the strong rider favoured
    assert 0.05 < win[0] < 0.9                                      # favoured, not certain (noise 1.0, retirements)
    assert ((sims.rank <= 10) & sims.finished).mean(axis=0).sum() == pytest.approx(10, abs=0.5)
    assert win[-2:].max() < win[0]                                  # an unknown rider is priced, at the prior
    h = SF.head_to_heads(sims)
    assert len(h) == len(field) and len(h[0]) == len(field) - 1
    a, b = str(field[0]), str(field[1])
    assert h[0][b] + h[1][a] == pytest.approx(1.0, abs=2e-4)       # ranks never tie: P(a ahead) + P(b ahead) = 1
    assert h[0][b] > 0.5


# --- the database: ingest, schedule, forecast (skips without Postgres) ----------------------------------------

def _clean(S):
    from sqlalchemy import text
    with S() as s:
        s.execute(text("""DELETE FROM race_predictions WHERE model_run_id IN (SELECT mr.id FROM model_runs mr
                          JOIN competitions co ON co.id = mr.competition_id WHERE co.code = 'uci_road_wt')"""))
        s.execute(text("""DELETE FROM model_runs WHERE competition_id IN
                          (SELECT id FROM competitions WHERE code = 'uci_road_wt')"""))
        s.execute(text("DELETE FROM source_files WHERE path LIKE 'pcs:%'"))
        s.execute(text("DELETE FROM events WHERE source LIKE 'pcs_%'"))
        s.execute(text("""DELETE FROM athletes WHERE id IN
                          (SELECT athlete_id FROM athlete_identifiers WHERE scheme = 'pcs')"""))
        s.commit()


def test_ingest_schedule_and_forecast_in_the_database(test_engine, tmp_path):
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    S = sessionmaker(test_engine)
    _clean(S)
    hist = _road_history(n_riders=40, races=6, field=30)
    url = {a: f"rider/r{a}" for a in hist["athlete_id"].unique()}
    rows = pd.DataFrame(dict(race=hist["race"].map(lambda r: f"race-{r[1:]}-2025"), kind="oneday",
                             date=hist["date"].dt.date.astype(str), rider=hist["athlete_id"].map(lambda a: f"R {a}"),
                             rider_url=hist["athlete_id"].map(url), nationality="IT", position=hist["position"],
                             gap_s=0.0, winner_time_s=1000.0, status=hist["status"]))
    csv = tmp_path / "road_results_pcs.csv"
    rows.to_csv(csv, index=False)
    with S() as s:
        rep = PI.ingest(s, csv, "road", echo=lambda *_: None)
        s.commit()
    assert len(rep) == 6 and all(v.endswith("results") for v in rep.values())
    with S() as s:
        assert set(PI.ingest(s, csv, "road", echo=lambda *_: None).values()) == {"unchanged"}   # idempotent
        start = pd.DataFrame(dict(rider=["R 1", "R 2", "Brand New"], rider_url=["rider/r1", "rider/r2", "rider/new"],
                                  nationality=None, team=["A", "B", "B"]))
        ev, race, n = PI.schedule(s, "next-race-2099", date(2099, 6, 1), "Next Race", startlist=start)
        s.commit()
        assert n == 3 and ev.status == "scheduled"
        assert s.execute(text("SELECT count(*) FROM athlete_identifiers WHERE scheme = 'pcs'")).scalar() == len(url) + 1
    fc = SF.forecast(test_engine, "road_cycling", today=date(2099, 1, 1))
    assert len(fc["races"]) == 1 and len(fc["races"][0]["sims"].entrants) == 3
    rid = SF.save(test_engine.url.render_as_string(hide_password=False), fc)
    with S() as s:
        got = s.execute(text("SELECT count(*), bool_and(extra ? 'h2h') FROM race_predictions WHERE model_run_id = :r"),
                        dict(r=rid)).one()
        assert tuple(got) == (3, True)
    _clean(S)


# --- the Markets board: a forecast run and no exchange link is enough to show the sport ------------------------

@pytest.mark.quick
def test_board_shows_road_cycling_from_a_forecast_run_without_links(monkeypatch):
    from racinglines.markets import alerts
    from racinglines.web import board as B
    from racinglines.web import sport_status as SS
    from racinglines.web import views as V
    monkeypatch.setattr(B.data, "latest_forecasts", lambda c: pd.DataFrame([dict(competition="uci_road_wt", id=7)]))
    monkeypatch.setattr(SS, "enabled", lambda: False)
    monkeypatch.setattr(alerts, "new_links", lambda c: {})
    monkeypatch.setattr(B, "exchange_breakdown", lambda c, comps=None: [])          # no Kalshi link at all
    monkeypatch.setattr(B.data, "q", lambda conn, sql, **p: pd.DataFrame([dict(id=3)]) if "FROM competitions" in sql
                        else pd.DataFrame(columns=["race_id"]))
    monkeypatch.setattr(B.data, "run_race_targets", lambda c, run: pd.DataFrame([dict(
        target="race:tre-valli-varesine-2026", race_id=11, event_id=5, event_name="Tre Valli Varesine",
        start_date=date(2026, 10, 6), status="scheduled", venue=None, source_key="tre-valli-varesine-2026", n=150)]))
    cards = []

    def card(c, race_id, maker_id, show_kind="race_win"):
        cards.append(race_id)
        return dict(info=dict(race_id=race_id, event_id=5, status="scheduled"), top=[], venues=[], outcomes=450)
    monkeypatch.setattr(B, "_card", card)
    monkeypatch.setattr(B, "season_matrix", lambda c, code, maker: (None, None, pd.DataFrame()))
    monkeypatch.setattr(B, "venue_summary", lambda df: [])
    monkeypatch.setattr(V, "latest_season_strategy", lambda c, code: None)
    sync = []
    monkeypatch.setattr(B, "event_sync", lambda c, ids, venues: sync.append((ids, venues)) or {})
    got = B.board(object(), 1, only="uci_road_wt")
    assert [s["code"] for s in got] == ["uci_road_wt"] and cards == [11]
    s = got[0]
    assert s["run"]["id"] == 7 and not s["tape"] and s["calibration"] == "baseline" and s["exchanges"] == []
    assert sync == [([5], ["kalshi"])]                             # the missing Kalshi prices are flagged, not hidden
    assert B.board(object(), 1, only="uci_road_wt", hide=frozenset({"uci_road_wt"})) == []   # hidden from non-admins
