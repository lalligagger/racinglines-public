"""
The analysis of a finished search (racinglines/pipelines/search.py), with the checks the params-4h
search showed a backtest needs (docs/backtest-core.md, Part 1):

  - held-out rule: a combo is labelled against the baseline in the target season AND the held-out ones,
    beyond a noise floor: robust / target only / held-out-led / not better;
  - noise floor: the spread of seed replicates (jobs that differ only in `seed`) where the search ran
    them, else the configured floor per strategy family;
  - baselines at the same fidelity: each run is compared with the default settings at its own
    simulation count, over the same rounds;
  - confirmation: the same combo at `confirm_sims` simulations, when the search ran it;
  - concentration: P&L without the best event, and which event that was;
  - stable candidate ids: `<strategy>-<settings_key>`, never a position in a list;
  - finished jobs only: a job still running (or failed) is never read.

    racinglines f1 search-report sweeps/params-4h.toml

Configuration: an optional [report] table in the queue file (defaults below). Outputs, next to the
search's state.json: stats.csv, ranking.csv, pnl_curves.json, candidates/<id>.json, candidates.toml,
report.md.
"""

import csv
import json
import math

import pandas as pd

from racinglines.pipelines import sweep_settings as SS

DEFAULTS = dict(target=2026, holdout=[2025], confirm_sims=16000, top=25, season_events=24,
                noise=dict(taker=150.0, maker=350.0))


def family(strategy):
    return "maker" if strategy.startswith("maker") else "taker"


def curve_stats(pnls, season_events):
    """Total, weekends up, max drawdown (peak to trough from 0 before the first event), Sharpe (mean / sd of
    event P&L x sqrt(events per season)), and the total without the best event."""
    cum, peak, dd, c = [], 0.0, 0.0, 0.0
    for x in pnls:
        c += x
        cum.append(c)
        peak = max(peak, c)
        dd = max(dd, peak - c)
    n = len(pnls)
    mean = c / n if n else 0.0
    sd = math.sqrt(sum((x - mean) ** 2 for x in pnls) / (n - 1)) if n > 1 else 0.0
    best = max(range(n), key=lambda i: pnls[i]) if n else None
    return dict(pnl=c, weekends=n, weekends_up=sum(x > 0 for x in pnls), max_drawdown=dd,
                sharpe=(mean / sd * math.sqrt(season_events)) if sd > 0 else 0.0, mean_weekend=mean,
                sd_weekend=sd, pnl_without_best=c - pnls[best] if n else 0.0, best_index=best), cum


def _config(cfg):
    out = dict(DEFAULTS, **(cfg or {}))
    out["noise"] = dict(DEFAULTS["noise"], **(cfg or {}).get("noise", {}))
    return out


def _without(st, *names):
    return {k: v for k, v in st.items() if k not in names}


def stats(jobs, metrics, strategies, cfg=None):
    """jobs: finished sweep jobs (state.json values: year, rounds, settings, run_id, id, note).
    metrics: {run_id: the saved sweep's metrics}. strategies: [(key, label)].
    Returns (stats rows, curves): one row per job x strategy."""
    cfg = _config(cfg)
    rows, curves = [], []
    for j in jobs:
        m = metrics.get(j["run_id"])
        if not m:
            continue
        st = SS.Settings.from_dict(j["settings"])
        wk = sorted(m.get("weekends") or [], key=lambda w: w["round"])
        for key, label in strategies:
            pn = [float(w.get(f"{key}_pnl") or 0.0) for w in wk]
            s, cum = curve_stats(pn, cfg["season_events"])
            bi = s.pop("best_index")
            rec = dict(job=j["id"], run_id=j["run_id"], year=j["year"], rounds=j.get("rounds"), settings_key=st.key,
                       combo=SS.Settings.from_dict(_without(st, "seed")).key, sims=st["sims"], seed=st["seed"], label=st.label(), strategy=key, strategy_label=label,
                       note=j.get("note", ""), best_event=wk[bi]["event"] if bi is not None else None, **s)
            rows.append(rec)
            curves.append(dict(rec, rounds_list=[w["round"] for w in wk], events=[w["event"] for w in wk],
                               weekend_pnl=pn, cumulative=cum, settings=st.to_json()))
    # each run against the default settings at its own fidelity, seed and rounds
    base = {}
    for r, c in zip(rows, curves):
        if SS.Settings.from_dict(_without(c["settings"], "sims", "seed")).key == SS.Settings.from_dict().key:
            base[(r["year"], r["rounds"], r["sims"], r["seed"], r["strategy"])] = r
    for r in rows:
        b = base.get((r["year"], r["rounds"], r["sims"], r["seed"], r["strategy"]))
        r["vs_baseline"] = r["pnl"] - b["pnl"] if b and b is not r else (0.0 if b is r else None)
    for c, r in zip(curves, rows):
        c["vs_baseline"] = r["vs_baseline"]
    return rows, curves


