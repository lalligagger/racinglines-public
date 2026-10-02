"""The global results model (racinglines/models/model_global.py): one sport-agnostic model pointed at a schema.
Synthetic data only; no network, no database."""

import numpy as np
import pandas as pd
import pytest

from racinglines import sports
from racinglines.core import walk_forward as WF
from racinglines.models import model_global as G
from racinglines.models import race_model as RM
from racinglines.models.race_model import Event

pytestmark = pytest.mark.quick

SCHEMA = """
[sport]
code = "toy_global"
name = "Toy global"
result_kind = "position"
model_family = "global"
display_order = 9
pricing_model = "racinglines.models.model_global:GlobalModel"

[competition]
code = "toy_global_cup"
name = "Toy Global Cup"

[model]
source = "toy_src"
group = "team"
prior = "rating"

[model.defaults]
noise = 0.6
"""


@pytest.fixture
def toy(tmp_path, monkeypatch):
    (tmp_path / "sports").mkdir()
    for f in sports.SCHEMAS.glob("*.toml"):
        (tmp_path / "sports" / f.name).write_text(f.read_text())
    (tmp_path / "sports" / "toy_global.toml").write_text(SCHEMA)
    monkeypatch.setattr(sports, "SCHEMAS", tmp_path / "sports")
    sports.load.cache_clear()
    yield tmp_path
    sports.load.cache_clear()


def world(seed=3, riders=40, races=10, field=(12, 30), strength_sd=1.2, noise=0.7):
    """Three seasons of races where each entrant has a fixed strength and only some of the riders start each race."""
    rng = np.random.default_rng(seed)
    strength = rng.normal(0, strength_sd, riders)
    rows = []
    for season in (2024, 2025, 2026):
        for r in range(races):
            ids = rng.choice(riders, size=rng.integers(*field), replace=False)
            order = np.argsort(-(strength[ids] + rng.normal(0, noise, len(ids))))
            date = pd.Timestamp(f"{season}-03-01") + pd.Timedelta(days=14 * r)
            rows += [dict(season=season, race=f"{season}-{r}", date=date, athlete_id=int(ids[i]), position=p,
                          status="OK") for p, i in enumerate(order, 1)]
    return pd.DataFrame(rows)


def race_rows(race, date, order, season=2025, status=None, team=None, rating=None):
    """One race: `order` = athlete ids in finishing order; `status`/`team`/`rating` map an id to its value."""
    rows = []
    for p, a in enumerate(order, 1):
        row = dict(season=season, race=race, date=pd.Timestamp(date), athlete_id=a, position=p,
                   status=(status or {}).get(a, "OK"))
        if team:
            row["team"] = team.get(a)
        if rating:
            row["prior"] = rating.get(a)
        rows.append(row)
    return rows


def price(model, data, field, cutoff="2026-01-01", seed=1, **settings):
    st = model.Settings.from_dict({"sims": 4000, "seed": seed, "half_life_days": 3650, "uncertainty": 0, **settings})
    ev = Event(id="new", season=2026, cutoff=pd.Timestamp(cutoff), info={"field": field})
    return model.price(model.history(data, st), ev, st, np.random.default_rng(st.rng_seed))


def beats(sims, a, b):
    return float((sims.rank[:, sims.index(a)] < sims.rank[:, sims.index(b)]).mean())


def test_runs_through_the_engine_and_beats_a_model_that_learned_nothing(toy):
    m = RM.get("toy_global")
    data = m.load(data=world())
    kinds = ["race_win", "race_podium", "race_h2h"]
    learned = WF.run(m, data, m.Settings.from_dict({"sims": 400, "seed": 5}), seasons=[2025, 2026], kinds=kinds,
                     echo=lambda s: None)
    flat = WF.run(m, data, m.Settings.from_dict({"sims": 400, "seed": 5, "prior_weight": 100, "uncertainty": 0}),
                  seasons=[2025, 2026], kinds=kinds, echo=lambda s: None)
    assert set(learned["events"]["season"]) == {2025, 2026} and len(learned["events"]) == 20
    # each event is priced for exactly its start list (variable field sizes), not every rider ever seen
    assert learned["events"]["n_entrants"].between(12, 29).all()
    for kind in kinds:
        a = learned["calibration"].query("season == 'all' and kind == @kind")["logloss"].iloc[0]
        b = flat["calibration"].query("season == 'all' and kind == @kind")["logloss"].iloc[0]
        assert a < b, kind


def test_prices_use_nothing_from_the_cutoff_on(toy):
    m = RM.get("toy_global")
    base = world()
    base["team"] = base["athlete_id"] % 4
    base["prior"] = base["athlete_id"].astype(float)
    st = m.Settings.from_dict({"sims": 300, "seed": 9, "group_weight": 1.0, "rating_weight": 1.0})
    ev = m.events(m.load(data=base), st, [2026])[3]

    def run(frame):
        d = m.load(data=frame)
        return m.price(m.history(d, st), ev, st, np.random.default_rng(1))

    late = base["date"] >= ev.cutoff
    scrambled = base.copy()
    scrambled.loc[late, "position"] = scrambled.loc[late].groupby("race")["position"].transform(lambda p: p.max() + 1 - p)
    scrambled.loc[late, "team"] = 9
    scrambled.loc[late, "prior"] = -scrambled.loc[late, "prior"]
    assert np.array_equal(run(base).rank, run(scrambled).rank)

    early = base["date"] < ev.cutoff - pd.Timedelta(days=60)         # positive control: the past does move prices
    flipped = base.copy()
    flipped.loc[early, "position"] = flipped.loc[early].groupby("race")["position"].transform(lambda p: p.max() + 1 - p)
    assert not np.array_equal(run(base).rank, run(flipped).rank)


