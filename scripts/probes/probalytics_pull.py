"""Read-only pull of Probalytics F1 order books and fills to data/probalytics/ (gitignored), from the owner's Mac.

Markets are chosen by exact key from our own F1 market_links (owner policy: exact keys, never title matching):
Kalshi by ticker (Probalytics platform_id = our token_id), Polymarket by condition id (= our condition_id). The
links come from the VM's archive (data/archive/markets/<venue>/links/market_links.parquet, competition_code f1_wdc),
copied to data/probalytics/links/our_<venue>_links.parquet.

Every output file is written once and skipped while it is current (MANIFEST.jsonl records the links key it was
written with; a wider set of markets refetches it), so a later, wider run fills in only what is missing (the owner's
"y-small now, the rest of y later"). Each file's query, range, row count and links key go to MANIFEST.jsonl.

    books   books/<YYYY-MM-DD>_F1_<VENUE>.parquet   every snapshot of the day, all levels (same columns as the
                                                    2026-10-07 pull, plus `state`)
    fills   fills/F1_<VENUE>_<YYYY-MM>.parquet      every fill of the month
    stages  stages/<event_key>_<VENUE>.parquet      the book as of each stage cutoff of a weekend (weekend_sweep's
                                                    schedule): the last snapshot per market and outcome at or before
                                                    the cutoff, within LOOKBACK_H hours

    # LOCAL (Mac): y-small (2026-10-13)
    python scripts/probes/probalytics_pull.py fills  --from 2025-06-01
    python scripts/probes/probalytics_pull.py books  --from 2026-09-01
    python scripts/probes/probalytics_pull.py stages --year 2026
    # the rest of y, later (only missing days are fetched)
    python scripts/probes/probalytics_pull.py books  --venue polymarket --from 2025-11-20
    python scripts/probes/probalytics_pull.py books  --venue kalshi     --from 2026-05-09

To the bucket (the big data plan, library/engineering/2026-10-14-big-data-storage.md: from NASCAR on the pull runs on the VM,
whose service account can write the bucket): with --to-bucket (or PROBALYTICS_BUCKET) each file is copied to the same
relative path under that prefix as soon as it is written, the object's size is checked against the local file, the
upload goes to MANIFEST.jsonl and the local copy is deleted (--keep-local keeps it), so the disk holds one file at a time.
A file recorded as uploaded counts as present, so a rerun skips it. MANIFEST.jsonl itself is copied after each upload.

    # VM: one venue-day at a time straight to the bucket
    PROBALYTICS_ENV=/opt/racinglines-staging/.env.probalytics python scripts/probes/probalytics_pull.py books \
      --to-bucket gs://racinglines-data-384052502248/vendor/probalytics --from 2026-05-09

Credentials: .env.probalytics (PROBALYTICS_CH_USER / PROBALYTICS_CH_PASSWORD); never printed. A progress line goes to
stderr at least every 5 minutes (CLAUDE.md, long-running jobs).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = Path(os.environ.get("PROBALYTICS_ENV", Path.home() / "py_dev/racinglines/.env.probalytics"))
OUT = Path(os.environ.get("PROBALYTICS_OUT", ROOT / "data/probalytics"))
URL = "https://clickhouse.probalytics.io:8443/"
VENUES = {"kalshi": "KALSHI", "polymarket": "POLYMARKET"}
BOOKS_FROM = {"kalshi": date(2026, 5, 9), "polymarket": date(2025, 11, 20)}   # the tier's first book (probe 10-12)
LOOKBACK_H = 48
CHUNK = 1500
MIN_FREE_GB = float(os.environ.get("MIN_FREE_GB", "4"))   # the Mac had 9 GB free on 2026-10-13
TIMEOUT = 900
PROGRESS_SEC = int(os.environ.get("RACINGLINES_PROGRESS_SEC", "300"))
BUCKET = {"to": os.environ.get("PROBALYTICS_BUCKET", "").rstrip("/"), "keep_local": False}


def env():
    out = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.strip().split("=", 1)
            out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


E = env()
SECRETS = [v for v in E.values() if v]


def scrub(s):
    for v in SECRETS:
        s = s.replace(v, "***")
    return s


def ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CTX = ctx()


def ch(sql, fmt="JSONCompact"):
    """One ClickHouse query; the raw body (bytes). Retries a reset or a timeout three times."""
    auth = base64.b64encode(f"{E['PROBALYTICS_CH_USER']}:{E['PROBALYTICS_CH_PASSWORD']}".encode()).decode()
    url = URL + "?" + urllib.parse.urlencode({"database": "probalytics", "default_format": fmt})
    for attempt in range(4):
        req = urllib.request.Request(url, data=sql.encode(), headers={"Authorization": "Basic " + auth})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(scrub(e.read().decode(errors="replace"))[:800]) from None
        except (ConnectionError, TimeoutError, urllib.error.URLError) as e:
            if attempt == 3:
                raise
            wait = 15 * 2 ** attempt
            log(f"retry in {wait}s after {type(e).__name__}")
            time.sleep(wait)


T0 = time.time()
STATE = {"done": 0, "total": 0, "item": ""}


def log(msg):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


def heartbeat():
    while True:
        time.sleep(PROGRESS_SEC)
        log(f"progress probalytics_pull: {(time.time() - T0) / 60:.0f} min elapsed · "
            f"{STATE['done']} of {STATE['total']} files · {STATE['item']}")


def manifest(**row):
    with open(OUT / "MANIFEST.jsonl", "a") as f:
        f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(timespec="seconds"), **row)) + "\n")


def our_ids(venue):
    """Our F1 markets for a venue, by exact key: Kalshi tickers or Polymarket condition ids. The union of the VM
    archive's links snapshot (links/our_<venue>_links.parquet) and an export of the live table
    (links/db_f1_links.csv: exchange, token_id, condition_id, ...; the snapshot lags, 2026-09-28 on 10-13)."""
    import pandas as pd
    col = "token_id" if venue == "kalshi" else "condition_id"
    ids = set()
    p = OUT / "links" / f"our_{venue}_links.parquet"
    if p.exists():
        d = pd.read_parquet(p)
        ids |= set(d.loc[d.competition_code == "f1_wdc", col].dropna())
    c = OUT / "links" / "db_f1_links.csv"
    if c.exists():
        d = pd.read_csv(c, dtype=str)
        ids |= set(d.loc[d.exchange == venue, col].dropna())
    return sorted(ids)


def entries():
    """{file relative to OUT: its last MANIFEST.jsonl row}."""
    m = OUT / "MANIFEST.jsonl"
    out = {}
    if m.exists():
        for line in m.read_text().splitlines():
            r = json.loads(line)
            out[r["file"]] = r
    return out


def written_keys():
    """{file relative to OUT: the links key it was written with} (the last entry wins)."""
    return {f: r.get("links_key") for f, r in entries().items()}


def current(path, key):
    """The file was written with this links key (a wider set of markets makes it stale) and is still here, or was
    uploaded to the bucket."""
    r = entries().get(str(path.relative_to(OUT)))
    return r is not None and r.get("links_key") == key and (path.exists() or bool(r.get("uploaded")))


def gcloud(*args):
    return subprocess.run(["gcloud", "storage", *args], check=True, capture_output=True, text=True).stdout.strip()


def upload(path, **meta):
    """path to the same relative path under BUCKET["to"]; the object's size must match before the local copy goes."""
    rel = str(path.relative_to(OUT))
    dest = f"{BUCKET['to']}/{rel}"
    size = path.stat().st_size
    gcloud("cp", "--quiet", str(path), dest)
    got = gcloud("objects", "describe", dest, "--format=value(size)")
    if got != str(size):
        sys.exit(f"stopping: {dest} is {got or '?'} bytes in the bucket, {size} here; the local file is kept")
    keep = BUCKET["keep_local"]
    manifest(file=rel, bytes=size, uploaded=dest, local=keep, **meta)
    if not keep:
        path.unlink()
    gcloud("cp", "--quiet", str(OUT / "MANIFEST.jsonl"), f"{BUCKET['to']}/MANIFEST.jsonl")
    log(f"{path.name}: uploaded to {dest}" + ("" if keep else ", local copy deleted"))


