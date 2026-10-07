"""Classifier gaps (C10): Kalshi kinds from the series ticker (an exact key in sports/f1.toml), the sprint series and
Polymarket families that used to land unmodeled, and the schema-driven filing of the sports without a title
classifier (identity.promote). Synthetic listings shaped like the stored rows of 2026-10-07; no network, no database."""

import pytest

from racinglines import sports
from racinglines.markets import identity
from racinglines.markets import kinds as K
from racinglines.markets.kalshi import sync as KS
from racinglines.markets.polymarket import sync as PS

pytestmark = pytest.mark.quick


class Resolver:
    DRIVERS = {"max verstappen": 1, "lando norris": 4, "liam lawson": 30, "lawson": 30, "yuki tsunoda": 22,
               "tsunoda": 22, "lance stroll": 18, "stroll": 18}

    def driver(self, name):
        return self.DRIVERS.get((name or "").strip().lower())

    def team(self, name):
        return PS.Resolver.team(self, name)

    def race(self, gp, end=None, near=None):
        return (7, "2026-05") if gp in ("Miami Grand Prix", "Japanese Grand Prix", "British Grand Prix") else (None, None)


def _ev(series, ticker, title, markets):
    return dict(event_ticker=ticker, series_ticker=series, title=title,
                markets=[dict(ticker=f"{ticker}-{i}", event_ticker=ticker, status="finalized", result="no",
                              close_time="2026-05-03T22:34:03Z", **mk) for i, mk in enumerate(markets)])


# --- Kalshi -----------------------------------------------------------------------------------------------------------

def test_every_schema_kind_is_a_registry_kind():
    for code in sports.SPORT_CODES:
        assert set(sports.kalshi_kinds(code).values()) <= set(K.KINDS), code
        assert set(sports.link_kinds(code)) <= set(K.KINDS), code
    assert sports.titles_classified("f1") and not any(sports.titles_classified(c) for c in ("nascar", "motogp", "indycar"))
    assert sports.kalshi_kinds("f1")["KXF1TOP5"] == "race_top5" and "KXF1SPRINTFASTLAP" not in sports.kalshi_kinds("f1")


def test_a_settled_top5_market_with_no_market_title_is_filed_by_its_series():
    # how the 330 KXF1TOP5 links were stored: the historical listing has no market title, the question is the event's
    ev = _ev("KXF1TOP5", "KXF1TOP5-MIAGP26", "Miami Grand Prix: Top 5 Finishers", [dict(yes_sub_title="Max Verstappen")])
    (r,) = KS.link_rows([ev], Resolver())
    assert (r["prediction"], r["athlete_id"], r["race_id"], r["params"]["series"]) == ("race_top5", 1, 7, "KXF1TOP5")
    mover = _ev("KXF1BIGGESTMOVER", "KXF1BIGGESTMOVER-MIAGP26", "Miami Grand Prix: Biggest Mover",
                [dict(yes_sub_title="Lando Norris")])
    assert KS.link_rows([mover], Resolver())[0]["prediction"] == "race_biggest_mover"


def test_the_sprint_series_take_the_sprint_kinds(monkeypatch):
    monkeypatch.setenv(KS.SPRINT_FLAG, "1")
    evs = [
        _ev("KXF1SPRINTTOP5", "KXF1SPRINTTOP5-MIAGP26", "Miami Grand Prix Sprint Race: Top 5 Finishers?",
            [dict(yes_sub_title="Max Verstappen")]),
        _ev("KXF1SPRINTTOP10", "KXF1SPRINTTOP10-MIAGP26", "Miami Grand Prix Sprint Race: Top 10 Finishers",
            [dict(yes_sub_title="Max Verstappen")]),
        # the event title of the stored constructor markets reads like a sprint win: the series says otherwise
        _ev("KXF1SPRINTTOPCONSTRUCTOR", "KXF1SPRINTTOPCONSTRUCTOR-MIAGP26",
            "Will McLaren finish in first in the Sprint Race at the 2026 Miami Grand Prix?", [dict(yes_sub_title="McLaren")]),
        _ev("KXF1RACESPRINT", "KXF1RACESPRINT-MIAGP26", "Miami Grand Prix: Sprint Race Winner",
            [dict(yes_sub_title="Max Verstappen")]),
        _ev("KXF1SPRINTFASTLAP", "KXF1SPRINTFASTLAP-MIAGP26", "Miami Grand Prix Sprint Race: Fastest Lap",
            [dict(yes_sub_title="Max Verstappen")]),
    ]
    got = {r["params"]["series"]: r for r in KS.link_rows(evs, Resolver())}
    assert {s: r["prediction"] for s, r in got.items()} == {
        "KXF1SPRINTTOP5": "race_sprint_top5", "KXF1SPRINTTOP10": "race_sprint_top10",
        "KXF1SPRINTTOPCONSTRUCTOR": "race_sprint_constructor_top", "KXF1RACESPRINT": "race_sprint_win",
        "KXF1SPRINTFASTLAP": "unmodeled"}
    assert got["KXF1SPRINTTOPCONSTRUCTOR"]["params"]["team"] == "mclaren"
    assert got["KXF1SPRINTTOP5"]["athlete_id"] == 1 and got["KXF1SPRINTTOP5"]["race_id"] == 7
    monkeypatch.setenv(KS.SPRINT_FLAG, "0")
    assert {r["prediction"] for r in KS.link_rows(evs, Resolver())} == {"unmodeled"}        # the flag still gates them