def noise_floor(rows, cfg=None):
    """{family: floor}: the largest sd of P&L across seed replicates (>= 3 seeds of the same combo, same
    season and fidelity) where the search ran them; the configured floor otherwise."""
    cfg = _config(cfg)
    reps = {}
    for r in rows:
        if r["rounds"]:
            continue
        st_key = (r["year"], r["sims"], r["strategy"], r["combo"])
        reps.setdefault(st_key, {})[r["seed"]] = r["pnl"]
    floor = dict(cfg["noise"])
    measured = {}
    for (_, _, strat, _), by_seed in reps.items():
        v = list(by_seed.values())
        if len(v) >= 3:
            m = sum(v) / len(v)
            sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
            measured[family(strat)] = max(measured.get(family(strat), 0.0), sd)
    floor.update(measured)
    return floor, measured


def rank(rows, curves, cfg=None, twin=None):
    """One row per target-season combo x strategy at the default fidelity, with its held-out twin(s),
    label, confirmation and score. twin(settings, year) -> settings the held-out season runs the same
    model with (e.g. a switch that's inert that season dropped); None = the same settings."""
    cfg = _config(cfg)
    settings = {c["settings_key"]: SS.Settings.from_dict(c["settings"]) for c in curves}
    floor, measured = noise_floor(rows, cfg)
    full = [r for r in rows if not r["rounds"]]
    by = {}
    for r in full:
        by.setdefault((r["year"], r["combo"], r["strategy"]), []).append(r)     # seed replicates group together

    def mean_of(rs, k):
        v = [r[k] for r in rs if r.get(k) is not None]
        return sum(v) / len(v) if v else None

    def lookup(year, st, strat):
        key = SS.Settings.from_dict(_without(st, "seed")).key
        return by.get((year, key, strat))

    default_sims = SS.BY_NAME["sims"].default
    out = []
    for (year, combo, strat), rs in by.items():
        st = settings[rs[0]["settings_key"]]
        if year != cfg["target"] or st["sims"] != default_sims:
            continue
        nf = floor[family(strat)]
        d_t = mean_of(rs, "vs_baseline")
        held = {}
        for hy in cfg["holdout"]:
            st_h = twin(st, hy) if twin else st
            held[hy] = lookup(hy, st_h, strat) or lookup(hy, st, strat)
        d_h = {hy: mean_of(h, "vs_baseline") if h else None for hy, h in held.items()}
        if SS.Settings.from_dict(_without(st, "seed")).key == SS.Settings.from_dict().key:
            label = "baseline"
        elif any(v is None for v in d_h.values()):
            label = "no held-out run"
        elif d_t > nf and all(v > nf for v in d_h.values()):
            label = "robust"
        elif d_t > nf:
            label = "target only"
        elif all(v > nf for v in d_h.values()) and d_t > -nf:
            label = "held-out-led"
        else:
            label = "not better"
        # confirmation at higher fidelity, in every season the label rests on
        conf = {}
        for yy, s_ in [(year, st)] + [(hy, twin(st, hy) if twin else st) for hy in cfg["holdout"]]:
            c = lookup(yy, dict(s_, sims=cfg["confirm_sims"]), strat) or lookup(yy, dict(st, sims=cfg["confirm_sims"]), strat)
            conf[yy] = mean_of(c, "vs_baseline") if c else None
        if label in ("robust", "target only", "held-out-led"):
            need = {"robust": list(conf), "target only": [year], "held-out-led": cfg["holdout"]}[label]
            confirmed = "not run" if any(conf[y] is None for y in need) else \
                ("yes" if all(conf[y] > 0 for y in need) else "no")
        else:
            confirmed = ""
        pnl_t = mean_of(rs, "pnl")
        pnl_h = {hy: mean_of(h, "pnl") if h else None for hy, h in held.items()}
        score = pnl_t + sum(min(0.0, v) for v in pnl_h.values() if v is not None) \
            if all(v is not None for v in pnl_h.values()) else pnl_t - 1e6
        # better than the baseline isn't the same as profitable (params-4h: hold strategies beat a losing
        # baseline in 2025 and still lost money)
        loses = [str(y) for y, v in [(year, pnl_t), *pnl_h.items()] if v is not None and v < 0]
        rec = dict(id=f"{strat}-{combo}", strategy=strat, settings_key=combo, label_settings=st.label(),
                   verdict=label, confirmed=confirmed, loses_money_in=",".join(loses), score=score, noise_floor=nf, replicates=len(rs),
                   pnl_target=pnl_t, vs_base_target=d_t, sharpe_target=mean_of(rs, "sharpe"),
                   dd_target=mean_of(rs, "max_drawdown"), without_best_target=mean_of(rs, "pnl_without_best"),
                   best_event_target=rs[0]["best_event"], settings=st.to_json(),
                   run_target=rs[0]["run_id"])
        for hy in cfg["holdout"]:
            h = held[hy] or []
            rec.update({f"pnl_{hy}": pnl_h[hy], f"vs_base_{hy}": d_h[hy], f"sharpe_{hy}": mean_of(h, "sharpe"),
                        f"dd_{hy}": mean_of(h, "max_drawdown"), f"without_best_{hy}": mean_of(h, "pnl_without_best"),
                        f"run_{hy}": h[0]["run_id"] if h else None,
                        f"settings_{hy}": settings[h[0]["settings_key"]].to_json() if h else None})
        rec.update({f"confirm_{y}": v for y, v in conf.items()})
        out.append(rec)
    out.sort(key=lambda x: -x["score"])
    return out, floor, measured


