"""Which NASCAR driver, race and contract a market is about (racinglines/sources/nascar/links.py), on the real listings
captured 2026-09-29 (tests/fixtures/market/kalshi_nascar_events.json, kalshi_nascar_h2h.json, polymarket_nascar_events.json,
og_instruments_nascar.json) and a throwaway database holding the NASCAR fixtures' drivers and races. No network. Rows marked
"synthetic" are built by hand from a real listing's fields, because the fixtures hold no sample of that shape (a name two races
share; a Polymarket race Kalshi also lists)."""

import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete, select

from test_nascar import MKT, TODAY, athlete_of, db, raw          # noqa: F401  (db, raw are fixtures)

from racinglines.db import models as m
from racinglines.markets.kalshi import sync as KS
from racinglines.markets.polymarket import sync as PS
from racinglines.sources.nascar import ingest as I
from racinglines.sources.nascar import links as L

KALSHI = json.loads((MKT / "kalshi_nascar_events.json").read_text())
H2H = json.loads((MKT / "kalshi_nascar_h2h.json").read_text())
OG_INSTRUMENTS = json.loads((MKT / "og_instruments_nascar.json").read_text())["result"]["data"]
OG_TICKERS = json.loads((MKT / "og_tickers_nascar.json").read_text())["result"]["data"]
POLY = json.loads((MKT / "polymarket_nascar_events.json").read_text())
UTC = timezone.utc
quiet = lambda *_: None                                                          # noqa: E731


def kalshi_events(*tickers):
    """The fixture's events with their markets nested, as sync sees them (settled ones from /historical)."""
    by = {e["event_ticker"]: e for v in KALSHI["events"].values() for k in ("open", "settled") for e in v.get(k, [])}
    out = []
    for t in tickers:
        e = dict(by[t])
        e["markets"] = e.get("markets") or KALSHI["historical"][t]
        out.append(e)
    return out


def kalshi_rows(*tickers):
    return KS.link_rows(kalshi_events(*tickers), None, modeled=False)            # the rows the tape-only sync stores


def og_rows():
    """The 17 Cup Champion contracts OG.com lists, as the generic exchange driver stores them."""
    from racinglines import exchanges as EX
    from racinglines.markets import exchange_driver as D
    return D.link_rows(EX.load("og"), "nascar", OG_INSTRUMENTS, {t["i"]: t for t in OG_TICKERS})


def h2h_rows(event):
    """A settled head-to-head event's markets (from /historical), as the tape-only Kalshi sync stores them."""
    ev = next(e for e in H2H["settled_sample"] if e["event_ticker"] == event)
    return KS.link_rows([dict(ev, markets=ev.get("markets") or H2H["historical"][event])], None, modeled=False)


def poly_event(slug):
    return next(e for e in POLY["events"] if e["slug"] == slug)


def poly_rows(slug):
    """What the Polymarket tape-only sync stores for an event's first outcome tokens."""
    ev = poly_event(slug)
    return [dict(exchange="polymarket", question=mk["question"], event_title=ev["title"], event_slug=slug, condition_id=mk["conditionId"],
                 group_title=mk.get("groupItemTitle"), outcome="Yes", params=None, athlete_id=None, race_id=None,
                 end_date=datetime.fromisoformat(mk["endDate"].replace("Z", "+00:00"))) for mk in ev["markets"]]


def synthetic(exchange, question, event_title, driver, slug, end=None, params=None):
    return dict(exchange=exchange, question=question, event_title=event_title, event_slug=slug, condition_id=slug, group_title=driver,
                outcome=driver, params=params, athlete_id=None, race_id=None, end_date=end)


def named(s, name):
    """The athlete id of a driver the fixtures' weekends hold, by the name the feed spells."""
    return s.scalars(select(m.Athlete.id).where(m.Athlete.display_name == name)).one()


def race_id_of(s, key):
    return s.scalars(select(m.Race.id).join(m.Event).where(m.Event.source_key == key)).one()