def test_second_of_a_big_field_outweighs_second_of_a_small_one(toy):
    m = RM.get("toy_global")
    rows = []
    for k in range(4):
        rows += race_rows(f"big{k}", f"2025-0{k + 1}-01", [100 + k] + [1] + list(range(101 + 4, 101 + 4 + 98)))
        rows += race_rows(f"small{k}", f"2025-0{k + 1}-15", [200 + k, 2, 205 + k, 210 + k, 215 + k])
    sims = price(m, m.load(data=pd.DataFrame(rows)), [1, 2])
    assert beats(sims, 1, 2) > 0.65


def test_a_single_great_start_is_shrunk_below_a_long_record(toy):
    m = RM.get("toy_global")
    rows = []
    for k in range(10):
        order = [20 + k, 2] + [30 + i for i in range(18)]            # rider 2 is second in all ten races of twenty
        if k == 9:
            order = [1, 2] + [30 + i for i in range(18)]             # rider 1's only start is a win
        rows += race_rows(f"r{k}", f"2025-0{k % 9 + 1}-{10 + k}", order)
    data = m.load(data=pd.DataFrame(rows))
    assert beats(price(m, data, [1, 2]), 2, 1) > 0.55                # shrunk: the record wins
    assert beats(price(m, data, [1, 2], prior_weight=0), 1, 2) > 0.5  # unshrunk: the single win wins


def test_retirements_are_modelled_and_can_be_switched_off(toy):
    m = RM.get("toy_global")
    rows = []
    for k in range(8):
        rows += race_rows(f"r{k}", f"2025-0{k + 1}-01", list(range(1, 11)), status={10: "DNF"})
    data = m.load(data=pd.DataFrame(rows))
    on = price(m, data, list(range(1, 11)))
    assert on.finished[:, on.index(10)].mean() < 0.5 and on.finished[:, on.index(1)].mean() > 0.9
    assert on.rank[:, on.index(10)].mean() > on.rank[:, on.index(1)].mean()
    assert price(m, data, list(range(1, 11)), dnf=False).finished.all()


def test_group_prior_lifts_a_newcomer_on_a_strong_team(toy):
    m = RM.get("toy_global")
    team = {**{a: "S" for a in (1, 2, 3, 4, 9)}, **{a: "W" for a in (5, 6, 7, 8, 10)}}
    rows = []
    for k in range(6):
        rows += race_rows(f"r{k}", f"2025-0{k + 1}-01", [1, 2, 3, 4, 5, 6, 7, 8], team=team)
    rows += race_rows("r6", "2025-08-01", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], team=team)   # 9 and 10 start once
    data = m.load(data=pd.DataFrame(rows))
    field = [9, 10]
    assert beats(price(m, data, field, group_weight=1.0), 9, 10) > beats(price(m, data, field), 9, 10) + 0.2


def test_rating_prior_leads_when_results_say_little(toy):
    m = RM.get("toy_global")
    rating = {a: 700.0 - 100 * a for a in range(1, 7)}               # rider 1 is the best rated ...
    data = m.load(data=pd.DataFrame(race_rows("r0", "2025-05-01", [6, 5, 4, 3, 2, 1], rating=rating)))   # ... and last
    field = list(range(1, 7))
    assert beats(price(m, data, field, prior_weight=50, rating_weight=1.0), 1, 6) > 0.9
    assert beats(price(m, data, field, prior_weight=50), 6, 1) > 0.5


def test_without_a_start_list_the_recently_active_are_priced(toy):
    m = RM.get("toy_global")
    rows = race_rows("old", "2020-01-01", [90, 91, 92, 93, 94]) + race_rows("new", "2025-12-01", [1, 2, 3, 4, 5])
    data = m.load(data=pd.DataFrame(rows))
    st = m.Settings.from_dict({"sims": 100, "seed": 1})
    ev = Event(id="x", season=2026, cutoff=pd.Timestamp("2026-01-01"))
    assert sorted(m.price(m.history(data, st), ev, st, np.random.default_rng(1)).entrants) == [1, 2, 3, 4, 5]
    assert m.price(m.history(data, st), Event(id="x", season=2020, cutoff=pd.Timestamp("2019-01-01")), st,
                   np.random.default_rng(1)) is None


def test_results_classify_unclassified_entrants_behind_the_finishers(toy):
    m = RM.get("toy_global")
    d = pd.DataFrame(race_rows("r", "2025-05-01", [1, 2, 3, 4, 5, 6]))
    d.loc[d["athlete_id"].isin([5, 6]), ["position", "status"]] = [np.nan, "DNF"]
    res = m.results(m.load(data=d), Event(id="r", season=2025, cutoff=pd.Timestamp("2025-05-01")))
    assert res["position"].notna().all() and res.set_index("athlete_id").loc[[5, 6], "position"].min() > 4


def test_the_schema_binds_the_model_and_sets_its_defaults(toy):
    from racinglines.pipelines import position_replay as PR
    m = RM.get("toy_global")
    assert m.sport == "toy_global" and m.cfg == dict(competition="toy_global_cup", source="toy_src", group="team",
                                                     prior="rating")
    assert m.Settings.from_dict({})["noise"] == 0.6 and G.GlobalModel.Settings.from_dict({})["noise"] == 0.8
    assert PR.model_for({"model": "racinglines.models.model_global:GlobalModel", "sport": "toy_global"}).sport == "toy_global"
    with pytest.raises(ValueError, match="unknown settings"):
        G._settings_class({"nope": 1})
    with pytest.raises(ValueError, match="needs"):                    # mtb_dh has no [model] and no [replay] source
        G.GlobalModel.for_sport("mtb_dh")
    with pytest.raises(ValueError, match="needs data"):
        G.GlobalModel().load()
