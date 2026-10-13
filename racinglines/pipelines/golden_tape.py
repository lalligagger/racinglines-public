"""The golden check on a second tape (owner, 2026-10-13: "re-run our golden test sweep vs. prob, make sure results match
within some thresholds"). Two parts, both on the weekends asked for:

1. Tapes: every Polymarket token linked to each weekend's race, our stored prices against the second tape's, one
   last price per token and BUCKET, over the window the sweep downloads (first stage - 36 h to the race + 3 h). Pass:
   within MID_TOL on at least MID_SHARE of the buckets both tapes have.
2. Golden sweep: the golden jobs of the defaults queue (sweeps/defaults-2026-10.toml, the "golden:" jobs: profile A) at
   each seed, run twice with weekend_sweep.run_sweep: on our tape, then with RACINGLINES_TAPE pointing at the second
   tape (markets/store.py: every read goes to that tree only). Same model runs, settings and seeds. Pass per weekend:
   the update taker's P&L within PNL_REL or PNL_ABS dollars (the larger), and its trade count within TRADES_REL.

The marks are the owner's proposed defaults (thread "order book tools", 2026-10-13). Nothing here writes to a
database; the sweep runs with fetch off, so neither side downloads anything."""
import contextlib
import math
import os
import tomllib
from datetime import timedelta
from pathlib import Path

import pandas as pd

from racinglines.markets import store as MS

QUEUE = Path(__file__).resolve().parents[2] / "sweeps" / "defaults-2026-10.toml"
BUCKET = "5min"
MID_TOL = 0.01
MID_SHARE = 0.95
PNL_REL, PNL_ABS = 0.10, 5.0
TRADES_REL = 0.05
MODE = "update"                      # the taker mode the golden numbers are quoted for


def golden_settings(year, queue=QUEUE):
    """The queue's golden job for `year` as sweep settings (without its seed or bookkeeping keys)."""
    from racinglines.pipelines import search as S
    jobs = tomllib.loads(Path(queue).read_text())["job"]
    for j in jobs:
        if str(j.get("note", "")).startswith("golden") and int(j.get("year", 0)) == year:
            return {k: v for k, v in j.items() if k not in S.META and k != "seed"}
    raise ValueError(f"no golden job for {year} in {queue}")


def seeds(n):
    """The search's replicate seeds: the default, then 1, 2, ... (search.py)."""
    return [None] + list(range(1, n))


@contextlib.contextmanager
def on_tape(path):
    """Every market-data read inside goes to the tape at `path` (None: ours)."""
    old = os.environ.get(MS.TAPE)
    if path is None:
        os.environ.pop(MS.TAPE, None)
    else:
        os.environ[MS.TAPE] = str(path)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(MS.TAPE, None)
        else:
            os.environ[MS.TAPE] = old


def bucketed(prices, bucket=BUCKET):
    """One last price per token and bucket: DataFrame(token_id, bucket, price)."""
    if not len(prices):
        return pd.DataFrame(columns=["token_id", "bucket", "price"])
    p = prices[["token_id", "ts", "price"]].dropna().copy()
    p["bucket"] = pd.to_datetime(p["ts"], utc=True).dt.floor(bucket)
    return p.sort_values("ts").groupby(["token_id", "bucket"], as_index=False)["price"].last()


def compare_mids(ours, theirs, tol=MID_TOL, bucket=BUCKET):
    """dict(matched, within, share, ours_only, theirs_only, worst) over the buckets, from two prices frames."""
    a, b = bucketed(ours, bucket), bucketed(theirs, bucket)
    m = a.merge(b, on=["token_id", "bucket"], suffixes=("_ours", "_theirs"))
    d = (m["price_ours"] - m["price_theirs"]).abs()
    keys = lambda x: set(zip(x["token_id"], x["bucket"]))                       # noqa: E731
    ka, kb = keys(a), keys(b)
    return dict(matched=len(m), within=int((d <= tol + 1e-9).sum()),
                share=float((d <= tol + 1e-9).mean()) if len(m) else None,
                ours_only=len(ka - kb), theirs_only=len(kb - ka), worst=float(d.max()) if len(m) else None)