def market_map(venue):
    """{probalytics market uuid: platform_id} for our F1 markets, cached in links/probalytics_<venue>_f1.json."""
    cache = OUT / "links" / f"probalytics_{venue}_f1.json"
    ids = our_ids(venue)
    key = hashlib.sha1("\n".join(ids).encode()).hexdigest()[:12]
    if cache.exists():
        c = json.loads(cache.read_text())
        if c["key"] == key:
            return c["map"], key
    m = {}
    for i in range(0, len(ids), CHUNK):
        lst = ",".join("'" + x.replace("'", "") + "'" for x in ids[i:i + CHUNK])
        body = ch(f"SELECT toString(id), platform_id FROM markets WHERE platform = '{VENUES[venue]}' "
                  f"AND platform_id IN ({lst})")
        m.update({u: p for u, p in json.loads(body)["data"]})
    cache.write_text(json.dumps(dict(key=key, ours=len(ids), found=len(m), map=m)))
    log(f"{venue}: {len(ids)} of our F1 markets, {len(m)} found in Probalytics (links key {key})")
    return m, key


# The filters run in an inner SELECT: an alias such as `toString(market_id) AS market_id` would otherwise
# replace the column in WHERE (ClickHouse resolves aliases there) and match nothing.
BOOK_COLS = """toString(market_id) AS market_id, market_platform_id, toString(platform) AS platform,
  outcome.platform_id AS outcome_pid, outcome.name AS outcome_name, timestamp, indexed_at,
  toString(continuity) AS continuity, path_index, toString(state) AS state,
  length(bids) AS n_bids, length(asks) AS n_asks,
  arraySum(arrayMap(x -> toFloat64(x.size), bids)) AS bid_size_total,
  arraySum(arrayMap(x -> toFloat64(x.size), asks)) AS ask_size_total,
  arrayMap(x -> toFloat64(x.price), bids) AS bid_px, arrayMap(x -> toFloat64(x.size), bids) AS bid_sz,
  arrayMap(x -> toFloat64(x.price), asks) AS ask_px, arrayMap(x -> toFloat64(x.size), asks) AS ask_sz"""

