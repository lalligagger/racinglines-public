"""
Search: run a queue of jobs in parallel, for long unattended sessions (e.g. a Claude cloud session).
The queue is a TOML file (sweeps/*.toml) that is re-read whenever a slot frees, so an agent can add,
reorder or drop pending jobs while the search runs; running and finished jobs are never touched.
After every finished job the leaderboard and a results export are rewritten.

    [search]
    name = "overnight-2026"      # output: data/runs/search/<name>/
    parallel = 3                 # jobs at once (one core each; leave one for the database)
    hours = 1.0                  # no new job starts after this; running ones are stopped at hours + grace
    grace_minutes = 10

    [[job]]                      # a season sweep (kind = "sweep", the default): every raced weekend
    year = 2026
    variant = "gridq+pretrain"   # any setting of racinglines/pipelines/sweep_settings.py; the rest default
    half_life_days = 90
    taker_stages = "pre-weekend,after FP1,after FP2"
    note = "why this job"        # shown on the leaderboard

    [[job]]                      # championship markets entered at fixed points and held
    kind = "checkpoints"
    year = 2026
    variants = "baseline,gridq+pretrain+reset"
    entries = "0,3,6"

    [[job]]                      # championship markets, rebalanced after every race
    kind = "season_strategy"
    year = 2026
    variant = "pretrain"

    [[job]]                      # a downhill walk-forward (model-only: calibration per market kind)
    sport = "mtb_dh"             # the sport's own settings (racinglines/models/timed_runs/settings.py)
    year = 2025
    half_life_days = 120
    replicates = 3               # any job: the same job at this many seeds (the default seed, 1, 2, ...);
                                 # the season's baseline gets as many, and the search report measures
                                 # its noise floor from them

    [[candidate]]                # a combo worth loading into the Lab (becomes a Lab candidate on import)
    name = "..."
    year = 2026
    strategy = "maker"           # a strategy key of the Edge Finder (update, hold, last, early, maker, ...)
    why = "..."
    variant = "..."              # + any settings, as in [[job]]

The default-settings baseline (sweep or walk-forward) of every sport and season searched is added
automatically (it runs first),
so every comparison is against a baseline priced from exactly the same data. A job's id covers its
kind, season, rounds and every setting, so the same job never runs twice. Outputs, in
data/runs/search/<name>/: state.json, leaderboard.md, results.json (for `racinglines f1
search-import`), logs/<id>.log.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timedelta, timezone

from racinglines import paths
from racinglines.pipelines import sweep_settings as SS

KINDS = {"f1": ("sweep", "checkpoints", "season_strategy"), "mtb_dh": ("walk_forward",)}
SEASON_KINDS = ("sweep", "walk_forward")          # a season-long run with a default-settings baseline
META = {"kind", "year", "rounds", "note", "id", "variants", "entries", "window", "sport", "replicates"}
SAVED = {"sweep": "Saved sweep run", "checkpoints": "Saved season checkpoints run",
         "season_strategy": "Saved season strategy run", "walk_forward": "Saved walk-forward run"}


def settings_class(sport="f1"):
    """The sport's settings schema (F1: the sweep's; others: their pricing model's)."""
    if sport == "f1":
        return SS.Settings
    from racinglines.models import race_model as RM
    try:
        return RM.model_class(sport).Settings
    except ValueError:
        _unknown_sport(sport)


def _unknown_sport(sport):
    raise ValueError(f"unknown sport {sport!r}: no pricing model (sports/<code>.toml [sport] pricing_model)")


def kinds_for(sport):
    """Job kinds a sport's queue entries may have: F1's sweeps and season runs; any other sport with a pricing
    model, the model-only walk-forward."""
    if sport in KINDS:
        return KINDS[sport]
    settings_class(sport)                      # raises for a sport without a pricing model
    return ("walk_forward",)


def _settings(j):
    cls = settings_class(j.get("sport", "f1"))
    extra = [k for k in j if k not in META and k not in cls.BY]
    if extra:
        raise ValueError(f"job {j.get('note', j)}: unknown keys {extra}")
    return cls.from_dict({k: v for k, v in j.items() if k in cls.BY})