@pytest.fixture
def world(db):
    """The fixtures' 2026 races (three run, six still to run) and the 26 drivers of the three weekends that were run."""
    with db() as s:
        I.ingest(s, [2026], today=TODAY, echo=quiet)
        s.commit()

    def wipe():
        with db() as s:
            s.execute(delete(m.MarketLink).where(m.MarketLink.token_id.like("KXNASCAR%") | m.MarketLink.event_slug.like("nascar-%")
                                                           | m.MarketLink.event_slug.like("NSCAR-%")))
            s.execute(delete(m.DataChange).where(m.DataChange.sport == "nascar", m.DataChange.kind.in_(("link", "link-undo"))))
            s.commit()
    wipe()
    yield db
    wipe()


def linker(s):
    return L.Linker(s.connection())


def by_token(rows):
    return {r["token_id"]: r for r in rows}


# --- pieces ---------------------------------------------------------------------------------------------------

@pytest.mark.quick
def test_the_season_in_a_kalshi_ticker_and_the_date_in_the_rules():
    year = L._ticker_year
    assert [year(f"KXNASCARRACE-{c}") for c in ("SOUP26", "FOCH100326", "WR4PBL26", "WIN2PB26", "YEL25")] == [2026, 2026, 2026, 2026, 2025]
    assert year("KXNASCARH2H-WINW26TOGICHEL") == 2026 and year("KXNASCARCHALLENGE-26") == 2026 and year(None) is None
    rules = "If X finishes in first in the main race at the 2026 South Point 400 originally scheduled for Oct 4, 2026, then"
    assert L._day(rules, {}) == date(2026, 10, 4)
    assert L._day("This is a Polymarket on the 2026 race, scheduled for Oct 3, 2026.  If", {}) == date(2026, 10, 3)
    assert L._day("Will X win?", {"event_slug": "nascar-xfinity-focused-health-302-winner-2026-10-03"}) == date(2026, 10, 3)
    assert L._day("Will X win?", {"event_slug": "nascar-coca-cola-600-winner"}) is None


@pytest.mark.quick
def test_a_race_name_is_matched_whole_and_without_its_sponsor_tail():
    assert L._phrases("Pennzoil 400 presented by Jiffy Lube") == ["pennzoil 400 presented by jiffy lube", "pennzoil 400"]
    assert L._phrases("Quaker State 400 Available at Walmart")[1] == "quaker state 400"
    assert L._phrases("Toyota / Save Mart 350") == ["toyota save mart 350"]
    assert L._phrases("DAYTONA 500") == ["daytona 500"]                           # nothing to strip; never a one-word phrase


# --- Kalshi: what the real listing says ----------------------------------------------------------------------

def test_kalshi_cup_race_markets_get_driver_race_contract_and_season(world):
    with world() as s:
        rows = kalshi_rows("KXNASCARRACE-SOUP26", "KXNASCARTOP10-SOUP26", "KXNASCARTOP3-SOUP26", "KXNASCARTOPTEAM-SOUP26")
        lk = linker(s)
        lk.fill(rows)
        vegas = race_id_of(s, "2026-5630")
        win = by_token(rows)["KXNASCARRACE-SOUP26-BRKE"]
        assert (win["race_id"], win["athlete_id"]) == (vegas, named(s, "Brad Keselowski"))
        assert win["params"]["kind"] == "race_win" and win["params"]["nascar_series"] == "cup" and win["params"]["season"] == 2026
        assert win["params"]["series"] == "KXNASCARRACE" and "originally scheduled for Oct 4, 2026" in win["params"]["rules"]   # kept
        assert win["prediction"] == "unmodeled"                                     # identity only: nothing is priced or promoted
        kinds = {r["token_id"].split("-")[0]: r["params"]["kind"] for r in rows}
        assert kinds == {"KXNASCARRACE": "race_win", "KXNASCARTOP10": "race_top10", "KXNASCARTOP3": "race_podium",
                         "KXNASCARTOPTEAM": "race_team_win"}
        assert {r["race_id"] for r in rows} == {vegas}                              # every market of the weekend: one race
        team = by_token(rows)["KXNASCARTOPTEAM-SOUP26-RFKR"]
        assert team["athlete_id"] is None and team["race_id"] == vegas              # a team is not a driver
        assert lk.counts["errors"] == 0