FILL_COLS = """toString(id) AS fill_id, toString(market_id) AS market_id, market_platform_id,
  toString(platform) AS platform, platform_id AS venue_fill_id, outcome.platform_id AS outcome_pid,
  outcome.name AS outcome_name, outcome.index AS outcome_index, toFloat64(size) AS size, toFloat64(price) AS price,
  toFloat64(normalized_price) AS normalized_price, toString(taker_side) AS taker_side, toFloat64(fee) AS fee,
  timestamp, indexed_at"""


def chunks(m, size=CHUNK):
    """The market uuids as SQL IN lists of CHUNK each: one list of ~5,000 would pass max_query_size (256 KB)."""
    u = sorted(m)
    return [",".join(f"toUUID('{x}')" for x in u[i:i + size]) for i in range(0, len(u), size)]


def fetch(path, sql_for, m, size=CHUNK, **meta):
    """sql_for(in_list) run once per chunk of the markets m, as Parquet, joined into path (atomically); skipped
    when path exists. Returns rows written, or None if skipped."""
    if current(path, meta.get("links_key")):
        return None
    free = shutil.disk_usage(OUT).free / 1e9
    if free < MIN_FREE_GB:
        sys.exit(f"stopping: {free:.1f} GB free on {OUT}'s disk, under MIN_FREE_GB={MIN_FREE_GB}")
    import io
    import pyarrow as pa
    import pyarrow.parquet as pq
    path.parent.mkdir(parents=True, exist_ok=True)
    t = time.time()
    parts = [pq.read_table(io.BytesIO(ch(sql_for(lst) + " FORMAT Parquet", fmt="Parquet"))) for lst in chunks(m, size)]
    parts = [x for x in parts if x.num_rows] or parts[:1]
    tab = pa.concat_tables(parts, promote_options="permissive") if len(parts) > 1 else parts[0]
    tmp = path.with_suffix(".part")
    pq.write_table(tab, tmp, compression="zstd")
    tmp.replace(path)
    size = path.stat().st_size
    manifest(file=str(path.relative_to(OUT)), rows=tab.num_rows, bytes=size, sec=round(time.time() - t, 1), **meta)
    log(f"{path.name}: {tab.num_rows:,} rows, {size / 1e6:.1f} MB, {time.time() - t:.0f}s")
    if BUCKET["to"]:
        upload(path, rows=tab.num_rows, **meta)
    return tab.num_rows