def weekend_window(w):
    """The window run_sweep's download covers for weekend `w` (weekend_sweep.fetch_market_data), UTC."""
    return ((w["stages"][0][1] - timedelta(hours=36)).tz_localize("UTC"),
            (w["race_start"] + timedelta(hours=3)).tz_localize("UTC"))


def tape_rows(conn, sched, tape, echo=print):
    """compare_mids per weekend: [dict(event_key, event, tokens, ...)]."""
    from racinglines.pipelines import weekend_sweep as SW
    rows = []
    for rnd, w in sched.items():
        rid = SW._race_id(conn, w["event_key"])
        links = SW._links(conn, rid, "polymarket") if rid is not None else pd.DataFrame(columns=["token_id"])
        toks = links["token_id"].dropna().astype(str).unique().tolist()
        a, b = weekend_window(w)
        with on_tape(None):
            ours = MS.read(conn, "prices", tokens=toks, start=a, end=b)
        with on_tape(tape):
            theirs = MS.read(None, "prices", tokens=toks, start=a, end=b)
        r = dict(round=rnd, event_key=w["event_key"], event=w["name"], tokens=len(toks), **compare_mids(ours, theirs))
        r["pass"] = r["share"] is not None and r["share"] >= MID_SHARE
        echo(f"progress tapes {w['event_key']}: {r['within']}/{r['matched']} buckets within {MID_TOL:.2f}")
        rows.append(r)
    return pd.DataFrame(rows)


def within(ours, theirs, rel, floor=0.0):
    """|ours - theirs| <= max(rel * |ours|, floor)."""
    if ours is None or theirs is None or (isinstance(ours, float) and math.isnan(ours)):
        return ours is None and theirs is None
    return abs(ours - theirs) <= max(rel * abs(ours), floor) + 1e-9


def compare_weekends(ours, theirs, mode=MODE):
    """Per weekend (weekends frames of run_sweep): P&L and trade counts of `mode` on both tapes, and the pass marks."""
    cols = ["event_key", "event", f"{mode}_pnl", f"{mode}_trades"]
    a = ours.reindex(columns=cols)
    b = theirs.reindex(columns=["event_key", f"{mode}_pnl", f"{mode}_trades"])
    m = a.merge(b, on="event_key", how="outer", suffixes=("_ours", "_theirs"))
    m = m.rename(columns={f"{mode}_pnl_ours": "pnl_ours", f"{mode}_pnl_theirs": "pnl_theirs",
                          f"{mode}_trades_ours": "trades_ours", f"{mode}_trades_theirs": "trades_theirs"})
    num = lambda v: None if pd.isna(v) else float(v)                               # noqa: E731
    m["pnl_ok"] = [within(num(x), num(y), PNL_REL, PNL_ABS) for x, y in zip(m["pnl_ours"], m["pnl_theirs"])]
    m["trades_ok"] = [within(num(x), num(y), TRADES_REL) for x, y in zip(m["trades_ours"], m["trades_theirs"])]
    m["pass"] = m["pnl_ok"] & m["trades_ok"]
    return m


def golden(engine, engine_url, year, rounds, tape, n_seeds=3, echo=print):
    """The golden job for `year` at each seed on both tapes: DataFrame(seed, event_key, ..., pass)."""
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.pipelines import weekend_sweep as SW
    base = golden_settings(year)
    out = []
    for s in seeds(n_seeds):
        st = SS.Settings.from_dict(dict(base, **({} if s is None else dict(seed=s))))
        runs = {}
        for side, path in (("ours", None), ("theirs", tape)):
            echo(f"progress golden seed {'default' if s is None else s}: {side} tape")
            with on_tape(path):
                runs[side] = SW.run_sweep(engine, engine_url, year, rounds, fetch=False, settings=st, echo=echo)
        out.append(compare_weekends(runs["ours"]["weekends"], runs["theirs"]["weekends"]).assign(
            seed="default" if s is None else s))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _md(df, cols, fmt=None):
    fmt = fmt or {}
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df[cols].itertuples(index=False):
        lines.append("| " + " | ".join("" if pd.isna(v) else fmt[c](v) if c in fmt else str(v)
                                       for c, v in zip(cols, r)) + " |")
    return "\n".join(lines)


