"""The study's one input: past finishing orders, one row per (race, athlete).

Columns of a results frame: sport, race_id, date, athlete_id, position, status, team.
Sources: a plain-text pg_dump (`load_dump`, parsed without a database) and CSVs pulled through the read-only
sql tool (`read_csv`); `combine` stacks them, a later source replacing a race it repeats.

Rules (the same for every algorithm):
- the race of a sport is its main classification: f1 / motogp / nascar round kind 'race', mtb_dh the Men Elite
  'final' (one race per category);
- DNS rows are dropped (never started); OK is a finisher; DNF / DSQ (and anything else) started but is ranked
  behind every finisher, as an unordered tail.
"""

import gzip
import io

import numpy as np
import pandas as pd

COLUMNS = ["sport", "race_id", "date", "athlete_id", "position", "status", "team"]
SPORTS = ["f1", "motogp", "nascar", "mtb_dh"]
ROUND_KIND = {"f1": "race", "motogp": "race", "nascar": "race", "mtb_dh": "final"}
DH_CATEGORY = "ME"

TABLES = {
    "sports": ["id", "code", "name", "result_kind"],
    "competitions": ["id", "code", "name", "league_id", "sport_id"],
    "seasons": ["id", "competition_id", "year", "label"],
    "events": ["id", "season_id", "source", "source_key", "name", "start_date", "venue_id", "series_round", "status"],
    "categories": ["id", "competition_id", "code", "name", "gender", "age_group"],
    "races": ["id", "event_id", "category_id", "format"],
    "rounds": ["id", "race_id", "kind", "ordinal", "name", "extra"],
    "results": ["id", "round_id", "athlete_id", "position", "status", "time_ms", "bib", "team", "nation", "extra"],
}


def _copy_blocks(path, tables):
    """{table: DataFrame} from the COPY ... FROM stdin blocks of a plain pg_dump (gzip or not)."""
    opener = gzip.open if str(path).endswith(".gz") else open
    out, cur, buf = {}, None, []
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            if cur is None:
                if line.startswith("COPY public."):
                    name = line[len("COPY public."):].split(" ", 1)[0]
                    if name in tables:
                        cur, buf = name, []
                continue
            if line.startswith("\\."):
                out[cur] = pd.read_csv(io.StringIO("".join(buf)), sep="\t", header=None, names=tables[cur],
                                       quoting=3, na_values=["\\N"], keep_default_na=False, dtype=str)
                cur = None
                continue
            buf.append(line)
    return out


def load_dump(path):
    """The results frame for SPORTS from a pg_dump file."""
    t = _copy_blocks(path, TABLES)
    sp = t["sports"][["id", "code"]].rename(columns={"id": "sport_id", "code": "sport"})
    comp = t["competitions"][["id", "sport_id"]].rename(columns={"id": "competition_id"})
    sea = t["seasons"][["id", "competition_id"]].rename(columns={"id": "season_id"})
    ev = t["events"][["id", "season_id", "start_date"]].rename(columns={"id": "event_id", "start_date": "date"})
    cat = t["categories"][["id", "code"]].rename(columns={"id": "category_id", "code": "category"})
    ra = t["races"][["id", "event_id", "category_id"]].rename(columns={"id": "race_id"})
    ro = t["rounds"][["id", "race_id", "kind"]].rename(columns={"id": "round_id"})
    re = t["results"][["round_id", "athlete_id", "position", "status", "team"]]
    df = (re.merge(ro, on="round_id").merge(ra, on="race_id").merge(cat, on="category_id", how="left")
          .merge(ev, on="event_id").merge(sea, on="season_id").merge(comp, on="competition_id").merge(sp, on="sport_id"))
    keep = df["sport"].isin(SPORTS) & (df["kind"] == df["sport"].map(ROUND_KIND))
    keep &= (df["sport"] != "mtb_dh") | (df["category"] == DH_CATEGORY)
    return normalize(df[keep])


def normalize(df):
    """Types and column order of a results frame; rows sorted by sport, date, race, position."""
    out = pd.DataFrame({
        "sport": df["sport"].astype(str),
        "race_id": pd.to_numeric(df["race_id"]).astype(int),
        "date": pd.to_datetime(df["date"]).dt.normalize(),
        "athlete_id": pd.to_numeric(df["athlete_id"]).astype(int),
        "position": pd.to_numeric(df["position"], errors="coerce"),
        "status": df["status"].fillna("").astype(str),
        "team": df["team"].fillna("").astype(str) if "team" in df else "",
    })
    return out.sort_values(["sport", "date", "race_id", "position"], na_position="last").reset_index(drop=True)


def read_csv(path):
    return normalize(pd.read_csv(path, dtype={"status": str, "team": str}, keep_default_na=False,
                                 na_values={"position": [""]}))


def combine(*frames):
    """Stack results frames; a race present in a later frame replaces the earlier copy."""
    out = None
    for f in frames:
        if out is None:
            out = f
            continue
        out = pd.concat([out[~out["race_id"].isin(f["race_id"].unique())], f])
    return normalize(out)


def races(frame):
    """Per race (date order): dict(race_id, date, ids, order, n_fin).

    `ids` are the starters (DNS dropped) in finishing order: finishers by position, then the non-finishers (by
    recorded position where present, which only fixes the array order: they are an unordered tail);
    `n_fin` is the number of finishers, so ids[:n_fin] is the classified order and ids[n_fin:] the tail."""
    f = frame[frame["status"] != "DNS"]
    out = []
    for (date, rid), g in f.groupby(["date", "race_id"], sort=True):
        fin = g[g["status"] == "OK"].sort_values("position")
        dnf = g[g["status"] != "OK"].sort_values("position", na_position="last")
        ids = np.concatenate([fin["athlete_id"].to_numpy(), dnf["athlete_id"].to_numpy()]).astype(np.int64)
        if len(np.unique(ids)) != len(ids):
            _, first = np.unique(ids, return_index=True)
            ids = ids[np.sort(first)]
        out.append(dict(race_id=int(rid), date=pd.Timestamp(date), ids=ids, n_fin=int(min(len(fin), len(ids))),
                        team={int(a): t for a, t in zip(g["athlete_id"], g["team"])}))
    return out


def read_packed(paths, sport):
    """A results frame from the compact text the study's sql pull wrote (SOURCES.md has the query): one line per
    race chunk, `race_id|date|chunk|entries`, entries `athlete_id[d].team_key` in finishing order (finishers by
    position, then non-finishers marked `d`), team_key a per-sport dense rank of results.team. `position` is the
    finishing order (1..n over finishers, NaN for non-finishers); DNS rows were left out by the query."""
    rows = []
    for path in paths:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rid, date, chunk, entries = line.split("|", 3)
                for k, e in enumerate(entries.split()):
                    a, team = e.split(".", 1)
                    dnf = a.endswith("d")
                    rows.append((sport, int(rid), date, int(chunk), k, int(a.rstrip("d")), "DNF" if dnf else "OK",
                                 f"{sport}:{team}"))
    df = pd.DataFrame(rows, columns=["sport", "race_id", "date", "chunk", "k", "athlete_id", "status", "team"])
    df = df.sort_values(["race_id", "chunk", "k"]).reset_index(drop=True)
    df["position"] = np.nan
    ok = df["status"] == "OK"
    df.loc[ok, "position"] = df[ok].groupby("race_id").cumcount() + 1
    return normalize(df)
