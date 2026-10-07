"""Walk-forward scoring of the contenders (algos.py) on a results frame, per sport.

    python -m racinglines.research.algo_abc.evaluate --data results.csv --out DIR [--sports nascar] [--from 2025]

Every race of every sport is fed to every model in date order; races dated `--from` (default 2025) or later are also
scored, each priced from races on earlier dates only (all races of a date are priced before any of them updates a
model). Writes DIR/races.csv (one row per sport x race x model: the metric sums and counts), DIR/summary.csv and
DIR/tables.md (per sport: each model's metrics with race-bootstrap 95% CIs, and its paired difference from A).

Metrics (lower is better but accuracy):
    win_ll     -log P(actual winner)                       (categorical log loss, one per race)
    win_bll    binary log loss of "wins" over every entrant (the repo's calibration.py race_win log loss)
    top3_brier, top10_brier  Brier over every entrant of "classified in the top 3 / 10"
    h2h_ll     -log P(i ahead of j) over every pair of classified finishers, i the one ahead
    h2h_acc    share of those pairs the model called right (P > 0.5; exactly 0.5 counts half)
Probabilities are clipped to [1e-4, 1 - 1e-4] before a log (racinglines/core/calibration.py EPS).
"""

import argparse
import sys
import time
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

from racinglines.research.algo_abc import algos as AL
from racinglines.research.algo_abc import data as D

EPS = 1e-4
METRICS = ["win_ll", "win_bll", "top3_brier", "top10_brier", "h2h_ll", "h2h_acc"]
LOWER_BETTER = {m: m != "h2h_acc" for m in METRICS}
MODELS = ["repo_form", "global", "pl", "wl_pl", "wl_pl_c", "elo", "avg_finish", "uniform"]
REF = "repo_form"


def race_metrics(pred, race):
    """{metric: (sum, count)} for one priced race."""
    ids = np.asarray(race["ids"])
    order = pd.Index(pred.ids.astype(int)).get_indexer(ids.astype(int))
    if (order < 0).any():
        raise ValueError("a prediction is missing an entrant")
    win, t3, t10, h = pred.win[order], pred.top3[order], pred.top10[order], pred.h2h[np.ix_(order, order)]
    n, f = len(ids), race["n_fin"]
    pos = np.arange(n)
    fin = pos < f
    out = {}
    if f >= 1:
        y = (pos == 0).astype(float)
        q = np.clip(win, EPS, 1 - EPS)
        out["win_ll"] = (-np.log(q[0]), 1)
        out["win_bll"] = (float(-(y * np.log(q) + (1 - y) * np.log(1 - q)).sum()), n)
    out["top3_brier"] = (float(((t3 - (fin & (pos < 3))) ** 2).sum()), n)
    out["top10_brier"] = (float(((t10 - (fin & (pos < 10))) ** 2).sum()), n)
    if f >= 2:
        iu = np.triu_indices(f, 1)                       # i < j among finishers: i finished ahead of j
        p = h[:f, :f][iu]
        out["h2h_ll"] = (float(-np.log(np.clip(p, EPS, 1 - EPS)).sum()), len(p))
        out["h2h_acc"] = (float((p > 0.5).sum() + 0.5 * (p == 0.5).sum()), len(p))
    return out


def walk(frame, sport, models, score_from, seed=7, echo=print):
    """Rows of race metrics for one sport (see the module doc)."""
    races = D.races(frame[frame["sport"] == sport])
    objs = {m: AL.ALL[m]() for m in models}
    rows = []
    by_date = {}
    for r in races:
        by_date.setdefault(r["date"], []).append(r)
    dates = sorted(by_date)
    scored_total = sum(len(by_date[d]) for d in dates if d.year >= score_from)
    t0, last, done = time.monotonic(), time.monotonic(), 0
    for d in dates:
        day = by_date[d]
        if d.year >= score_from:
            for r in day:
                if r["n_fin"] < 2:
                    continue
                for m, obj in objs.items():
                    rng = np.random.default_rng([seed, r["race_id"], models.index(m)])
                    met = race_metrics(obj.predict(r, rng), r)
                    for k, (s, c) in met.items():
                        rows.append(dict(sport=sport, race_id=r["race_id"], date=r["date"].date().isoformat(),
                                         n=len(r["ids"]), n_fin=r["n_fin"], model=m, metric=k, sum=s, count=c))
                done += 1
                now = time.monotonic()
                if now - last >= 60:
                    echo(f"progress algo-abc {sport}: {(now - t0) / 60:.1f} min elapsed · race {done} of "
                         f"{scored_total} ({r['date'].date()})")
                    last = now
        for r in day:
            for obj in objs.values():
                obj.update(r)
    echo(f"{sport}: scored {done} races in {(time.monotonic() - t0) / 60:.1f} min")
    return pd.DataFrame(rows)