def test_o_reilly_and_truck_markets_are_tagged_and_the_race_the_day_before_is_not_mistaken_for_the_cup_race(world):
    with world() as s:
        rows = kalshi_rows("KXNASCARRACE-FOCH100326", "KXNASCARTOP10-WIN2PB26", "KXNASCARTRUCKSERIES-NTS26", "KXNASCARAUTOPARTSSERIES-NAPS26")
        lk = linker(s)
        lk.fill(rows)
        series = {r["token_id"].rsplit("-", 1)[0]: r["params"]["nascar_series"] for r in rows}
        assert series == {"KXNASCARRACE-FOCH100326": "xfinity", "KXNASCARTOP10-WIN2PB26": "xfinity",
                          "KXNASCARTRUCKSERIES-NTS26": "trucks", "KXNASCARAUTOPARTSSERIES-NAPS26": "xfinity"}
        assert all(r["race_id"] is None and r["athlete_id"] is None for r in rows)
        # the Focused Health 302 was Saturday Oct 3, the Cup South Point 400 is Sunday Oct 4: a date alone would join them
        assert {r["params"]["kind"] for r in rows} == {"race_win", "race_top10", "champion"}
        assert all(r["params"]["season"] == 2026 and r["prediction"] == "unmodeled" for r in rows)
        assert not lk.unresolved                                                    # tagged, so no noise in the report


def test_season_markets_have_a_driver_and_no_race(world):
    with world() as s:
        rows = kalshi_rows("KXNASCARCUPSERIES-NCS26", "KXNASCARCUPSEASON-26", "KXNASCARCHALLENGE-26")
        lk = linker(s)
        lk.fill(rows)
        champ = by_token(rows)["KXNASCARCUPSERIES-NCS26-KLAR"]
        assert (champ["params"]["kind"], champ["params"]["nascar_series"], champ["params"]["season"]) == ("champion", "cup", 2026)
        assert champ["race_id"] is None and champ["athlete_id"] == athlete_of(s, 4030)
        bell = next(r for r in rows if r["outcome"] == "Christopher Bell" and r["params"]["series"] == "KXNASCARCUPSERIES")
        assert bell["athlete_id"] == athlete_of(s, 4153)
        assert {r["params"]["kind"] for r in rows} == {"champion", "regular_season_champion", "in_season_challenge"}
        assert by_token(rows)["KXNASCARCUPSEASON-26-DEHA"]["athlete_id"] == named(s, "Denny Hamlin")
        assert by_token(rows)["KXNASCARCHALLENGE-26-RBLA"]["athlete_id"] == named(s, "Ryan Blaney")
        assert by_token(rows)["KXNASCARCHALLENGE-26-TGIL"]["athlete_id"] is None and "Todd Gilliland" in lk.unresolved["driver: unknown"]


def test_settled_markets_without_a_year_or_date_use_the_ticker_and_the_name(world):
    """2025's YellaWood 500 and Xfinity 500 (a CUP race sponsored by Xfinity): rules say only 'If Zane Smith wins the YellaWood 500'."""
    with world() as s:
        rows = kalshi_rows("KXNASCARRACE-YEL25", "KXNASCARRACE-XFI25")
        lk = linker(s)
        lk.resolver(2025).events = [(11, "YellaWood 500", date(2025, 10, 19), "c"), (12, "Xfinity 500", date(2025, 10, 26), "c"),
                                    (13, "Bank of America Roval 400", date(2025, 10, 12), "c")]
        lk.fill(rows)
        assert {r["race_id"] for r in rows if "YEL25" in r["token_id"]} == {11}
        assert {r["race_id"] for r in rows if "XFI25" in r["token_id"]} == {12}
        assert {r["params"]["nascar_series"] for r in rows} == {"cup"} and {r["params"]["season"] for r in rows} == {2025}