def days(a, b):
    while a <= b:
        yield a
        a += timedelta(days=1)


def months(a, b):
    a = a.replace(day=1)
    while a <= b:
        yield a
        a = (a + timedelta(days=32)).replace(day=1)


def run_books(venues, start, end):
    jobs = []
    for v in venues:
        m, key = market_map(v)
        for d in days(max(start, BOOKS_FROM[v]), end):
            p = OUT / "books" / f"{d:%Y-%m-%d}_F1_{VENUES[v]}.parquet"
            if not current(p, key):
                jobs.append((v, m, key, d, p))
    STATE["total"] = len(jobs)
    for v, m, key, d, p in jobs:
        STATE["item"] = p.name
        sql = (lambda lst, d=d: f"SELECT {BOOK_COLS} FROM (SELECT * FROM orderbook_snapshots WHERE market_id IN ({lst}) "
               f"AND timestamp >= '{d} 00:00:00' AND timestamp < '{d + timedelta(days=1)} 00:00:00') "
               f"ORDER BY market_id, outcome_pid, timestamp")
        fetch(p, sql, m, kind="books", venue=v, day=str(d), links_key=key)
        STATE["done"] += 1


def run_fills(venues, start, end):
    jobs = []
    for v in venues:
        m, key = market_map(v)
        for mo in months(start, end):
            nxt = (mo + timedelta(days=32)).replace(day=1)
            p = OUT / "fills" / f"F1_{VENUES[v]}_{mo:%Y-%m}.parquet"
            # the current month is never final: refetch it each run
            if current(p, key) and nxt <= date.today():
                continue
            jobs.append((v, m, key, mo, nxt, p))
    STATE["total"] = len(jobs)
    for v, m, key, mo, nxt, p in jobs:
        STATE["item"] = p.name
        sql = (lambda lst, mo=mo, nxt=nxt: f"SELECT {FILL_COLS} FROM (SELECT * FROM fills WHERE market_id IN ({lst}) "
               f"AND timestamp >= '{mo}' AND timestamp < '{nxt}') ORDER BY market_id, timestamp")
        fetch(p, sql, m, kind="fills", venue=v, month=f"{mo:%Y-%m}", links_key=key)
        STATE["done"] += 1


def stage_times(year):
    """[(event_key, label, cutoff naive UTC)] of every weekend already raced, from weekend_sweep's schedule."""
    sys.path.insert(0, str(ROOT))
    import pandas as pd
    from racinglines.pipelines import weekend_sweep as W
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    return [(w["event_key"], lab, pd.Timestamp(t)) for w in W.schedule(year).values() if w["race_start"] < now
            for lab, t in w["stages"]]