def summarize(rows, n_boot=2000, seed=11, ref=REF):
    """Per sport x model x metric: the value over all scored races, a race-bootstrap 95% CI, and the paired
    difference from `ref` with its CI (the same resampled races for every model)."""
    out = []
    for (sport, metric), g in rows.groupby(["sport", "metric"]):
        s = g.pivot_table(index="race_id", columns="model", values="sum", aggfunc="sum")
        c = g.pivot_table(index="race_id", columns="model", values="count", aggfunc="sum")
        races = s.index.to_numpy()
        rng = np.random.default_rng([seed, zlib.crc32(sport.encode()), METRICS.index(metric)])
        idx = rng.integers(0, len(races), (n_boot, len(races)))
        S, C = s.to_numpy(), c.to_numpy()
        boot = S[idx].sum(1) / C[idx].sum(1)                     # (n_boot, models)
        point = S.sum(0) / C.sum(0)
        cols = list(s.columns)
        j = cols.index(ref) if ref in cols else None
        for k, m in enumerate(cols):
            row = dict(sport=sport, metric=metric, model=m, races=len(races), n=int(C[:, k].sum()),
                       value=point[k], lo=np.percentile(boot[:, k], 2.5), hi=np.percentile(boot[:, k], 97.5))
            if j is not None:
                diff = boot[:, k] - boot[:, j]
                row.update(diff=point[k] - point[j], diff_lo=np.percentile(diff, 2.5),
                           diff_hi=np.percentile(diff, 97.5))
            out.append(row)
    return pd.DataFrame(out)


def verdict(row):
    """Against A: 'better' / 'worse' when the paired 95% CI excludes 0, else 'noise'."""
    if row["model"] == REF or pd.isna(row.get("diff_lo")):
        return "ref"
    good = (row["diff_hi"] < 0) if LOWER_BETTER[row["metric"]] else (row["diff_lo"] > 0)
    bad = (row["diff_lo"] > 0) if LOWER_BETTER[row["metric"]] else (row["diff_hi"] < 0)
    return "better" if good else "worse" if bad else "noise"


def tables(summary):
    """Markdown: per sport, models x metrics as 'value [lo, hi]', then the paired differences from A."""
    lines = []
    for sport, g in summary.groupby("sport", sort=False):
        races = int(g["races"].max())
        lines += [f"### {sport} ({races} scored races)", "",
                  "| model | " + " | ".join(METRICS) + " |", "|---|" + "---|" * len(METRICS)]
        for m in MODELS:
            cells = []
            for met in METRICS:
                r = g[(g["model"] == m) & (g["metric"] == met)]
                cells.append("–" if r.empty else f"{r['value'].iloc[0]:.4f} [{r['lo'].iloc[0]:.4f}, {r['hi'].iloc[0]:.4f}]")
            lines.append(f"| {AL.LABEL[m]} | " + " | ".join(cells) + " |")
        lines += ["", f"Paired difference from A (model minus A, 95% race-bootstrap CI; verdict vs A):", "",
                  "| model | " + " | ".join(METRICS) + " |", "|---|" + "---|" * len(METRICS)]
        for m in MODELS:
            if m == REF:
                continue
            cells = []
            for met in METRICS:
                r = g[(g["model"] == m) & (g["metric"] == met)]
                if r.empty:
                    cells.append("–")
                    continue
                r = r.iloc[0]
                cells.append(f"{r['diff']:+.4f} [{r['diff_lo']:+.4f}, {r['diff_hi']:+.4f}] {verdict(r)}")
            lines.append(f"| {AL.LABEL[m]} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="results.csv (data.COLUMNS)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sports", nargs="+", default=D.SPORTS)
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--from", dest="score_from", type=int, default=2025, help="first scored season (year)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--boot", type=int, default=2000)
    args = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(line_buffering=True)
    frame = D.read_csv(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = pd.concat([walk(frame, s, args.models, args.score_from, args.seed) for s in args.sports], ignore_index=True)
    rows.to_csv(out / "races.csv", index=False)
    summ = summarize(rows, args.boot)
    summ["verdict"] = summ.apply(verdict, axis=1)
    summ.to_csv(out / "summary.csv", index=False)
    (out / "tables.md").write_text(tables(summ))
    print(tables(summ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
