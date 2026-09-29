"""Downhill championship points tables (racinglines/models/timed_runs/points.py): per-season schemes
from points_schemes, the owner's entry file, and reconciliation with official standings. The official
UCI scales aren't in the repo yet, so these tests use the placeholders and synthetic results."""

import pandas as pd
import pytest

from racinglines.models.timed_runs import model as M
from racinglines.models.timed_runs import points as P
from racinglines.paths import ROOT

TEMPLATE = ROOT / "sports" / "points" / "uci_dhi_wc.toml"


def _raw(n_events=2, riders=("Ann Able", "Bea Best", "Cat Cole", "Dee Dunn")):
    """Single-qualifier weekends: everyone rides the qualifier and the Final, in reversed order."""
    rows = []
    for e in range(n_events):
        for rnd in ("qual", "final"):
            order = list(riders) if (rnd == "final") == (e % 2 == 0) else list(reversed(riders))
            for pos, name in enumerate(order, 1):
                rows.append(dict(event_id=f"ev{e}", event_date=f"2026-0{e + 3}-01", category="ME", round=rnd,
                                 rider_id=name.lower().replace(" ", "_"), rider_name=name, rank_at_split=pos,
                                 status="OK", sector_id="FINISH", series_round=e + 1))
    return pd.DataFrame(rows)


def test_through_round_with_a_number_used_twice_in_a_season():
    """ChronoRace numbers two weekends of one season the same (2022: Leogang and Lenzerheide both #3): "after
    round 3" is the later of the two, so both count; an unknown number is an error, not the first event."""
    raw = _raw(n_events=4)
    raw.loc[raw["event_id"] == "ev2", "series_round"] = 2          # ev1 and ev2 are both round 2; ev3 is round 4
    raw.loc[raw["event_id"] == "ev3", "series_round"] = 4
    assert P.through_event(raw, 1) == "ev0"
    assert P.through_event(raw, 2) == "ev2"
    assert P.through_event(raw, 4) == "ev3"
    with pytest.raises(ValueError):
        P.through_event(raw, 3)
    official = pd.DataFrame(dict(rider=["Ann Able"], points=[0.0]))
    after2 = P.reconcile(raw, official, P.through_event(raw, 2))
    every = P.reconcile(raw[raw["event_id"] != "ev3"], official)
    assert after2.equals(every)                                     # both round-2 weekends counted


def _row(season_from, round_kind, points, season_to=None, official=False):
    return dict(season_from=season_from, season_to=season_to, round_kind=round_kind, points=points,
                is_official=official)


def test_from_rows_by_era_with_schema_fallback():
    rows = [_row(2021, "final", [100, 50], 2022), _row(2021, "qual", [10, 5], 2022),
            _row(2025, "final", [300, 200, 100], official=True), _row(2025, "qual1", [30], official=True)]
    s = P.from_rows(rows, range(2020, 2028))
    assert set(s) == {2021, 2022, 2025, 2026, 2027}
    assert s[2022].final == (100, 50) and s[2022].qual == (10, 5) and not s[2022].official
    assert s[2026].final == (300, 200, 100) and s[2026].official and s[2026].source == "db"
    assert P.scheme_for(2023, s) == P.schema_scheme()                    # no row: the placeholders


def test_use_sets_and_restores_the_tables():
    before = (list(M.FINAL_POINTS), list(M.QUAL_POINTS), dict(M.QUAL_POINTS_ROUND))
    with P.use(P.Scheme(final=(9, 8), qual=(1,))):
        assert M.FINAL_POINTS == [9, 8] and M.QUAL_POINTS == [1] and M.QUAL_POINTS_ROUND == before[2]
    assert (M.FINAL_POINTS, M.QUAL_POINTS, M.QUAL_POINTS_ROUND) == before
    with P.use(None):
        assert M.FINAL_POINTS == before[0]


def test_unset_scheme_scores_exactly_as_today():
    raw = _raw()
    today = M.actual_event_points(raw)
    with P.use(P.schema_scheme()):
        assert M.actual_event_points(raw).equals(today)
    with P.use(P.Scheme(final=tuple(2 * p for p in M.FINAL_POINTS), qual=tuple(2 * p for p in M.QUAL_POINTS))):
        assert (M.actual_event_points(raw)["points"] == 2 * today["points"]).all()


def test_template_file_is_valid_and_all_placeholder():
    rows = P.read_file(TEMPLATE)
    assert rows and not any(r["official"] for r in rows)
    s = P.from_rows([dict(r, is_official=r["official"], season_to=r.get("season_to")) for r in rows], range(2021, 2027))
    assert set(s) == set(range(2021, 2027))
    assert all(sc.final == tuple(M.FINAL_POINTS) and sc.qual == tuple(M.QUAL_POINTS) for sc in s.values())


