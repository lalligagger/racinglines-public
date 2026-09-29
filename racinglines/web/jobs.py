"""
Model runs launched from the web app.

Each job type is a CLI command with a few typed knobs; the Lab page renders the
form from this catalog, so every sport gets the same UI. Jobs run one at a time
in a background thread as a subprocess (the same code path as the command line),
stream progress into the `jobs` table and link to the model run they saved.

Guard rails:
  - forecasts launched here are saved as kind='scenario': live prices only change
    when a maker promotes one (see promote());
  - backtests and diagnostics use the same as-of pricing as the CLI (no leakage
    by construction), whatever the knobs.
"""

import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text

from racinglines.db import models as m
from racinglines.db.config import get_engine, get_session

ROOT = Path(__file__).resolve().parents[2]      # the repository
LOG_MAX = 20_000


@dataclass
class Knob:
    name: str
    label: str
    type: str = "float"          # float | int | choice | text | datetime | event
    default: object = None
    min: float | None = None
    max: float | None = None
    choices: list = field(default_factory=list)
    help: str = ""


@dataclass
class JobType:
    code: str
    sport: str
    label: str
    what: str
    knobs: list
    argv: callable
    minutes: str = ""


# model variants offered for the sweep: each switch alone, and the combinations worth comparing
MODEL_CHOICES = ["baseline", "grid", "gridq", "pretrain", "gbm", "tail", "reset", "gridq+pretrain", "gridq+reset",
                 "pretrain+reset", "gridq+pretrain+reset", "gridq+pretrain+tail"]


def _sweep_argv(p):
    from racinglines.pipelines import sweep_settings as SS
    st = SS.Settings.from_dict(p.get("settings") or {})
    return ["-m", "racinglines", "f1", "--variant", st["variant"], "sweep", "--year", str(p.get("year", 2026)),
            "--no-fetch", "--save", *st.argv()]


def _f1_common(p):
    return ["-m", "racinglines", "f1", "--half-life", str(p["half_life"])]


HALF_LIFE = Knob("half_life", "Recency half-life (days)", "float", 120, 20, 720,
                 help="How fast old races fade from the pace models.")
F1_TRACK = Knob("track", "Track/sector features", "choice", "on", choices=["on", "off"],
                help="Use the sector-type car model at each circuit.")