def test_a_head_to_head_has_both_drivers_and_the_race(world):
    """Kalshi lists a matchup as two markets, one per driver ("Will A beat B at the Window World 450 ..."), yes = A finishes ahead."""
    with world() as s:
        lk = linker(s)
        lk.resolver(2026).events += [(31, "Window World 450", date(2026, 7, 19), "c")]
        rows = h2h_rows("KXNASCARH2H-WINW26CHBERYBL")                               # Blaney vs Bell: both in the pool
        lk.fill(rows)
        blaney, bell = named(s, "Ryan Blaney"), named(s, "Christopher Bell")
        by = by_token(rows)
        assert (by["KXNASCARH2H-WINW26CHBERYBL-RYBL"]["athlete_id"], by["KXNASCARH2H-WINW26CHBERYBL-RYBL"]["params"]["opponent_id"]) == (blaney, bell)
        assert (by["KXNASCARH2H-WINW26CHBERYBL-CHBE"]["athlete_id"], by["KXNASCARH2H-WINW26CHBERYBL-CHBE"]["params"]["opponent_id"]) == (bell, blaney)
        assert {r["race_id"] for r in rows} == {31} and {r["params"]["kind"] for r in rows} == {"race_h2h"}
        keys = {L.outcome_key(r) for r in rows}
        assert len(keys) == 2 and ("race_h2h", blaney, "race", 31, bell) in keys       # the two sides are different outcomes
        gil = h2h_rows("KXNASCARH2H-WINW26TOGICHEL")                                # Gilliland is not in the test pool
        lk.fill(gil)
        assert all(r["athlete_id"] is None and "opponent_id" not in r["params"] and r["race_id"] == 31 for r in gil)   # half a matchup is no key
        assert "Todd Gilliland" in lk.unresolved["driver: unknown"]


def test_unknown_shapes_are_left_alone(world):
    with world() as s:
        row = synthetic("kalshi", "NASCAR Cup Series playoffs Winner?", "NASCAR Cup Series playoffs Winner?", "Kyle Larson", "KXNASCAR-PLAYOFFS25",
                        params={"series": "KXNASCAR"})
        linker(s).fill([row])
        assert "kind" not in row["params"] and row["athlete_id"] is None and row["race_id"] is None


# --- Polymarket and OG.com: the same outcome, other words ---------------------------------------------------

def test_polymarket_markets_are_found_by_race_name_and_tagged_by_series(world):
    with world() as s:
        lk = linker(s)
        champ = poly_rows("nascar-cup-series-2026-champion-20260722193936777")
        xfin = poly_rows("nascar-xfinity-focused-health-302-winner-2026-10-03")
        lk.resolver(2025).events = [(41, "Coca-Cola 600", date(2025, 5, 25), "c"), (42, "Cracker Barrel 400", date(2025, 6, 1), "c")]
        coke, barrel = poly_rows("nascar-coca-cola-600-winner"), poly_rows("nascar-cracker-barrel-400")
        lk.fill(champ + xfin + coke + barrel)
        assert {r["params"]["kind"] for r in champ} == {"champion"} and {r["params"]["nascar_series"] for r in champ} == {"cup"}
        assert all(r["race_id"] is None and r["params"]["season"] == 2026 for r in champ)
        assert {r["params"]["nascar_series"] for r in xfin} == {"xfinity"} and all(r["race_id"] is None for r in xfin)
        assert {r["race_id"] for r in coke} == {41} and {r["race_id"] for r in barrel} == {42}       # the question names the race and year
        assert {r["params"]["kind"] for r in coke + barrel} == {"race_win"} and {r["params"]["season"] for r in coke} == {2025}
        larson = next(r for r in coke if r["group_title"] == "Kyle Larson")
        assert larson["athlete_id"] == athlete_of(s, 4030)                              # found in the 2025 pool: last year's field, this year's drivers