def candidates(ranking, top):
    """The top combos that have a held-out run and aren't the baseline (or a loosened guard)."""
    return [r for r in ranking if r["verdict"] not in ("baseline", "no held-out run", "not better")][:top]


def write(out, jobs, metrics, strategies, cfg=None, twin=None, rerun=None, echo=print):
    """Every output file, from finished jobs only. rerun(job-like dict) -> argv list, for re-run commands."""
    cfg = _config(cfg)
    rows, curves = stats(jobs, metrics, strategies, cfg)
    ranking, floor, measured = rank(rows, curves, cfg, twin)
    (out / "pnl_curves.json").write_text(json.dumps(curves, default=str))
    cols = ["year", "rounds", "strategy", "label", "sims", "seed", "pnl", "vs_baseline", "weekends_up", "weekends",
            "max_drawdown", "sharpe", "pnl_without_best", "best_event", "run_id", "job", "settings_key", "note"]
    _csv(out / "stats.csv", sorted(rows, key=lambda r: (r["year"], r["strategy"], -r["pnl"])), cols)
    rcols = [c for c in ranking[0] if not c.startswith("settings")] if ranking else []
    _csv(out / "ranking.csv", ranking, rcols)
    cdir = out / "candidates"
    cdir.mkdir(exist_ok=True)
    for f in cdir.glob("*.json"):
        f.unlink()
    toml = ["# Top combos of this search as [[candidate]] entries (racinglines f1 search-report).", ""]
    top = candidates(ranking, cfg["top"])
    for i, r in enumerate(top, 1):
        st = SS.Settings.from_dict(r["settings"])
        doc = dict(r, rank=i, name=f"{r['strategy']} · {st.label()}", changed=st.changed())
        if rerun:
            doc["rerun"] = {str(cfg["target"]): " ".join(rerun(dict(kind="sweep", year=cfg["target"], settings=r["settings"])))}
            for hy in cfg["holdout"]:
                if r.get(f"settings_{hy}"):
                    doc["rerun"][str(hy)] = " ".join(rerun(dict(kind="sweep", year=hy, settings=r[f"settings_{hy}"])))
        (cdir / f"{r['id']}.json").write_text(json.dumps(doc, indent=1, default=str) + "\n")
        why = (f"{r['verdict']}: {cfg['target']} {r['pnl_target']:+,.0f} ({r['vs_base_target']:+,.0f} vs baseline); "
               + "; ".join(f"{hy} {r[f'pnl_{hy}']:+,.0f} ({r[f'vs_base_{hy}']:+,.0f})" for hy in cfg["holdout"]))
        toml += ["[[candidate]]", f'name = "{r["id"]}: {r["strategy"]} · {st.label()}"', f"year = {cfg['target']}",
                 f'strategy = "{r["strategy"]}"', f'why = "{why}"']
        for k, v in st.to_json().items():
            if k == "variant" or st[k] != SS.BY_NAME[k].default:
                toml.append(f"{k} = " + (f'"{",".join(v)}"' if isinstance(v, list) else json.dumps(v)))
        toml.append("")
    (out / "candidates.toml").write_text("\n".join(toml))
    (out / "report.md").write_text(summary_md(ranking, top, floor, measured, cfg))
    echo(f"search-report: {len(rows)} run x strategy rows, {len(ranking)} combos, {len(top)} candidates -> {out}")
    return rows, ranking