CATALOG = {j.code: j for j in [
    JobType("f1_backtest", "f1", "Backtest", "Price past races as of just before qualifying and just before the race, "
            "then score against results and the grid-only baseline.",
            [Knob("races", "Last N races", "int", 30, 3, 200, help="Fewer races = faster."),
             HALF_LIFE,
             Knob("sims", "Simulations per race", "int", 2000, 200, 10000),
             Knob("track", "Track/sector features", "choice", "both", choices=["both", "on", "off"],
                  help="'both' runs twice to compare.")],
            lambda p, out: _f1_common(p) + ["backtest", "--races", str(p["races"]), "--sims", str(p["sims"]),
                                            "--track", p["track"], "--start-year", "2021", "--out", out, "--save"],
            "~1 min per 30 races"),
    JobType("f1_scenario", "f1", "Forward forecast (scenario)", "Price every remaining race and the championships "
            "with data up to now. Saved as a scenario; promote it to make it the live fair prices.",
            [Knob("label", "Scenario name", "text", "my scenario"), HALF_LIFE,
             Knob("sims", "Simulations", "int", 10000, 1000, 50000), F1_TRACK],
            lambda p, out: _f1_common(p) + ["forecast", "--sims", str(p["sims"]), "--save", "--scenario", p["label"]]
            + (["--no-track"] if p["track"] == "off" else []),
            "~1-2 min"),
    JobType("f1_diagnostic", "f1", "Event diagnostic", "Price one past race as of a cutoff (e.g. the evening before), "
            "then compare with Polymarket at that time and the result.",
            [Knob("event", "Event", "event"), Knob("cutoff", "As of (UTC)", "datetime"), HALF_LIFE,
             Knob("sims", "Simulations", "int", 10000, 1000, 50000), F1_TRACK],
            lambda p, out: _f1_common(p) + ["diagnostic", "--event", p["event"], "--cutoff", p["cutoff"],
                                            "--sims", str(p["sims"]), "--save"]
            + (["--no-track"] if p["track"] == "off" else []),
            "~1 min"),
    JobType("f1_sweep", "f1", "Edge Finder sweep (every weekend of the season)", "Every raced weekend of the "
            "season, priced with these settings before any running and after each session, then traded on "
            "Polymarket by every taker and maker strategy and settled on the result. The run joins the Edge Finder. "
            "Stages already priced with the same model settings and data are reused.",
            [Knob("year", "Season", "choice", "2026", choices=["2026", "2025"]),
             Knob("settings", "Settings", "sweep_settings", None)],
            lambda p, out: _sweep_argv(p),
            "a few minutes per season (GBM longer)"),
    JobType("f1_season_strategy", "f1", "Season strategy (championships)", "Replay the default championship-market "
            "strategy through the season on Polymarket's recorded prices: as-of season forecasts pre-season and after "
            "every race, rebalance, settle eliminated markets, mark the rest. Forecasts already computed are reused.",
            [Knob("min_edge", "Min edge to act (prob.)", "float", 0.03, 0.005, 0.5),
             Knob("stake_per_edge", "Stake per unit edge ($)", "float", 500, 10, 10000),
             Knob("max_stake", "Max stake per market ($)", "float", 150, 1, 10000),
             Knob("capital", "Capital cap ($)", "float", 1500, 50, 100000)],
            lambda p, out: ["-m", "racinglines", "f1", "season-strategy", "--no-fetch", "--save", "--min-edge", str(p["min_edge"]),
                            "--stake-per-edge", str(p["stake_per_edge"]), "--max-stake", str(p["max_stake"]),
                            "--capital", str(p["capital"])],
            "~1 min once forecasts exist"),
    JobType("dh_scenario", "mtb_dh", "Forward forecast (scenario)", "Simulate the remaining downhill rounds and the "
            "championship. Saved as a scenario; promote it to make it the live fair prices.",
            [Knob("label", "Scenario name", "text", "my scenario"),
             Knob("half_life", "Recency half-life (days)", "float", 240, 20, 2000),
             Knob("junior_weight", "Weight of junior results", "float", 0.25, 0, 1),
             Knob("sims", "Simulations", "int", 10000, 1000, 50000)],
            lambda p, out: ["-m", "racinglines", "mtb_dh", "forecast", "--db", "--save", "--scenario", p["label"],
                            "--half-life-days", str(p["half_life"]), "--junior-weight", str(p["junior_weight"]),
                            "--sims", str(p["sims"]), "--out-dir", str(Path(out).parent.parent / "mtb_dh" / "season")],
            "~1 min"),
    JobType("dh_backtest", "mtb_dh", "Backtest", "Walk forward through past downhill seasons, predicting each round "
            "from earlier ones only.",
            [Knob("half_life", "Recency half-life (days)", "float", 240, 20, 2000),
             Knob("junior_weight", "Weight of junior results", "float", 0.25, 0, 1),
             Knob("sims", "Simulations", "int", 2000, 200, 10000)],
            lambda p, out: ["-m", "racinglines", "mtb_dh", "backtest", "--db", "--save", "--half-life-days", str(p["half_life"]),
                            "--junior-weight", str(p["junior_weight"]), "--sims", str(p["sims"]),
                            "--out-dir", str(Path(out).parent.parent / "mtb_dh" / "backtests")],
            "a few min"),
]}


def parse(job_type, form):
    """Validate a submitted form against the job's knobs. Returns params or raises ValueError."""
    out = {}
    for k in job_type.knobs:
        if k.type == "sweep_settings":                 # every field of the sweep settings schema
            out[k.name] = parse_sweep_settings(form)
            continue
        raw = (form.get(k.name) or "").strip()
        if raw == "" and k.default is not None:
            raw = str(k.default)
        if k.type in ("float", "int"):
            v = float(raw) if k.type == "float" else int(float(raw))
            if (k.min is not None and v < k.min) or (k.max is not None and v > k.max):
                raise ValueError(f"{k.label} must be between {k.min:g} and {k.max:g}")
            out[k.name] = v
        elif k.type == "choice":
            if raw not in k.choices:
                raise ValueError(f"{k.label}: pick one of {k.choices}")
            out[k.name] = raw
        elif k.type == "datetime":
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", raw):
                raise ValueError(f"{k.label}: use YYYY-MM-DDTHH:MM")
            out[k.name] = raw
        elif k.type == "event":
            if not re.fullmatch(r"\d{4}-\d{1,2}", raw):
                raise ValueError(f"{k.label}: pick an event")
            out[k.name] = raw
        else:
            if not raw or len(raw) > 60 or not re.fullmatch(r"[\w .,'()-]+", raw):
                raise ValueError(f"{k.label}: letters, numbers and spaces, up to 60 characters")
            out[k.name] = raw
    return out