def test_the_series_wins_over_the_titles_and_needs_a_grand_prix():
    c = KS.classify
    assert c("Will McLaren finish in first in the Sprint Race at the 2026 Dutch Grand Prix?", sprints=True)[0] == \
        "race_sprint_win"                                                    # titles alone: a sprint winner ...
    assert c("Will McLaren finish in first in the Sprint Race at the 2026 Dutch Grand Prix?", sprints=True,
             series="KXF1SPRINTTOPCONSTRUCTOR") == ("race_sprint_constructor_top", "Dutch Grand Prix")   # ... the series
    assert c("F1 Drivers Champion", series="KXF1") == ("champion", None)
    assert c("Top 5 Finishers", series="KXF1TOP5") == ("unmodeled", None)               # no Grand Prix: no race
    assert c("Top 5 Finishers", gp="British Grand Prix", series="KXF1TOP5") == ("race_top5", "British Grand Prix")
    assert c("Azerbaijan Grand Prix Winner", "Oscar Piastri to finish in first", series="KXF1NEWSERIES") == \
        ("race_win", "Azerbaijan Grand Prix")                                # an unmapped series: the titles


# --- schema-driven filing of the sports without a title classifier -------------------------------------------------------

@pytest.mark.parametrize("sport,row,want", [
    ("nascar", dict(athlete_id=5, race_id=9, params=dict(kind="race_win")), "race_win"),
    ("nascar", dict(athlete_id=5, race_id=9, params=dict(kind="race_top20")), "race_top20"),
    ("nascar", dict(athlete_id=5, race_id=None, params=dict(kind="race_win")), "unmodeled"),     # no Cup race matched
    ("nascar", dict(athlete_id=5, race_id=9, params=dict(kind="race_h2h")), "unmodeled"),       # no opponent
    ("nascar", dict(athlete_id=5, race_id=9, params=dict(kind="race_h2h", opponent_id=6)), "race_h2h"),
    ("nascar", dict(athlete_id=5, race_id=9, params=dict(kind="race_pole")), "unmodeled"),      # not in [markets] kinds
    ("nascar", dict(athlete_id=5, race_id=None, params=dict(kind="champion")), "unmodeled"),
    ("nascar", dict(athlete_id=None, race_id=9, params=dict(kind="race_team_win")), "unmodeled"),   # not a kind
    ("motogp", dict(athlete_id=5, race_id=9, params=dict(kind="race_win")), "race_win"),
    ("motogp", dict(athlete_id=5, race_id=9, params=dict(kind="race_podium")), "unmodeled"),
    ("indycar", dict(athlete_id=5, race_id=9, params=dict(kind="race_win")), "unmodeled"),      # no [markets] kinds
])
def test_promote_files_the_schemas_kinds_once_identified(sport, row, want):
    row = dict(row, prediction="unmodeled")
    identity.promote(sport, [row])
    assert row["prediction"] == want