def test_a_name_two_races_share_is_settled_by_the_date_or_left_alone(world):
    """Cook Out 400 is Martinsville (Mar 29) and Richmond (Aug 15) in 2026. Synthetic rows built from real listings' wording."""
    with world() as s:
        lk = linker(s)
        lk.resolver(2026).events += [(21, "Cook Out 400", date(2026, 3, 29), "c"), (22, "Cook Out 400", date(2026, 8, 15), "c")]
        q = "Will Kyle Larson win the 2026 Cook Out 400?"
        by_close = synthetic("polymarket", q, "NASCAR: Cook Out 400 Winner", "Kyle Larson", "nascar-cook-out-400-winner", end=datetime(2026, 8, 15, 12, tzinfo=UTC))
        by_rules = synthetic("kalshi", "Cup Series: Kyle Larson wins", "Cook Out 400 Winner", "Kyle Larson", "KXNASCARRACE-COOK26",
                             params={"series": "KXNASCARRACE", "rules": "If Kyle Larson finishes in first in the main race at the 2026 Cook Out 400 originally scheduled for Mar 29, 2026, then"})
        neither = synthetic("polymarket", q, "NASCAR: Cook Out 400 Winner", "Kyle Larson", "nascar-cook-out-400-winner-2")
        far = synthetic("polymarket", q, "NASCAR: Cook Out 400 Winner", "Kyle Larson", "nascar-cook-out-400-winner-3", end=datetime(2026, 6, 1, tzinfo=UTC))
        lk.fill([by_close, by_rules, neither, far])
        assert (by_close["race_id"], by_rules["race_id"], neither["race_id"], far["race_id"]) == (22, 21, None, None)
        assert any("2 races share the name" in k for k in lk.unresolved)              # said, not guessed
        assert neither["params"]["kind"] == "race_win" and neither["athlete_id"] == athlete_of(s, 4030)      # the contract and the driver still known


def test_a_postponed_race_keeps_its_identity_until_the_dates_are_implausibly_far_apart(world):
    with world() as s:
        lk = linker(s)
        row = lambda d: synthetic("kalshi", "Cup Series: Kyle Larson wins", "South Point 400 Winner", "Kyle Larson", "KXNASCARRACE-SOUP26",   # noqa: E731
                                  params={"series": "KXNASCARRACE", "rules": f"in the main race at the 2026 South Point 400 originally scheduled for {d}, then"})
        moved, wrong = row("Oct 3, 2026"), row("Sep 1, 2026")
        lk.fill([moved, wrong])
        assert moved["race_id"] == race_id_of(s, "2026-5630")
        assert wrong["race_id"] is None and any("days from the listing's date" in k for k in lk.unresolved)