def parse_sweep_settings(form):
    """{name: value} of the settings that differ from the defaults (validated), from the Lab form: one
    field per setting; booleans are checkboxes (with a hidden 'false' before each), multi-choice
    settings are checkbox groups."""
    from racinglines.pipelines import sweep_settings as SS
    getlist = form.getlist if hasattr(form, "getlist") else (
        lambda k: [] if form.get(k) in (None, "") else (form[k] if isinstance(form[k], list) else [form[k]]))
    d = {}
    for s in SS.SETTINGS:
        if s.type == "multi":
            if form.get(f"{s.name}__present") is None:
                continue
            d[s.name] = [v for v in getlist(s.name) if v]
        elif s.type == "bool":
            vals = getlist(s.name)
            if vals:
                d[s.name] = "true" in vals
        else:
            raw = (form.get(s.name) or "").strip()
            if raw != "":
                d[s.name] = raw
    st = SS.Settings.from_dict(d)
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in st.changed().items()}


def submit(job_type, params, user_id, engine=None):
    """Queue a job (the caller has validated `params` with parse()). `engine`: a database other than the default one."""
    from sqlalchemy.orm import sessionmaker
    with (sessionmaker(engine, expire_on_commit=False)() if engine is not None else get_session()) as s:
        job = m.Job(kind=job_type.code, sport=job_type.sport, params=params, user_id=user_id, status="queued")
        s.add(job)
        s.commit()
        job_id = job.id
    _wake.set()
    return job_id


def promote(session, run_id):
    """Make a scenario run the live forecast for its competition/category."""
    run = session.get(m.ModelRun, run_id)
    if run is None or run.kind not in ("scenario", "forecast"):
        raise ValueError("only forecast scenarios can be promoted")
    run.kind = "forecast"
    run.params = dict(run.params or {}, promoted_at=datetime.now(timezone.utc).isoformat())
    session.commit()


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

_wake = threading.Event()
_started = False


def start_worker(reset_running=True):
    """Start the worker thread. `reset_running`: mark jobs still 'running' as failed first (the web app on start: those
    were its own subprocesses, gone with the restart); the MCP server passes False, since a running job may be the web app's."""
    global _started
    if _started:
        return
    _started = True
    if reset_running:
        with get_engine().begin() as c:
            c.execute(text("""UPDATE jobs SET status = 'failed', finished_at = now(),
                              progress = 'interrupted: the app restarted' WHERE status = 'running'"""))
    threading.Thread(target=_loop, daemon=True, name="jobs").start()


def _loop():
    while True:
        try:
            if not _run_next():
                _wake.wait(timeout=5)
                _wake.clear()
        except Exception as ex:  # noqa: BLE001  keep the worker alive
            print(f"jobs worker error: {ex}", file=sys.stderr)
            time.sleep(5)


def _run_next():
    with get_session() as s:
        job = s.scalars(select(m.Job).where(m.Job.status == "queued").order_by(m.Job.id)
                        .with_for_update(skip_locked=True).limit(1)).first()
        if job is None:
            return False
        jt = CATALOG[job.kind]
        from racinglines import paths
        out = paths.runs("jobs") / f"job_{job.id}.csv"
        argv = [sys.executable] + jt.argv(job.params, str(out))
        job.argv, job.status, job.started_at, job.progress = argv[1:], "running", datetime.now(timezone.utc), "starting"
        s.commit()
        job_id = job.id
    log, last_write, status, run_id = [], 0.0, "failed", None
    try:
        p = subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        progress = "running"
        for line in p.stdout:
            line = line.rstrip()
            if line.startswith("INFO ") or not line:
                continue
            log.append(line)
            if line.startswith("progress "):
                progress = line[9:][:200]
            mt = re.search(r"Saved (?:\w+ )*run (\d+)", line)
            if mt:
                run_id = int(mt.group(1))
            if time.time() - last_write > 1.5:
                _update(job_id, progress=progress, log="\n".join(log)[-LOG_MAX:])
                last_write = time.time()
        rc = p.wait()
        status = "done" if rc == 0 else "failed"
        progress = "finished" if rc == 0 else f"exit code {rc}"
    except Exception as ex:  # noqa: BLE001
        log.append(f"error: {ex}")
        progress = f"error: {ex}"[:200]
    _update(job_id, status=status, progress=progress, finished_at=datetime.now(timezone.utc),
            result_run_id=run_id, log="\n".join(log)[-LOG_MAX:])
    return True


def _update(job_id, **values):
    with get_session() as s:
        job = s.get(m.Job, job_id)
        for k, v in values.items():
            setattr(job, k, v)
        s.commit()