def report(tapes, gold, tape, year, rounds):
    """REPORT.md text: the verdict first, then both tables and what the check doesn't cover."""
    t_ok = bool(len(tapes)) and bool(tapes["pass"].all())
    g_ok = bool(len(gold)) and bool(gold["pass"].all())
    money = lambda v: f"{v:+.2f}"                                                   # noqa: E731
    pct = lambda v: f"{100 * v:.1f}%"                                               # noqa: E731
    lines = [f"# Golden check: our tape vs {tape}", "",
             f"Season {year}, rounds {', '.join(map(str, rounds)) if rounds else 'all raced'}; "
             f"the golden jobs of {QUEUE.name} at {gold['seed'].nunique() if len(gold) else 0} seeds, taker mode {MODE}.",
             "", "## Verdict", "",
             f"- Tapes: **{'PASS' if t_ok else 'FAIL'}** ({int(tapes['pass'].sum()) if len(tapes) else 0} of "
             f"{len(tapes)} weekends with mids within {MID_TOL * 100:.0f}c on {MID_SHARE:.0%} of matched buckets)",
             f"- Golden sweep: **{'PASS' if g_ok else 'FAIL'}** ({int(gold['pass'].sum()) if len(gold) else 0} of "
             f"{len(gold)} weekend-seeds with P&L within {PNL_REL:.0%} or ${PNL_ABS:.0f} and trades within "
             f"{TRADES_REL:.0%})", "", "## Tapes", ""]
    if len(tapes):
        lines.append(_md(tapes, ["event_key", "event", "tokens", "matched", "within", "share", "ours_only",
                                 "theirs_only", "worst", "pass"],
                         dict(share=lambda v: pct(v), worst=lambda v: f"{v:.3f}")))
    lines += ["", "## Golden sweep, per weekend and seed", ""]
    if len(gold):
        lines.append(_md(gold, ["seed", "event_key", "event", "pnl_ours", "pnl_theirs", "trades_ours", "trades_theirs",
                                "pass"], dict(pnl_ours=money, pnl_theirs=money)))
        tot = gold.groupby("seed")[["pnl_ours", "pnl_theirs", "trades_ours", "trades_theirs"]].sum().reset_index()
        lines += ["", "Season totals per seed:", "",
                  _md(tot, ["seed", "pnl_ours", "pnl_theirs", "trades_ours", "trades_theirs"],
                      dict(pnl_ours=money, pnl_theirs=money))]
    lines += ["", "## What this does and doesn't show", "",
              "- Fills in the golden sweep are at the stored price at each stage plus cost and fee, not book walks, so "
              "the sweep part tests the prices and trade tape, not queue position or depth.",
              "- Polymarket only (the golden queue's venue). Kalshi books are not compared here.",
              "- A weekend with no matched buckets fails the tape mark; read ours_only / theirs_only for which side "
              "lacks it."]
    return "\n".join(lines) + "\n"


def run(engine, engine_url, tape, year=2026, rounds=None, n_seeds=3, out=None, echo=print):
    """Both parts, written to `out` (default data/runs/golden-tape/<tape folder name>-<year>/): REPORT.md, tapes.csv,
    golden.csv. Returns (tapes, golden, out)."""
    from racinglines import paths
    from racinglines.pipelines import weekend_sweep as SW
    tape = Path(tape)
    if not tape.is_dir():
        raise ValueError(f"no tape at {tape}")
    sched = SW.schedule(year, rounds)
    out = Path(out) if out else paths.runs("golden-tape", f"{tape.name}-{year}")
    out.mkdir(parents=True, exist_ok=True)
    with engine.connect() as c:
        tapes = tape_rows(c, sched, tape, echo)
    tapes.to_csv(out / "tapes.csv", index=False)
    gold = golden(engine, engine_url, year, rounds, tape, n_seeds, echo)
    gold.to_csv(out / "golden.csv", index=False)
    (out / "REPORT.md").write_text(report(tapes, gold, tape.name, year, rounds))
    return tapes, gold, out