def test_one_outcome_on_three_venues_has_one_key(world):
    """The 2026 Cup champion, Kyle Larson: Kalshi, Polymarket and OG.com, all from real listings. And one race winner on two venues:
    Kalshi (real) and a Polymarket-style row (synthetic: the fixtures hold no open Polymarket race for a race Kalshi lists)."""
    with world() as s:
        lk = linker(s)
        kal = by_token(kalshi_rows("KXNASCARCUPSERIES-NCS26"))["KXNASCARCUPSERIES-NCS26-KLAR"]
        poly = next(r for r in poly_rows("nascar-cup-series-2026-champion-20260722193936777") if r["group_title"] == "Kyle Larson")
        ogs = og_rows()
        og = next(r for r in ogs if r["group_title"] == "Kyle Larson")
        lk.fill([kal, poly] + ogs)
        larson = named(s, "Kyle Larson")
        assert L.outcome_key(kal) == L.outcome_key(poly) == L.outcome_key(og) == ("champion", larson, "season", 2026, None)
        assert {r["params"]["nascar_series"] for r in ogs} == {"cup"} and {r["params"]["kind"] for r in ogs} == {"champion"}
        assert all(r["prediction"] == "unmodeled" and r["race_id"] is None for r in ogs)
        assert sum(r["athlete_id"] is not None for r in ogs) == 15                 # the two others are not in the test pool
        assert set(lk.unresolved["driver: unknown"]) == {"Daniel Suarez", "AJ Allmendinger"}
        k_win = by_token(kalshi_rows("KXNASCARRACE-SOUP26"))["KXNASCARRACE-SOUP26-BRKE"]
        p_win = synthetic("polymarket", "Will Brad Keselowski win the 2026 South Point 400?", "NASCAR: South Point 400 Winner", "Brad Keselowski",
                          "nascar-south-point-400-winner", end=datetime(2026, 10, 5, tzinfo=UTC))
        lk.fill([k_win, p_win])
        assert L.outcome_key(k_win) == L.outcome_key(p_win) is not None
        assert L.outcome_key(dict(k_win, athlete_id=None)) is None


def test_wording_that_only_looks_like_a_win_or_a_title_gets_no_kind(world):
    with world() as s:
        lk = linker(s)
        rows = [synthetic("polymarket", q, t, "Kyle Larson", f"nascar-x-{i}", end=datetime(2026, 10, 4, tzinfo=UTC))
                for i, (q, t) in enumerate((("Will Kyle Larson win the pole for the 2026 South Point 400?", "NASCAR: South Point 400 Pole"),
                                            ("Will Kyle Larson win the 2026 NASCAR Cup Series regular season?", "NASCAR Cup Series Regular Season"),
                                            ("Will Kyle Larson win Stage 1 of the 2026 South Point 400?", "NASCAR: South Point 400 Stage 1")))]
        lk.fill(rows)
        assert all("kind" not in r["params"] and r["athlete_id"] is None and r["race_id"] is None for r in rows)


def test_a_bad_row_does_not_stop_the_sync_and_an_empty_database_still_gets_kinds(world, monkeypatch):
    with world() as s:
        lk = linker(s)
        good, bad = kalshi_rows("KXNASCARRACE-SOUP26")[0], {"exchange": "kalshi", "params": "not a dict"}
        lk.fill([bad, good])
        assert lk.counts["errors"] == 1 and "kind" in good["params"]
        monkeypatch.setattr(L.Linker, "has_data", lambda self: False)
        assert not lk.has_data()


# --- the syncs fill it, and a second sync keeps it -------------------------------------------------------------

class FakeKalshi:
    """The open events the fixture holds, by series, as `Client.events` returns them."""

    def events(self, series_ticker=None, status=None):
        opened = [e for v in KALSHI["events"].values() for e in v.get("open", []) if e.get("markets")]
        return [e for e in opened if e["series_ticker"] == series_ticker] if status == "open" else []


def test_the_kalshi_sync_stores_identity_and_a_second_sync_keeps_it(world):
    series = ["KXNASCARRACE", "KXNASCARCUPSERIES"]
    with world() as s:
        st = KS.sync(s, s.connection(), 2026, kc=FakeKalshi(), sport="nascar", series=series)
        assert st["links"] == 24 and st["modeled"] == 0 and st["identity"]["links"] == 24
        for _ in range(2):                                                         # the second sync must not undo the first
            link = s.scalars(select(m.MarketLink).filter_by(exchange="kalshi", token_id="KXNASCARRACE-SOUP26-BRKE")).one()
            assert (link.race_id, link.athlete_id) == (race_id_of(s, "2026-5630"), named(s, "Brad Keselowski"))
            assert link.prediction == "unmodeled" and link.params["kind"] == "race_win" and link.params["series"] == "KXNASCARRACE"
            KS.sync(s, s.connection(), 2026, kc=FakeKalshi(), sport="nascar", series=series)
            s.expire_all()