def summary_md(ranking, top, floor, measured, cfg):
    hy = cfg["holdout"]
    lines = ["# Search report", "",
             f"Target season {cfg['target']}, held out: {', '.join(map(str, hy))}. Noise floor per strategy family: "
             + ", ".join(f"{k} ±{v:,.0f}" + (" (seed replicates)" if k in measured else " (configured)")
                         for k, v in floor.items()) + ".", "",
             "Labels: **robust** beats the baseline by more than the noise floor in every season; **target only** "
             "in the target season only; **held-out-led** in the held-out seasons, with the target within noise. "
             "*Confirmed* re-checks the label's seasons at " f"{cfg['confirm_sims']:,} simulations. "
             "*Without best* is the target-season P&L without its best event. *Loses money in*: better than the "
             "baseline there, but still a loss.", "",
             "| Id | Strategy | Settings | Label | Confirmed | " + f"{cfg['target']} | Without best | "
             + " | ".join(str(y) for y in hy) + " | Loses money in |",
             "|---" * (8 + len(hy)) + "|"]
    for r in top:
        lines.append(f"| `{r['id']}` | {r['strategy']} | {r['label_settings']} | {r['verdict']} | {r['confirmed']} | "
                     f"{r['pnl_target']:+,.0f} | {r['without_best_target']:+,.0f} ({r['best_event_target']}) | "
                     + " | ".join(f"{r[f'pnl_{y}']:+,.0f}" for y in hy) + f" | {r['loses_money_in']} |")
    counts = pd.Series([r["verdict"] for r in ranking]).value_counts().to_dict() if ranking else {}
    lines += ["", "Combos by label: " + ", ".join(f"{k} {v}" for k, v in counts.items()), ""]
    return "\n".join(lines)


def _csv(path, rows, cols):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 2) if isinstance(r.get(k), float) else r.get(k)) for k in cols})


def run(queue_path, echo=print):
    """Load the search's finished sweep jobs and their saved runs, and write every output."""
    import tomllib

    from sqlalchemy import text

    from racinglines import paths
    from racinglines.db.config import get_engine
    from racinglines.models.position_sim import evaluate as EV
    from racinglines.models.position_sim import variants as V
    from racinglines.pipelines import search as S
    cfg, _, _ = S.load(queue_path)
    rep = tomllib.loads(open(queue_path).read()).get("report", {})
    out = paths.runs("search", cfg["name"])
    state = json.loads((out / "state.json").read_text())
    jobs = [v for v in state.values() if v.get("status") == "done" and v.get("run_id") and v["kind"] == "sweep"]
    with get_engine().connect() as c:
        rows = c.execute(text("SELECT id, metrics FROM model_runs WHERE id = ANY(:ids)"),
                         dict(ids=[j["run_id"] for j in jobs])).fetchall()
    metrics = {r[0]: r[1] for r in rows}

    def twin(st, year):
        return SS.Settings.from_dict(dict(st, variant=V.for_season(st["variant"], year)))
    return write(out, jobs, metrics, EV.STRATEGIES, rep, twin=twin, rerun=S.argv, echo=echo)