# --- Polymarket ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("title,question,want", [
    ("F1 Singapore Grand Prix: 2nd Place", "Will Lance Stroll finish second at the 2025 F1 Singapore Grand Prix?",
     ("race_p2", "Singapore Grand Prix")),
    ("F1 British Grand Prix: 5th Place ", "", ("race_p5", "British Grand Prix")),
    ("F1 Azerbaijan Grand Prix: Which Constructor scores 2nd?", "", ("race_constructor_p2", "Azerbaijan Grand Prix")),
    ("F1 Bahrain Grand Prix: Which constructor scores the second most points?", "",
     ("race_constructor_p2", "Bahrain Grand Prix")),
    ("Bahrain Grand Prix: Which Constructor Scores 1st?", "", ("race_constructor_top", "Bahrain Grand Prix")),
    ("Bahrain Grand Prix: Constructor Pole Position", "", ("race_constructor_pole", "Bahrain Grand Prix")),
    ("F1 Dutch Grand Prix – Constructor Matchups ", "F1 Dutch Grand Prix: McLaren vs. Red Bull",
     ("race_constructor_h2h", "Dutch Grand Prix")),
    ("F1: Constructor to double podium at Chinese Grand Prix?", "Will McLaren double podium at the 2026 Chinese Grand Prix?",
     ("race_team_double_podium", "Chinese Grand Prix")),
    ("F1: Will Lawson finish ahead of Tsunoda in the Japanese Grand Prix?",
     "F1: Will Lawson finish ahead of Tsunoda in the Japanese Grand Prix?", ("race_h2h", "Japanese Grand Prix")),
    ("F1: Will Carlos Sainz finish ahead of Fernando Alonso in the 2026 Drivers' Championship?",
     "F1: Will Carlos Sainz finish ahead of Fernando Alonso in the 2026 Drivers' Championship?", ("standings_h2h", None)),
    ("F1 Drivers Champion: 2nd Place", "Will Andrea Kimi Antonelli finish second in the 2025 Drivers Championship?",
     ("standings_p2", None)),
    ("F1 Constructors Champion: 4th Place", "", ("constructors_p4", None)),
    ("F1 Belgian Grand Prix: Sprint Race Winner ", "", ("race_sprint_win", "Belgian Grand Prix")),
    ("China Grand Prix - Sprint Winner", "Will Oscar Piastri win the 2025 Chinese Grand Prix Sprint?",
     ("race_sprint_win", "China Grand Prix")),
    ("British Grand Prix: Sprint Qualifying Pole Winner", "", ("race_sprint_pole", "British Grand Prix")),
    ("Bahrain Grand Prix: Practice 1 Fastest Lap", "", ("unmodeled", "Bahrain Grand Prix")),       # needs a model
    ("F1 Drivers' Champion", "", ("champion", None)),
    ("Honda Indy 200 at Mid-Ohio: Race Winner", "", ("unmodeled", None)),
])
def test_polymarket_families(title, question, want):
    assert PS.classify(title, question) == want


def test_polymarket_tokens_follow_the_kinds_subject():
    R = Resolver()
    t = PS.targets_of
    assert t("race_p2", "", "Stroll", ["Yes", "No"], R) == [(0, 18, None, "Yes")]
    assert t("race_constructor_pole", "", "McLaren", ["Yes", "No"], R) == [(0, None, {"team": "mclaren"}, "Yes")]
    assert t("constructors_p3", "", "Ferrari", ["Yes", "No"], R) == [(0, None, {"team": "ferrari"}, "Yes")]
    assert t("race_constructor_h2h", "F1 Dutch Grand Prix: McLaren vs. Red Bull", "McLaren vs. Red Bull",
             ["McLaren ", "Red Bull"], R) == [(0, None, {"team": "mclaren", "opponent": "red_bull"}, "McLaren "),
                                              (1, None, {"team": "red_bull", "opponent": "mclaren"}, "Red Bull")]
    assert t("race_h2h", "F1: Will Lawson finish ahead of Tsunoda in the Japanese Grand Prix?", "Yes", ["Yes", "No"], R) \
        == [(0, 30, {"opponent_id": 22}, "Yes")]                              # the yes token: Lawson ahead of Tsunoda
    assert t("race_h2h", "Who will finish higher: Verstappen or Norris?", "", ["Max Verstappen", "Lando Norris"], R) == \
        [(0, 1, {"opponent_id": 4}, "Max Verstappen"), (1, 4, {"opponent_id": 1}, "Lando Norris")]
    assert t("unmodeled", "", "Stroll", ["Yes", "No"], R) == [(0, None, None, "Yes")]