def job_id(j):
    sport = j.get("sport", "f1")
    kind = j.get("kind", KINDS.get(sport, ("walk_forward",))[0])
    key = dict(kind=kind, year=j.get("year"), rounds=j.get("rounds"))
    if sport != "f1":                                 # F1 ids stay as they were
        key["sport"] = sport
    if kind == "checkpoints":
        key.update(variants=j.get("variants"), entries=j.get("entries"), window=j.get("window"))
    else:
        key["settings"] = _settings(j).key
    return hashlib.sha1(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()[:10]


def _replicate(j, n):
    """The job at n seeds: its own (or the default) seed, then 1, 2, ... (skipping a seed it already has)."""
    seeds = [j.get("seed")] + [s for s in range(1, n + 1) if s != j.get("seed")][:n - 1]
    return [dict(j, seed=s) if s is not None else {k: v for k, v in j.items() if k != "seed"} for s in seeds]


def load(path):
    """(config, jobs, candidates). Jobs are normalized and validated; each season's baseline sweep is
    put first."""
    cfg = tomllib.loads(open(path).read())
    s = cfg.get("search", {})
    jobs, reps = [], {}
    for j0 in cfg.get("job", []):
        j0 = dict(j0)
        sport = j0.get("sport", "f1")
        allowed = kinds_for(sport)
        j0.setdefault("kind", allowed[0])
        j0.setdefault("year", 2026)
        if j0["kind"] not in allowed:
            raise ValueError(f"unknown job kind {j0['kind']!r} for {sport}; one of {allowed}")
        n = int(j0.pop("replicates", 1) or 1)
        if n > 1:
            key = (sport, j0["year"], j0.get("rounds"))
            reps[key] = max(reps.get(key, 1), n)
        for j in _replicate(j0, n):
            if j["kind"] != "checkpoints":
                j["settings"] = _settings(j).to_json()
            j["id"] = job_id({k: v for k, v in j.items() if k != "settings"})
            if not any(x["id"] == j["id"] for x in jobs):
                jobs.append(j)
    base = []
    for sport, kind, year, rounds in dict.fromkeys((j.get("sport", "f1"), j["kind"], j["year"], j.get("rounds"))
                                                   for j in jobs if j["kind"] in SEASON_KINDS):
        b0 = dict(kind=kind, year=year, note="baseline (added automatically: same data as every job)")
        if sport != "f1":
            b0["sport"] = sport
        if rounds:
            b0["rounds"] = rounds
        for b in _replicate(b0, reps.get((sport, year, rounds), 1)):
            b["settings"] = settings_class(sport).from_dict({"seed": b["seed"]} if "seed" in b else {}).to_json()
            b["id"] = job_id({k: v for k, v in b.items() if k != "settings"})
            if not any(x["id"] == b["id"] for x in jobs):
                base.append(b)
            else:                                          # already queued: move it to the front
                jobs.insert(0, jobs.pop(next(i for i, x in enumerate(jobs) if x["id"] == b["id"])))
    cands = []
    for c in cfg.get("candidate", []):
        c = dict(c)
        sport = c.get("sport", "f1")
        cls = settings_class(sport)
        st = cls.from_dict({k: v for k, v in c.items() if k in cls.BY})
        strategy = c.get("strategy", "maker")
        cand = dict(name=c.get("name") or st.label(), year=int(c.get("year", 2026)), strategy=strategy,
                    why=c.get("why", ""), settings=st.to_json(), settings_key=st.key,
                    id=c.get("id") or f"{strategy}-{cls.from_dict(dict(st, seed=None)).key}")   # as search-report names it
        if sport != "f1":
            cand["sport"] = sport
        cands.append(cand)
    return (dict(name=s.get("name", "search"), parallel=int(s.get("parallel", 3)), hours=float(s.get("hours", 1.0)),
                 grace=float(s.get("grace_minutes", 10))), base + jobs, cands)


def argv(j):
    if j.get("sport", "f1") != "f1":
        st = settings_class(j["sport"]).from_dict(j["settings"])
        return [sys.executable, "-m", "racinglines", "backtest", "walk-forward", j["sport"], "--seasons", str(j["year"]),
                "--save"] + st.argv()
    py = [sys.executable, "-m", "racinglines", "f1"]
    if j["kind"] == "checkpoints":
        a = py + ["season-checkpoints", "--year", str(j["year"]), "--save"]
        for k in ("variants", "entries", "window"):
            if j.get(k) is not None:
                a += ["--" + k, str(j[k])]
        return a
    st = SS.Settings.from_dict(j["settings"])
    if j["kind"] == "season_strategy":
        return py + ["--variant", st["variant"], "season-strategy", "--year", str(j["year"]), "--no-fetch", "--save"]
    a = py + ["--variant", st["variant"], "sweep", "--year", str(j["year"]), "--no-fetch", "--save"]
    if j.get("rounds"):
        a += ["--rounds", str(j["rounds"])]
    return a + st.argv()


def run(path, echo=print):
    """Run the queue until it's empty or the time is up. Safe to restart: finished jobs are kept."""
    cfg, _, _ = load(path)
    out = paths.runs("search", cfg["name"])
    (out / "logs").mkdir(parents=True, exist_ok=True)
    state_f = out / "state.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {}
    for v in state.values():                       # a restart: whatever was running didn't finish
        if v["status"] == "running":
            v["status"] = "interrupted"
    t0 = datetime.now(timezone.utc)
    stop_new = t0 + timedelta(hours=cfg["hours"])
    hard_stop = stop_new + timedelta(minutes=cfg["grace"])
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")  # one core per job
    procs = {}

    def save():
        state_f.write_text(json.dumps(state, indent=1, default=str))

    while True:
        now = datetime.now(timezone.utc)
        for jid, p in list(procs.items()):         # collect finished jobs
            if p.poll() is None:
                if now > hard_stop:
                    p.terminate()
                    state[jid]["status"] = "stopped"
                    echo(f"search: stopped {jid} (time up)")
                continue
            log = (out / "logs" / f"{jid}.log").read_text(errors="ignore")
            mark = SAVED[state[jid]["kind"]]
            rid = next((int(line.split()[-1].rstrip(".")) for line in log.splitlines() if line.startswith(mark)), None)
            if state[jid]["status"] == "running":
                state[jid].update(status="done" if p.returncode == 0 and rid else "failed", run_id=rid, ended=str(now))
            del procs[jid]
            echo(f"search: {state[jid]['status']} {jid} {_title(state[jid])} run {rid}")
            save()
            write_outputs(out, state, path, echo)
        try:
            cfg, jobs, _ = load(path)              # re-read: the queue may have been edited
        except (ValueError, tomllib.TOMLDecodeError) as ex:
            echo(f"search: queue file not usable ({ex}); keeping the previous queue")
        pending = [j for j in jobs if j["id"] not in state or state[j["id"]]["status"] == "interrupted"]
        while pending and len(procs) < cfg["parallel"] and now < stop_new:
            j = pending.pop(0)
            log = open(out / "logs" / f"{j['id']}.log", "w")
            procs[j["id"]] = subprocess.Popen(argv(j), stdout=log, stderr=subprocess.STDOUT, env=env, cwd=paths.ROOT)
            state[j["id"]] = dict(j, status="running", started=str(now), log=f"logs/{j['id']}.log")
            echo(f"search: started {j['id']} {_title(j)} {j.get('note', '')}")
            save()
        if not procs and (not pending or now >= stop_new):
            echo(f"search: finished ({sum(v['status'] == 'done' for v in state.values())} done)")
            save()
            write_outputs(out, state, path, echo)
            return state
        time.sleep(15)


def _title(j):
    if j["kind"] == "checkpoints":
        return f"checkpoints {j['year']} [{j.get('variants', 'default variants')}]"
    st = settings_class(j.get("sport", "f1")).from_dict(j["settings"])
    kind = "" if j["kind"] == "sweep" else ("downhill " if j["kind"] == "walk_forward" else j["kind"] + " ")
    return f"{kind}{st.label()} · {j['year']}" + (
        f" · rounds {j['rounds']}" if j.get("rounds") else "")


def write_outputs(out, state, queue_path=None, echo=print):
    """leaderboard.md and results.json from the finished jobs' saved runs."""
    from sqlalchemy import text

    from racinglines.db.config import get_engine
    from racinglines.models.position_sim import evaluate as EV
    from racinglines.pipelines import season_checkpoints as SC
    done = {k: v for k, v in state.items() if v.get("run_id")}
    runs = {}
    if done:
        with get_engine().connect() as c:
            rows = c.execute(text("SELECT id, kind, params, metrics FROM model_runs WHERE id = ANY(:ids)"),
                             dict(ids=[v["run_id"] for v in done.values()])).fetchall()
        runs = {r[0]: dict(id=r[0], kind=r[1], params=r[2], metrics=r[3]) for r in rows}
    cands = []
    if queue_path:
        try:
            cands = load(queue_path)[2]
        except (ValueError, tomllib.TOMLDecodeError):
            pass
    (out / "results.json").write_text(json.dumps(dict(state=state, runs=list(runs.values()), candidates=cands),
                                                 default=str))
    lines = [f"# Search leaderboard ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)", ""]
    sweeps = [(v, runs[v["run_id"]]) for v in done.values() if v["kind"] == "sweep" and v["run_id"] in runs]
    for year in sorted({v["year"] for v, _ in sweeps}):
        cols = [(v, r) for v, r in sweeps if v["year"] == year]
        default = SS.Settings.from_dict().key
        bases = {v.get("rounds"): r for v, r in cols if SS.Settings.from_dict(v["settings"]).key == default}
        n_w = max((len(r["metrics"].get("weekends") or []) for _, r in cols), default=0)
        lines += [f"## {year}: season sweeps ({n_w} weekends)", "",
                  "P&L in $ (weekends up) [difference from the baseline over the same weekends, same data]. "
                  "Best per strategy in **bold**.", ""]
        lines.append("| Strategy | " + " | ".join(SS.Settings.from_dict(v["settings"]).label()
                                                   + (f" · rounds {v['rounds']}" if v.get("rounds") else "")
                                                   for v, _ in cols) + " |")
        lines.append("|---" * (len(cols) + 1) + "|")
        for key, label in EV.STRATEGIES:
            vals = [((r["metrics"].get("totals") or {}).get(key) or {}).get("pnl") for _, r in cols]
            best = max((x for x in vals if x is not None), default=None)
            cells = []
            for (v, r), x in zip(cols, vals):
                if x is None:
                    cells.append("")
                    continue
                t = r["metrics"]["totals"][key]
                base = bases.get(v.get("rounds"))                   # the baseline over the same weekends
                bt = (base["metrics"].get("totals") or {}) if base else {}
                d = x - bt[key]["pnl"] if key in bt and r is not base else None
                cell = f"{x:+,.0f} ({t['weekends_up']}/{t['weekends']})" + (f" [{d:+,.0f}]" if d is not None else "")
                cells.append(f"**{cell}**" if x == best and len(cols) > 1 else cell)
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        lines.append("")
    wfs = [(v, runs[v["run_id"]]) for v in done.values() if v["kind"] == "walk_forward" and v["run_id"] in runs]
    for sport, year in sorted({(v["sport"], v["year"]) for v, _ in wfs}):
        cols = [(v, r) for v, r in wfs if (v["sport"], v["year"]) == (sport, year)]
        cls = settings_class(sport)
        bases = {v["settings"].get("seed"): r for v, r in cols            # the default settings, per seed
                 if cls.from_dict(v["settings"]).key == cls.from_dict({"seed": v["settings"].get("seed")}).key}
        kinds = sorted({k[:-len("_score")] for _, r in cols for w in (r["metrics"].get("weekends") or [])
                        for k in w if k.endswith("_score")})
        lines += [f"## {year}: {sport} walk-forward (model only)", "",
                  "Score per market kind = −1000 × log loss, summed over the season's events (higher is better) "
                  "[difference from the baseline at the same seed].", "",
                  "| Settings | " + " | ".join(kinds) + " |", "|---" * (len(kinds) + 1) + "|"]
        for v, r in cols:
            wk = r["metrics"].get("weekends") or []
            base = bases.get(v["settings"].get("seed"))
            cells = []
            for k in kinds:
                x = sum(w.get(f"{k}_score") or 0.0 for w in wk)
                d = None
                if base is not None and base is not r:
                    d = x - sum(w.get(f"{k}_score") or 0.0 for w in base["metrics"].get("weekends") or [])
                cells.append(f"{x:,.1f}" + (f" [{d:+,.1f}]" if d is not None else ""))
            lines.append(f"| {cls.from_dict(v['settings']).label()} | " + " | ".join(cells) + " |")
        lines.append("")
    for v in done.values():
        r = runs.get(v["run_id"])
        if not r:
            continue
        if v["kind"] == "checkpoints":
            import pandas as pd
            df = pd.DataFrame((r["metrics"] or {}).get("rows") or [])
            if len(df):
                lines += [f"## {v['year']}: championship checkpoints (run {r['id']})", "",
                          SC.format_summary(df, int(v.get("window") or SC.WINDOW)), ""]
        elif v["kind"] == "season_strategy":
            sm = (r["metrics"] or {}).get("summary") or {}
            hold = (r["metrics"] or {}).get("hold") or {}
            lines += [f"- {v['year']} season strategy, {_title(v)} (run {r['id']}): update after every race "
                      f"{sm.get('pnl', 0):+,.0f}, enter pre-season & hold {hold.get('pnl', 0):+,.0f}"]
    if cands:
        lines += ["", "## Candidates", ""] + [f"- **{c['name']}** ({c['year']}, {c['strategy']}): {c['why']}"
                                               for c in cands]
    other = [f"- {v['status']}: {_title(v)} ({k})" for k, v in state.items() if v["status"] != "done"]
    if other:
        lines += ["", "Not finished:", *other]
    (out / "leaderboard.md").write_text("\n".join(lines) + "\n")
    echo(f"search: leaderboard -> {paths.rel(out / 'leaderboard.md')}")


def import_results(path, engine_url=None, echo=print):
    """Load a search's results.json (e.g. from a cloud session) into this database: its saved runs
    (sweeps, checkpoints, season strategies) into model_runs marked params.source = 'search:<name>:<id>',
    and its candidates as kind='candidate' runs. Re-importing skips what's already there."""
    from sqlalchemy import text

    from racinglines.db.config import get_engine
    data = json.loads(open(path).read())
    name = os.path.basename(os.path.dirname(os.path.abspath(path)))
    eng = get_engine(engine_url)
    n = k = 0
    with eng.begin() as c:
        comp_f1 = comp = c.execute(text("SELECT id FROM competitions WHERE code = 'f1_wdc'")).scalar()
        cat_f1 = c.execute(text("SELECT id FROM categories WHERE competition_id = :c AND code = 'DRV'"), dict(c=comp)).scalar()
        new_ids = {}
        for r in data.get("runs", []):
            src = f"search:{name}:{r['id']}"
            have = c.execute(text("SELECT id FROM model_runs WHERE params->>'source' = :s"), dict(s=src)).scalar()
            if have:
                new_ids[r["id"]] = have
                continue
            params = dict(r["params"] or {}, source=src)
            comp, cat = comp_f1, cat_f1
            if r.get("kind") == "walk_forward":                # a downhill walk-forward
                comp = c.execute(text("SELECT id FROM competitions WHERE code = 'uci_dhi_wc'")).scalar()
                cat = c.execute(text("SELECT id FROM categories WHERE competition_id = :c AND code = :k"),
                                dict(c=comp, k=(params.get("settings") or {}).get("category", "ME"))).scalar()
            season = c.execute(text("SELECT id FROM seasons WHERE competition_id = :c AND year = :y"),
                               dict(c=comp, y=int(params.get("year") or 0))).scalar()
            model = {"sweep": "f1_sector_sim", "walk_forward": "timed_runs"}.get(r.get("kind", "sweep"), r.get("kind", "sweep"))
            new_ids[r["id"]] = c.execute(text("""INSERT INTO model_runs (competition_id, season_id, category_id, model, kind, params, metrics)
                                                 VALUES (:c, :s, :k, :m, :kind, CAST(:p AS jsonb), CAST(:x AS jsonb)) RETURNING id"""),
                                         dict(c=comp, s=season, k=cat, m=model, kind=r.get("kind", "sweep"),
                                              p=json.dumps(params, default=str), x=json.dumps(r["metrics"], default=str))).scalar()
            n += 1
        comp = comp_f1
        for cand in data.get("candidates", []):
            if cand.get("sport", "f1") != "f1":               # the Lab is F1's (downhill candidates stay in the report)
                continue
            src = f"search:{name}:candidate:{cand['name']}"
            if c.execute(text("SELECT 1 FROM model_runs WHERE kind = 'candidate' AND params->>'source' = :s"),
                         dict(s=src)).first():
                continue
            st = SS.Settings.from_dict(cand["settings"])
            run_id = next((new_ids[r["id"]] for r in data.get("runs", []) if r.get("kind", "sweep") == "sweep"
                           and (r["params"] or {}).get("settings_key") == st.key
                           and int((r["params"] or {}).get("year") or 0) == cand["year"]), None)
            add_candidate(c, cand["name"], st, cand["year"], cand["strategy"], cand.get("why", ""), run_id, src, comp,
                          candidate_id=cand.get("id"))
            k += 1
    echo(f"imported {n} run(s) and {k} candidate(s) from {path}")
    return n


def add_candidate(conn, name, settings, year, strategy, why="", run_id=None, source="lab", competition_id=None,
                  candidate_id=None):
    """A Lab candidate: a named, complete settings set (+ the strategy it's for and the run it came from).
    candidate_id: the search report's stable id (<strategy>-<settings key without the seed>), when it has one."""
    from sqlalchemy import text
    comp = competition_id or conn.execute(text("SELECT id FROM competitions WHERE code = 'f1_wdc'")).scalar()
    return conn.execute(text("""INSERT INTO model_runs (competition_id, model, kind, params)
                                VALUES (:c, 'candidate', 'candidate', CAST(:p AS jsonb)) RETURNING id"""),
                        dict(c=comp, p=json.dumps(dict(name=name, settings=settings.to_json(), settings_key=settings.key,
                                                       label=settings.label(), year=int(year), strategy=strategy,
                                                       why=why, run_id=run_id, source=source,
                                                       **({"candidate_id": candidate_id} if candidate_id else {}))))).scalar()