def run_stages(venues, year):
    st = stage_times(year)
    by_ev = {}
    for ev, lab, t in st:
        by_ev.setdefault(ev, []).append((lab, t))
    jobs = []
    for v in venues:
        m, key = market_map(v)
        for ev, stages in by_ev.items():
            stages = [(lab, t) for lab, t in stages if t.date() >= BOOKS_FROM[v]]
            p = OUT / "stages" / f"{ev}_{VENUES[v]}.parquet"
            if stages and not current(p, key):
                jobs.append((v, m, key, ev, stages, p))
    STATE["total"] = len(jobs)
    for v, m, key, ev, stages, p in jobs:
        STATE["item"] = p.name
        def sql(lst, stages=stages):
            # argMax per market and outcome keeps one book per group in memory; sorting every snapshot of the
            # 48 hours (ORDER BY ... LIMIT 1 BY) passed the server's 11 GiB query limit on 2026-10-13
            parts = []
            for lab, t in stages:
                lo = t - timedelta(hours=LOOKBACK_H)
                parts.append(
                    f"SELECT '{lab}' AS stage, toDateTime64('{t}', 6, 'UTC') AS cutoff, toString(market_id) AS mkt, "
                    f"any(market_platform_id) AS market_platform_id, any(toString(platform)) AS platform, "
                    f"outcome.platform_id AS outcome_pid, any(outcome.name) AS outcome_name, "
                    f"max(timestamp) AS snap_ts, argMax(toString(continuity), timestamp) AS continuity, "
                    f"argMax(toString(state), timestamp) AS state, argMax(bids, timestamp) AS b, "
                    f"argMax(asks, timestamp) AS a, length(b) AS n_bids, length(a) AS n_asks, "
                    f"arrayMap(x -> toFloat64(x.price), b) AS bid_px, arrayMap(x -> toFloat64(x.size), b) AS bid_sz, "
                    f"arrayMap(x -> toFloat64(x.price), a) AS ask_px, arrayMap(x -> toFloat64(x.size), a) AS ask_sz "
                    f"FROM orderbook_snapshots WHERE market_id IN ({lst}) AND timestamp > '{lo}' AND timestamp <= '{t}' "
                    f"GROUP BY market_id, outcome.platform_id")
            return ("SELECT stage, cutoff, mkt AS market_id, market_platform_id, platform, outcome_pid, outcome_name, "
                    "snap_ts AS timestamp, continuity, state, n_bids, n_asks, bid_px, bid_sz, ask_px, ask_sz FROM ("
                    + " UNION ALL ".join(parts) + ")")
        fetch(p, sql, m, size=CHUNK // len(stages), kind="stages", venue=v, event=ev,
              stages=[lab for lab, _ in stages], lookback_h=LOOKBACK_H, links_key=key)
        STATE["done"] += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", choices=["books", "fills", "stages"])
    ap.add_argument("--venue", choices=["kalshi", "polymarket", "both"], default="both")
    ap.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2025, 6, 1))
    ap.add_argument("--to", dest="end", type=date.fromisoformat, default=date.today())
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--to-bucket", default=BUCKET["to"], help="gs:// prefix: upload each file, then delete it here")
    ap.add_argument("--keep-local", action="store_true", help="with --to-bucket: keep the local copies")
    a = ap.parse_args()
    BUCKET.update(to=a.to_bucket.rstrip("/"), keep_local=a.keep_local)
    if BUCKET["to"] and not BUCKET["to"].startswith("gs://"):
        ap.error("--to-bucket takes a gs:// prefix")
    venues = list(VENUES) if a.venue == "both" else [a.venue]
    threading.Thread(target=heartbeat, daemon=True).start()
    log(f"probalytics_pull {a.what} {venues} -> {OUT}" + (f" -> {BUCKET['to']}" if BUCKET["to"] else ""))
    {"books": lambda: run_books(venues, a.start, a.end), "fills": lambda: run_fills(venues, a.start, a.end),
     "stages": lambda: run_stages(venues, a.year)}[a.what]()
    log(f"done: {STATE['done']} of {STATE['total']} files in {(time.time() - T0) / 60:.0f} min")


if __name__ == "__main__":
    main()