def test_the_polymarket_sync_stores_identity_and_a_second_sync_keeps_it(world, monkeypatch):
    events = {e["slug"]: e for e in POLY["events"] if e["slug"].endswith(("champion-20260722193936777", "focused-health-302-winner-2026-10-03"))}
    monkeypatch.setattr(PS, "_events", lambda *a, **k: events)
    with world() as s:
        for _ in range(2):
            st = PS.sync(s, s.connection(), 2026, sport="nascar")
            s.expire_all()
        assert st["links"] == 16 and st["identity"]["links"] == 16
        larson = s.scalars(select(m.MarketLink).where(m.MarketLink.exchange == "polymarket", m.MarketLink.group_title == "Kyle Larson")).one()
        assert larson.athlete_id == athlete_of(s, 4030) and larson.params["kind"] == "champion" and larson.prediction == "unmodeled"
        matt = s.scalars(select(m.MarketLink).where(m.MarketLink.group_title == "Matt Dibenedetto")).one()
        assert matt.params["nascar_series"] == "xfinity" and matt.athlete_id is None


class FakeOG:
    """OG.com's public API as the driver pages it: the one NASCAR event, its 17 instruments and tickers."""

    def __init__(self):
        from racinglines import exchanges as EX
        self.schema = EX.load("og")

    def paged(self, endpoint, **params):
        return json.loads((MKT / "og_events_nascar.json").read_text())["result"]["data"]

    def batched(self, endpoint, values, **params):
        return OG_INSTRUMENTS if endpoint == "instruments" else OG_TICKERS


def test_the_og_sync_stores_identity_and_a_second_sync_keeps_it(world):
    from racinglines.markets import exchange_driver as D
    with world() as s:
        for _ in range(2):
            st = D.sync(s, s.connection(), "og", "nascar", client=FakeOG())
            s.expire_all()
        assert st["links"] == 17 and st["new"] == 0 and st["identity"]["links"] == 17 and st["identity"]["athletes"] == 15
        links = s.scalars(select(m.MarketLink).where(m.MarketLink.exchange == "og", m.MarketLink.event_slug == "NSCAR-00002-2026")).all()
        assert len(links) == 17 and {l.prediction for l in links} == {"unmodeled"}
        larson = next(l for l in links if l.group_title == "Kyle Larson")
        assert larson.athlete_id == named(s, "Kyle Larson") and larson.params["kind"] == "champion" and larson.params["season"] == 2026
        assert larson.params["contract"] == "Moneyline"                              # what the driver stored before is kept


# --- the pass over links already stored ------------------------------------------------------------------------

def store(s, rows):
    """Put rows in market_links the way the tape-only sync did before this change: no driver, no race, params = series + rules."""
    comp, cat = KS.competition(s, "nascar")
    for r in rows:
        s.add(m.MarketLink(competition_id=comp.id, category_id=cat.id, **r))
    s.commit()


