"""Downhill data paths on synthetic inputs (docs/todo.md, Data): UCI rider IDs from the download to
the database, and merging two athletes that are the same person. The live ChronoRace API isn't
reachable from every machine, so the downloader is fed a recorded-shape JSON; unverified against
the live API."""

import pandas as pd
import pytest

from racinglines.sources.chronorace import download as D
from racinglines.sources.chronorace.parse import parse_markdown_tables_file

RIDERS = {"1001": dict(RaceNr=1001, PrintName="WILLIAMS Robert Jordan", UciTeamName="TEAM A", Nation="GBR",
                       UciRiderId="10011112222"),
          "1002": dict(RaceNr=1002, PrintName="BRUNI Loïc", UciTeamName="TEAM B", Nation="FRA",
                       UciRiderId="10009998888")}


def _json(times=(180_000, 181_500)):
    return dict(Riders=RIDERS, Results=[
        dict(RaceNr=1001 + i, Position=i + 1, Status="Finished", RaceTime=t,
             Times=[dict(RaceTime=t // 2, TimeGap=0), dict(RaceTime=t, TimeGap=t - times[0])])
        for i, t in enumerate(times)])


class _Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def _event_file(tmp_path, monkeypatch, data, uci=True):
    monkeypatch.setattr(D.http, "get", lambda session, url, **kw: _Resp(data))
    table = D.build_round_table("20260821_mtb", "dh", "3", "Final", session=None)
    if not uci:                                      # an older download: no UCI ID column
        lines = []
        for line in table.splitlines():
            cells = line.split("|")
            lines.append("|".join(cells[:6] + cells[7:]) if line.startswith("|") else line)
        table = "\n".join(lines) + "\n"
    f = tmp_path / "20260821_mtb_dhi_elite-men.md"
    f.write_text("# UCI MOUNTAIN BIKE WORLD SERIES - DHI #7 - Les Gets, August 21-23, FRA\n\n"
                 "Category: Men Elite\n\nSource: ChronoRace (prod.chronorace.be), event slug `20260821_mtb`\n\n"
                 + table)
    return f


def test_download_writes_uci_ids_and_parse_reads_them(tmp_path, monkeypatch):
    f = _event_file(tmp_path, monkeypatch, _json())
    text = f.read_text()
    assert "| Pos | Bib | Rider | Team | Nation | UCI ID |" in text and "| 10011112222 |" in text
    rows = pd.DataFrame(parse_markdown_tables_file(f))
    fin = rows[rows["sector_id"] == "FINISH"].set_index("rider_name")
    assert fin.loc["WILLIAMS Robert Jordan", "uci_id"] == "10011112222"
    assert fin.loc["WILLIAMS Robert Jordan", "rider_id"] == "name:williams robert jordan"   # unchanged key
    assert fin.loc["BRUNI Loïc", "cum_time_s"] == pytest.approx(181.5)


def test_older_files_parse_exactly_as_before(tmp_path, monkeypatch):
    rows = parse_markdown_tables_file(_event_file(tmp_path, monkeypatch, _json(), uci=False))
    assert rows and all("uci_id" not in r for r in rows)


def _ingest(engine, path):
    from sqlalchemy.orm import Session

    from racinglines.sources.chronorace.ingest import ingest_file, seed
    with Session(engine) as s:
        seed(s)
        status = ingest_file(s, path, force=True)
        s.commit()
    return status


def _athletes(engine):
    from sqlalchemy import text
    with engine.connect() as c:
        return pd.read_sql(text("""SELECT a.id, a.display_name, i.scheme, i.value FROM athletes a
                                   JOIN athlete_identifiers i ON i.athlete_id = a.id ORDER BY a.id, i.scheme"""), c)


def test_ingest_matches_uci_ids_first_and_reports_name_changes(test_engine, tmp_path, monkeypatch):
    from sqlalchemy import text
    with test_engine.begin() as c:                   # a clean slate for athletes in the test database
        c.execute(text("TRUNCATE athletes, athlete_identifiers, results, rounds, races, events, source_files CASCADE"))
    # 1. an old file without UCI IDs: athletes by name only
    old = tmp_path / "old"
    old.mkdir()
    _ingest(test_engine, _event_file(old, monkeypatch, _json(), uci=False))
    a = _athletes(test_engine)
    assert set(a["scheme"]) == {"name"} and a["id"].nunique() == 2
    # 2. the same file with UCI IDs: matched by name, gains the UCI identifier, no new athlete
    new = tmp_path / "new"
    new.mkdir()
    _ingest(test_engine, _event_file(new, monkeypatch, _json()))
    a = _athletes(test_engine)
    assert a["id"].nunique() == 2 and (a["scheme"] == "uci").sum() == 2
    williams = int(a.loc[a["value"] == "10011112222", "id"].iloc[0])
    # 3. a later event where he's printed "WILLIAMS Jordan": the UCI ID keeps him the same athlete
    renamed = dict(RIDERS, **{"1001": dict(RIDERS["1001"], PrintName="WILLIAMS Jordan")})
    later = tmp_path / "later"
    later.mkdir()
    status = _ingest(test_engine, _event_file(later, monkeypatch, dict(_json(), Riders=renamed)))
    a = _athletes(test_engine)
    assert a["id"].nunique() == 2 and "merge" not in status
    assert int(a.loc[a["value"] == "williams jordan", "id"].iloc[0]) == williams
    # 4. an athlete created by name under the new spelling, before UCI IDs: reported for a merge
    with test_engine.begin() as c:
        c.execute(text("UPDATE athlete_identifiers SET athlete_id = :w WHERE value = 'williams jordan'"),
                  dict(w=williams))
        other = c.execute(text("INSERT INTO athletes (display_name) VALUES ('WILLIAMS Jordan') RETURNING id")).scalar()
        c.execute(text("UPDATE athlete_identifiers SET athlete_id = :o WHERE value = 'williams jordan'"), dict(o=other))
    status = _ingest(test_engine, _event_file(later, monkeypatch, dict(_json(), Riders=renamed)))
    assert f"merge {other} into {williams}" in status


def test_merge_athletes_moves_everything_or_refuses(test_engine):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from racinglines.db.ingest import merge_athletes
    with test_engine.begin() as c:
        keep, drop = (c.execute(text("INSERT INTO athletes (display_name) VALUES (:n) RETURNING id"), dict(n=n)).scalar()
                      for n in ("KEEP Rider", "DROP Rider"))
        c.execute(text("INSERT INTO athlete_identifiers (scheme, value, athlete_id) VALUES ('name', 'drop rider', :d)"),
                  dict(d=drop))
    with Session(test_engine) as s:
        assert merge_athletes(s, keep, drop, dry_run=True) == {"athlete_identifiers": 1}
        assert s.get(__import__("racinglines.db.models", fromlist=["Athlete"]).Athlete, drop) is not None
        with pytest.raises(ValueError):
            merge_athletes(s, keep, keep)
        moved = merge_athletes(s, keep, drop)
        s.commit()
    assert moved == {"athlete_identifiers": 1}
    with test_engine.connect() as c:
        assert c.execute(text("SELECT athlete_id FROM athlete_identifiers WHERE value = 'drop rider'")).scalar() == keep
        assert c.execute(text("SELECT count(*) FROM athletes WHERE id = :d"), dict(d=drop)).scalar() == 0