def test_read_file_rejects_bad_tables(tmp_path):
    f = tmp_path / "p.toml"
    f.write_text('[[scheme]]\nseason_from = 2026\nround_kind = "final"\npoints = [10, 20]\n')
    with pytest.raises(ValueError):
        P.read_file(f)
    f.write_text('[[scheme]]\nseason_from = 2026\nround_kind = "lunch"\npoints = [10]\n')
    with pytest.raises(ValueError):
        P.read_file(f)


def test_reconcile_matches_and_flags_differences():
    raw = _raw()
    pts = M.actual_event_points(raw).groupby("rider_id")["points"].sum()
    names = raw.drop_duplicates("rider_id").set_index("rider_id")["rider_name"]
    official = pd.DataFrame(dict(rider=[names[r] for r in pts.index], points=pts.to_numpy()))
    rec = P.reconcile(raw, official)
    assert (rec["diff"] == 0).all() and len(rec) == 4
    # names match regardless of accents, case and word order; a missing rider and a wrong total show up
    off = official.copy()
    off.loc[0, "rider"] = off.loc[0, "rider"].upper()
    off.loc[1, "rider"] = " ".join(reversed(off.loc[1, "rider"].split()))
    off.loc[2, "points"] += 5
    off = pd.concat([off.iloc[:3], pd.DataFrame(dict(rider=["Émile Extra"], points=[40]))], ignore_index=True)
    rec = P.reconcile(raw, off)
    assert (rec["diff"] != 0).sum() == 3            # +5 rider, the rider left out, the extra rider
    # after the first event only
    first = P.reconcile(raw, official, through="ev0")
    assert (first["computed"] < first["official"]).any()


def test_read_standings_toml_and_csv(tmp_path):
    t = tmp_path / "s.toml"
    t.write_text('source = "test"\n[points]\n"Loïc Bruni" = 120\n"Amaury Pierron" = 95.5\n')
    c = tmp_path / "s.csv"
    c.write_text("rider,points,nation\nLoïc Bruni,120,FRA\nAmaury Pierron,95.5,FRA\n")
    a, b = P.read_standings(t), P.read_standings(c)
    assert a.equals(b) and list(a.columns) == ["rider", "points"]


def test_import_rows_and_load(test_engine):
    from sqlalchemy.orm import Session

    from racinglines.db.ingest import seed
    with Session(test_engine) as s:
        seed(s)
        s.commit()
        n = P.import_rows(s, [dict(season_from=2025, round_kind="final", points=[300, 200], official=True),
                              dict(season_from=2025, round_kind="qual1", points=[30, 20], official=True)])
        assert n == 2
        P.import_rows(s, [dict(season_from=2025, round_kind="final", points=[310, 210], official=True)])  # replaces
    with test_engine.connect() as c:
        schemes = P.load(c)
    assert schemes[2026].final == (310, 210) and schemes[2026].qual == (30, 20) and schemes[2026].official
    assert 2024 not in schemes


# --- pinning: our totals against the official standings (owner-entered) ----------------------------

STANDINGS = ROOT / "sports" / "points" / "standings"          # <competition>_<season>_<category>_r<round>.toml


@pytest.mark.parametrize("path", sorted(STANDINGS.glob("*.toml")) or [None], ids=lambda p: p.name if p else "none")
def test_totals_match_official_standings(path):
    """Every rider's cumulative points equal the official standings file, with the tables in
    points_schemes. Skips until the owner adds a standings file and the official tables."""
    if path is None:
        pytest.skip(f"no official standings yet: add {STANDINGS.relative_to(ROOT)}/uci_dhi_wc_2026_ME_r7.toml "
                    "and import the official tables")
    from racinglines.db.config import get_engine
    from racinglines.db.queries import load_tidy
    competition, season, category, rnd = path.stem.rsplit("_", 3)
    try:
        eng = get_engine()
        raw = load_tidy(eng, competition=competition, with_splits=False)
        with eng.connect() as c:
            schemes = P.load(c, competition)
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"no database with downhill results: {ex}")
    target = M.select_target(raw, int(season), category)
    through = P.through_event(target, int(rnd.lstrip("r")))
    scheme = P.scheme_for(int(season), schemes)
    assert scheme.official, f"{season}: the points tables are still placeholders"
    with P.use(scheme):
        rec = P.reconcile(target, P.read_standings(path), through)
    assert (rec["diff"].abs() < 1e-9).all(), rec[rec["diff"] != 0].to_string()