def test_relink_reports_first_then_writes_then_undoes(world, tmp_path):
    with world() as s:
        store(s, kalshi_rows("KXNASCARRACE-SOUP26", "KXNASCARRACE-FOCH100326", "KXNASCARCUPSERIES-NCS26"))
        before = {l.token_id: (l.athlete_id, l.race_id, l.params) for l in s.scalars(select(m.MarketLink).where(m.MarketLink.token_id.like("KXNASCAR%")))}
        report = L.relink(s, s.connection())                                            # dry run
        assert report["links"] == 24 and report["changed"] == 24
        assert {tuple(k.split("|"))[1:] for k in report["shapes"]} == {("KXNASCARRACE", "cup", "race_win"), ("KXNASCARRACE", "xfinity", "race_win"),
                                                                       ("KXNASCARCUPSERIES", "cup", "champion")}
        assert report["shapes"]["kalshi|KXNASCARRACE|cup|race_win"] == dict(links=8, athlete=4, race=8)      # 4 of the 8 drivers are in the fixtures' pool
        s.expire_all()
        assert all(before[l.token_id] == (l.athlete_id, l.race_id, l.params) for l in s.scalars(select(m.MarketLink).where(m.MarketLink.token_id.like("KXNASCAR%"))))
        assert "24 would change" in L.format_report(report)

        undo = tmp_path / "undo.json"
        report = L.relink(s, s.connection(), apply=True, undo_path=undo)
        s.commit()
        assert report["undo"] == str(undo) and len(json.loads(undo.read_text())) == 24
        link = s.scalars(select(m.MarketLink).filter_by(token_id="KXNASCARRACE-SOUP26-BRKE")).one()
        assert link.race_id == race_id_of(s, "2026-5630") and link.params["kind"] == "race_win"
        assert L.relink(s, s.connection())["changed"] == 0                             # settled: a second pass has nothing to do
        assert L.relink(s, s.connection(), exchange="polymarket")["links"] == 0

        assert L.undo(s, undo) == 24
        s.commit()
        s.expire_all()
        assert {l.token_id: (l.athlete_id, l.race_id, l.params) for l in s.scalars(select(m.MarketLink).where(m.MarketLink.token_id.like("KXNASCAR%")))} == before


def test_the_link_command_needs_a_fresh_backup_before_it_writes(world, tmp_path, monkeypatch, capsys):
    import os
    import time

    from racinglines.cli import nascar as CLI
    from racinglines.db import changes
    from racinglines import paths
    monkeypatch.setattr(paths, "DATA", tmp_path)
    url = world.kw["bind"].url.render_as_string(hide_password=False)
    with world() as s:
        store(s, kalshi_rows("KXNASCARCUPSERIES-NCS26"))
    assert CLI.main(["--db", url, "link"]) == 0                                       # a dry run needs nothing
    assert "Dry run: nothing written" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="--backup FILE"):
        CLI.main(["--db", url, "link", "--apply"])
    dump = tmp_path / "racinglines-before-nascar-links-test.sql.gz"
    dump.write_bytes(b"x")
    os.utime(dump, (time.time() - 3 * 86400,) * 2)
    with pytest.raises(SystemExit, match="--backup FILE"):
        CLI.main(["--db", url, "link", "--apply", "--backup", str(dump)])               # three days old
    os.utime(dump)
    assert CLI.main(["--db", url, "link", "--apply", "--backup", str(dump)]) == 0
    assert "Wrote 8 links" in capsys.readouterr().out
    with world() as s:
        row = changes.recent(s, 5, "nascar")[0]
        assert row.kind == "link" and dump.name in row.summary and row.detail["changed"] == 8
        undo = row.detail["undo"]
    assert CLI.main(["--db", url, "link", "--undo", undo]) == 0
    with world() as s:
        assert s.scalars(select(m.MarketLink).filter_by(token_id="KXNASCARCUPSERIES-NCS26-KLAR")).one().athlete_id is None


def test_the_season_forecast_finds_every_venues_cup_champion_contract(world):
    """racinglines nascar season --quotes: OG.com's 17 contracts and Kalshi's Cup series market, read as they are
    listed (nothing stored), all Cup champion 2026; the Xfinity/Trucks champion and race markets are left out."""
    from racinglines.pipelines import nascar_season as NSP
    with world() as s:
        rows = og_rows() + kalshi_rows("KXNASCARCUPSERIES-NCS26") + kalshi_rows("KXNASCARRACE-SOUP26")
        got = NSP.champions(rows, linker(s), 2026)
        assert len(got[got["exchange"] == "og"]) == 17
        assert set(got["exchange"]) == {"og", "kalshi"}
        assert got["athlete_id"].notna().sum() >= 16
        assert NSP.champions(og_rows(), linker(s), 2025).empty
