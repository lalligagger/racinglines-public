"""Local-only, finite-pool Jev sweep controller (research, not a trading service).

Dry runs are pure: no journal, lock, database, SDK, or subprocess is opened.
Execution requires --execute, positive budgets and an existing database backup.
The backup must cover the local database used by the CLI; the operator owns
rollback (restore that backup separately, never automatically from this runner).
Pool/settings, objective and model must remain unchanged on resume. To extend a
pool, use a new journal; saved exact-key sweeps are still reused from the database.
Every candidate is confirmed in both years, including same-fidelity baselines.
Controller verdicts pin the search-report default noise floors (150 taker / 350
maker); descriptive reports may instead measure replicate noise. Journal v2
rejects older schemas rather than silently changing cached decision evidence.
Any existing partial sweep with a requested (year, exact key) blocks execution
unless a usable full-season counterpart exists. Partial keys are never "new".
The child inherits the workspace lock, so even SIGKILL of the controller blocks
other runners until it exits. Its PID is also checkpointed; restart never kills
a saved PID (which may have been reused), and blocks while it might be alive.
"""

import csv
import fcntl
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from racinglines import paths
from racinglines.pipelines.sweep_settings import Settings
from racinglines.research.jev_gate import DEFAULT_MODEL

OBJECTIVE = "search-report-baseline-gain-v1"
STOP = "STOP"
MAX_POOL = 254  # One of the 255 Choice options is STOP.


@dataclass(frozen=True)
class Config:
    pool: list
    strategy: str = "update"
    target: int = 2026
    holdout: int = 2025
    confirm_sims: int = 16000
    model: str = DEFAULT_MODEL
    stop_after: int = 0
    margin: float = 0.0

    def document(self):
        if not isinstance(self.pool, list) or not self.pool or len(self.pool) > MAX_POOL:
            raise ValueError("pool must contain 1..254 exact configurations (plus STOP)")
        if any(not isinstance(s, dict) for s in self.pool):
            raise ValueError("each pool configuration must be a settings dictionary")
        pool = [Settings.from_dict(s) for s in self.pool]
        if len({s.key for s in pool}) != len(pool):
            raise ValueError("duplicate exact Settings.key in pool")
        if len({s["sims"] for s in pool}) != 1:
            raise ValueError("MVP pool must have one common ranking simulation count")
        if any(s.get("venue") is not None for s in pool):
            raise ValueError("MVP uses the default venue only; leave venue unset")
        if self.target != 2026 or self.holdout != 2025:
            raise ValueError("MVP requires target 2026 and held-out 2025")
        if type(self.confirm_sims) is not int or type(self.stop_after) is not int:
            raise ValueError("confirm_sims and stop_after must be integers, not booleans")
        Settings.from_dict({"sims": self.confirm_sims})
        if self.confirm_sims <= pool[0]["sims"]:
            raise ValueError("confirmation sims must exceed ranking sims")
        if self.stop_after < 0 or not math.isfinite(self.margin) or self.margin < 0:
            raise ValueError("stop_after and finite improvement margin must be nonnegative")
        from racinglines.models.evaluate import STRATEGIES
        from racinglines.pipelines.search_report import DEFAULTS
        if self.strategy not in dict(STRATEGIES):
            raise ValueError(f"unknown search-report strategy {self.strategy!r}")
        if not self.model:
            raise ValueError("Jev model is required")
        return dict(pool=[s.to_json() for s in sorted(pool, key=lambda s: s.key)],
                    strategy=self.strategy, target=self.target, holdout=self.holdout,
                    confirm_sims=self.confirm_sims, model=self.model, stop_after=self.stop_after,
                    margin=self.margin, metric=OBJECTIVE, rank_sims=pool[0]["sims"],
                    noise_policy="fixed-search-report-defaults-v1", noise=dict(DEFAULTS["noise"]))


def job_id(year, settings):
    return f"{year}:{Settings.from_dict(settings).key}"


def requirements(settings, cfg):
    """Deterministic, exact-key work order; every missing job consumes one attempt."""
    st = Settings.from_dict(settings)
    jobs = {}
    for sims in (st["sims"], cfg["confirm_sims"]):
        baseline = Settings.from_dict(dict(sims=sims, seed=st["seed"]))
        candidate = Settings.from_dict(dict(st, sims=sims))
        for s in (baseline, candidate):
            for year in (cfg["target"], cfg["holdout"]):
                jid = job_id(year, s)
                jobs[jid] = dict(id=jid, year=year, settings=s.to_json())
    return list(jobs.values())


def plan(config):
    cfg = config.document()
    jobs = {j["id"]: j for s in cfg["pool"] for j in requirements(s, cfg)}
    return dict(config=cfg, candidates=len(cfg["pool"]), jobs=list(jobs.values()),
                max_new_sweeps=len(jobs), sweep_budget=0, jev_budget=0, dry_run=True)


def _atomic(path, value):
    """Replace beside the journal, fsync both file and directory; never use /tmp."""
    path = Path(path)
    staging = path.with_name(path.name + ".pending")
    with staging.open("w") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(staging, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _lock(path):
    with Path(str(path) + ".lock").open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as ex:
            raise RuntimeError("another controller owns this journal") from ex
        try:
            yield f.fileno()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


@contextmanager
def heartbeat(label, echo):
    start = time.monotonic()
    stop = threading.Event()

    def beat():
        while not stop.wait(60):
            echo(f"auto-sweeper: {int(time.monotonic() - start)}s elapsed · waiting for {label}")

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


@contextmanager
def _signals():
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"signal {signum}")

    old = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            old[sig] = signal.signal(sig, interrupted)
        yield
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


def sweep_argv(job):
    st = Settings.from_dict(job["settings"])
    return [sys.executable, "-m", "racinglines", "strategy", "sweep", "f1",
            "--variant", st["variant"], "--year", str(job["year"]), "--no-fetch", "--save", *st.argv()]


def local_database():
    """Resolve one explicit local source for both reconciliation and the child."""
    from sqlalchemy.engine import make_url
    from racinglines.cli import config
    from racinglines.db.config import DEFAULT_URL

    if os.environ.get("RACINGLINES_DEMO"):
        raise ValueError("auto-sweeper cannot execute against a demo store")
    defaults = config.load()
    url = os.environ.get("DATABASE_URL") or defaults.get("db") or DEFAULT_URL
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or parsed.host not in (None, "localhost", "127.0.0.1", "::1"):
        raise ValueError("auto-sweeper requires a local PostgreSQL URL; remote databases are not allowed")
    return url


def database_identity():
    """Non-secret identity; never persist credentials or the connection URL."""
    from sqlalchemy.engine import make_url
    url = make_url(local_database())
    identity = dict(host=url.host or "localhost", port=url.port or 5432, database=url.database)
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


class LocalExecutor:
    """One directly owned child; never kills by name or touches unrelated processes."""

    owns_child = True

    def run(self, job, log, echo, started=None):
        with Path(log).open("a") as output:
            # Defer termination until Popen's returned child is owned by this frame.
            deferred = []
            handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
            for sig in handlers:
                signal.signal(sig, lambda signum, frame: deferred.append(signum))
            child = None
            try:
                child = subprocess.Popen(sweep_argv(job), stdout=output, stderr=subprocess.STDOUT,
                                         env=dict(os.environ, PYTHONUNBUFFERED="1", DATABASE_URL=local_database()),
                                         cwd=paths.ROOT,
                                         pass_fds=((self.lock_fd,) if hasattr(self, "lock_fd") else ()))
                if started:
                    started(child.pid)
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
                if deferred:
                    raise KeyboardInterrupt(f"signal {deferred[-1]}")
                with heartbeat(job["id"], echo):
                    code = child.wait()
                if code:
                    raise RuntimeError(f"sweep {job['id']} exited {code}; see {log}")
            except BaseException:
                # Ignore a second termination request until the owned child has been reaped.
                old = {s: signal.signal(s, signal.SIG_IGN) for s in (signal.SIGINT, signal.SIGTERM)}
                try:
                    if child is not None:
                        if child.poll() is None:
                            child.terminate()
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                finally:
                    for sig, handler in old.items():
                        signal.signal(sig, handler)
                raise
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)


def load_runs(requested=None):
    """Lazy read-only reconciliation, including legacy and partial exact identities."""
    from sqlalchemy import text
    from racinglines.db.config import get_engine

    with get_engine(local_database()).connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            rows = conn.execute(text("""
                SELECT id, params, metrics FROM model_runs
                WHERE kind = 'sweep' AND coalesce(params->>'sport', 'f1') = 'f1'
                  AND params->>'year' IN ('2026', '2025')
                ORDER BY id
            """)).mappings().all()
    out = []
    partial = set()
    for row in rows:
        p = row["params"]
        stored_key = p.get("settings_key")
        identity = f"{p['year']}:{stored_key}"
        if requested is not None and identity not in requested:
            continue
        if p.get("rounds"):
            partial.add(identity)
            continue
        if not stored_key:
            raise ValueError(f"saved sweep {row['id']} lacks exact settings_key")
        st = Settings.from_run_params(p)
        if p.get("settings_key") != st.key:
            raise ValueError(f"saved sweep {row['id']} settings_key mismatch")
        if not row["metrics"] or not row["metrics"].get("weekends"):
            raise ValueError(f"saved sweep {row['id']} lacks completed weekend metrics")
        out.append(dict(year=int(p["year"]), settings=st.to_json(),
                        run_id=row["id"], metrics=row["metrics"]))
    complete = {job_id(r["year"], r["settings"]) for r in out}
    if partial - complete:
        raise ValueError(f"stored partial sweep blocks exact-key rerun: {sorted(partial - complete)}; "
                         "inspect the existing run; do not silently relaunch")
    return out


def ask_jev(evidence, options, model):
    """TypeSafe's typed Choice protocol, matching jev_gate/jev_trader examples."""
    from racinglines.research.jev_gate import make_client
    from typesafe_sdk import RetryPolicy

    if len(options) > 255 or STOP not in options:
        raise ValueError("Choice must include STOP and at most 255 options")
    response = make_client().system_one(
        state=evidence, model=model, retry=RetryPolicy(max_retries=0, timeout=30.0),
        questions={"next": {"type": "choice", "instructions":
            "Choose the next full configuration to evaluate, or STOP. Maximize the supplied search-report "
            "baseline-gain objective, not raw P&L. Heldout, noise and higher-sims confirmations are mandatory "
            "evidence, not proof of future profit. Only the listed exact configuration ids are allowed.",
            "criteria": {o: "stop research" if o == STOP else f"evaluate exact settings {o}" for o in options}}})
    answer = response.choices["next"]
    return dict(choice=answer.choice, probabilities=dict(answer.probabilities),
                confidence=answer.confidence)


def _validate_evidence(jobs, runs, cfg):
    metrics = {r["run_id"]: r["metrics"] for r in runs.values()}
    coverage = {}
    for job in jobs:
        weekends = metrics[job["run_id"]].get("weekends")
        if not isinstance(weekends, list) or not weekends:
            raise ValueError(f"run {job['run_id']}: missing weekend evidence")
        rounds, events = set(), set()
        for weekend in weekends:
            rnd, event = weekend.get("round"), weekend.get("event")
            value = weekend.get(f"{cfg['strategy']}_pnl")
            if type(rnd) is not int or rnd < 1 or rnd in rounds:
                raise ValueError(f"run {job['run_id']}: invalid or duplicate round")
            if not isinstance(event, str) or not event.strip() or event in events:
                raise ValueError(f"run {job['run_id']}: invalid or duplicate event")
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"run {job['run_id']}: missing/nonfinite {cfg['strategy']}_pnl")
            rounds.add(rnd)
            events.add(event)
        coverage[job["id"]] = {(w["round"], w["event"]) for w in weekends}
    for job in jobs:
        st = Settings.from_dict(job["settings"])
        baseline = job_id(job["year"], dict(sims=st["sims"], seed=st["seed"]))
        if baseline in coverage and coverage[baseline] != coverage[job["id"]]:
            raise ValueError(f"run {job['run_id']}: candidate/baseline round/event coverage mismatch")


def stored_evidence(jobs, runs, cfg):
    """Bounded aggregate evidence, including partially completed historical pairs."""
    from racinglines.pipelines import search_report as report
    _validate_evidence(jobs, runs, cfg)
    metrics = {r["run_id"]: r["metrics"] for r in runs.values()}
    rows, _ = report.stats(jobs, metrics, [(cfg["strategy"], cfg["strategy"])])
    return [dict(id=r["job"], year=r["year"],
                 baseline=Settings.from_dict(runs[r["job"]]["settings"]).key == Settings.from_dict(
                     dict(sims=r["sims"], seed=r["seed"])).key,
                 sims=r["sims"], seed=r["seed"], pnl=r["pnl"], gain=r["vs_baseline"],
                 drawdown=r["max_drawdown"], without_best2=r["pnl_without_best2"],
                 weekends=r["weekends"]) for r in rows]


def _paired_jobs(jobs):
    """Descriptive ranking omits unpaired historical runs, never fabricates zeros."""
    present = {j["id"] for j in jobs}
    return [j for j in jobs if job_id(
        j["year"], dict(sims=Settings.from_dict(j["settings"])["sims"],
                        seed=Settings.from_dict(j["settings"])["seed"])) in present]


def score_results(jobs, runs, cfg, settings=None):
    """Real search-report statistics/ranking, with ranking value = baseline gain."""
    from racinglines.pipelines import search_report as report
    strategies = [(cfg["strategy"], cfg["strategy"])]
    metrics = {r["run_id"]: r["metrics"] for r in runs.values()}
    _validate_evidence(jobs, runs, cfg)
    jobs = _paired_jobs(jobs)
    report_cfg = dict(target=cfg["target"], holdout=[cfg["holdout"]],
                      rank_sims=cfg["rank_sims"], confirm_sims=cfg["confirm_sims"])
    rows, curves = report.stats(jobs, metrics, strategies, report_cfg)
    if settings is not None:
        # Pin controller noise to the versioned report defaults. Descriptive
        # search-report may measure replicate noise; it is not a cached verdict.
        report_cfg["noise"] = dict(cfg["noise"])
        wanted = {j["id"] for j in requirements(settings, cfg)}
        rows, curves = report.stats([j for j in jobs if j["id"] in wanted],
                                   metrics, strategies, report_cfg)
    raw, _, _ = report.rank(rows, curves, report_cfg)
    ranked, _, _ = report.rank(rows, curves, dict(report_cfg, value="baseline_gain"))
    risks = {r["id"]: r for r in raw}
    for row in ranked:
        # The non-P&L ranking branch intentionally omits descriptive P&L risks.
        row.update({k: risks[row["id"]][k] for k in ("shape", "loses_money_in")})
    return ranked, report_cfg, metrics, strategies


def _evidence_row(row, cfg):
    fields = ("score", "verdict", "confirmed", "noise_floor", "vs_base_target", "dd_target", "pnl_target",
              "gain_without_best_target", "without_best2_target", "shape", "loses_money_in",
              f"vs_base_{cfg['holdout']}", f"dd_{cfg['holdout']}", f"pnl_{cfg['holdout']}",
              f"confirm_{cfg['target']}", f"confirm_{cfg['holdout']}")
    return {k: row[k] for k in fields}


def _write_reports(out, jobs, runs, cfg):
    from racinglines.pipelines import search_report as report

    _, rcfg, metrics, strategies = score_results(jobs, runs, cfg)
    evidence_dir = out / "search-report"
    evidence_dir.mkdir(exist_ok=True)
    report.write(evidence_dir, _paired_jobs(jobs), metrics, strategies, rcfg, echo=lambda *a: None)
    ranking = []
    for settings in cfg["pool"]:
        if not all(j["id"] in runs for j in requirements(settings, cfg)):
            continue
        exact = Settings.from_dict(settings).key
        ranked, _, _, _ = score_results(jobs, runs, cfg, settings)
        row = next(r for r in ranked if Settings.from_dict(r["settings"]).key == exact)
        ranking.append(dict(row, settings_key=exact))
    ranking.sort(key=lambda r: -r["score"])
    # Existing search-report files are descriptive P&L evidence. Controller's
    # separately named leaderboard uses the explicitly chosen gain objective.
    lines = ["# Local finite-pool sweep leaderboard", "",
             "Objective: target baseline gain + min(0, held-out baseline gain), from search-report.rank.",
             "The search-report/ folder retains the ordinary P&L report, not the selection objective.",
             "Controller verdict noise is pinned to report defaults; descriptive search-report may use measured "
             "replicate noise and therefore differ. Cached controller evaluations never drift.",
             "Verdicts describe backtests; neither a gain nor a robust label promises future profit.", "",
             "| settings (exact key) | score | gain target / heldout | P&L target / heldout | noise | "
             "verdict | confirmed (target / heldout gain) | drawdown | gain without best | shape | loses money in |",
             "|---|---:|---|---|---:|---|---|---:|---:|---|---|"]
    for row in ranking:
        lines.append(f"| {row['label_settings']} ({row['settings_key']}) | {row['score']} | "
                     f"{row['vs_base_target']} / {row[f'vs_base_{cfg['holdout']}']} | "
                     f"{row['pnl_target']} / {row[f'pnl_{cfg['holdout']}']} | {row['noise_floor']} | "
                     f"{row['verdict']} | {row['confirmed']} ({row[f'confirm_{cfg['target']}']} / "
                     f"{row[f'confirm_{cfg['holdout']}']}) | {row['dd_target']} | "
                     f"{row['gain_without_best_target']} | {row['shape']} | {row['loses_money_in']} |")
    (out / "leaderboard.md").write_text("\n".join(lines) + "\n")
    with (out / "leaderboard.csv").open("w") as f:
        fields = ["settings_key", "label_settings", *_evidence_row(ranking[0], cfg)] if ranking else ["settings_key"]
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        for row in ranking:
            writer.writerow(dict(settings_key=row["settings_key"], label_settings=row["label_settings"],
                                 **_evidence_row(row, cfg)))


def _new_state(cfg, budget, jev_budget):
    return dict(version=2, config=cfg, budget=budget, jev_budget=jev_budget,
                attempts=[], choices=[], active=None, evaluations={}, best=None, misses=0,
                failure=None, failure_job=None, stopped=None, database_identity=None, pins={})


def _read_state(path, cfg):
    try:
        state = json.loads(path.read_text())
        required = set(_new_state(cfg, 0, 0))
        if not isinstance(state, dict) or set(state) != required or state["version"] != 2:
            raise ValueError("invalid journal schema")
        if state["config"] != cfg:
            raise ValueError("incompatible journal configuration; pool/model/objective/stop rule must be unchanged")
        for key in ("budget", "jev_budget", "misses"):
            if type(state[key]) is not int or state[key] < 0:
                raise ValueError(f"invalid journal {key}")
        if not isinstance(state["attempts"], list) or not isinstance(state["choices"], list):
            raise ValueError("invalid journal attempts/choices")
        if len(state["attempts"]) > state["budget"] or len(state["choices"]) > state["jev_budget"]:
            raise ValueError("journal counters exceed budget")
        keys = {Settings.from_dict(s).key for s in cfg["pool"]}
        if state["active"] is not None and state["active"] not in keys:
            raise ValueError("journal active config not in pool")
        if not isinstance(state["evaluations"], dict) or not set(state["evaluations"]) <= keys:
            raise ValueError("invalid journal evaluations")
        expected_evidence = {"score", "verdict", "confirmed", "noise_floor", "vs_base_target", "dd_target", "pnl_target",
                             "gain_without_best_target", "without_best2_target", "shape", "loses_money_in",
                             f"vs_base_{cfg['holdout']}", f"dd_{cfg['holdout']}", f"pnl_{cfg['holdout']}",
                             f"confirm_{cfg['target']}", f"confirm_{cfg['holdout']}"}
        text_fields = {"verdict", "confirmed", "shape", "loses_money_in"}
        for evidence in state["evaluations"].values():
            if not isinstance(evidence, dict) or set(evidence) != expected_evidence:
                raise ValueError("invalid journal score evidence")
            for key, value in evidence.items():
                if key in text_fields:
                    if not isinstance(value, str):
                        raise ValueError("invalid journal verdict")
                elif value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                    raise ValueError("invalid journal numerical evidence")
            if evidence["score"] is None:
                raise ValueError("journal score must be finite")
        if state["misses"] > len(state["evaluations"]):
            raise ValueError("invalid journal miss streak")
        if state["best"] is not None and (not isinstance(state["best"], (int, float))
                                          or not math.isfinite(state["best"])):
            raise ValueError("invalid journal best")
        valid_jobs = {j["id"] for s in cfg["pool"] for j in requirements(s, cfg)}
        if not isinstance(state["pins"], dict) or not set(state["pins"]) <= valid_jobs:
            raise ValueError("invalid journal run pins")
        if any(type(rid) is not int or rid <= 0 for rid in state["pins"].values()):
            raise ValueError("invalid journal pinned run id")
        context = state["database_identity"]
        if context is not None and (not isinstance(context, str) or len(context) != 64):
            raise ValueError("invalid journal database identity")
        for attempt in state["attempts"]:
            if (not isinstance(attempt, dict) or attempt["id"] not in valid_jobs
                    or attempt["id"] != job_id(attempt["year"], attempt["settings"])
                    or attempt["status"] not in ("launched", "done", "failed", "interrupted")):
                raise ValueError("invalid journal attempt")
            if "pid" in attempt and (type(attempt["pid"]) is not int or attempt["pid"] <= 0):
                raise ValueError("invalid journal child PID")
        for choice in state["choices"]:
            if not isinstance(choice, dict) or not isinstance(choice["options"], list):
                raise ValueError("invalid journal choice")
            options = choice["options"]
            if not options or options[-1] != STOP or len(options) > 255 or len(set(options)) != len(options):
                raise ValueError("invalid journal Choice options")
            if not set(options) <= keys | {STOP}:
                raise ValueError("journal Choice contains out-of-pool options")
            if choice["status"] not in ("calling", "done", "failed", "interrupted"):
                raise ValueError("invalid journal choice")
            if choice["status"] == "done" and choice["answer"]["choice"] not in options:
                raise ValueError("invalid cached choice")
        if state["stopped"] not in (None, "pool exhausted", "Jev STOP", "no improvement"):
            raise ValueError("invalid journal stop reason")
        if state["failure_job"] is not None and state["failure_job"] not in valid_jobs:
            raise ValueError("invalid journal failed job")
        return state
    except (ValueError, KeyError, TypeError) as ex:
        raise ValueError(f"unusable journal {path}: {ex}") from ex


def run(config, journal, *, execute=False, budget=None, jev_budget=None, increase_budget=False,
        backup=None, retry_failed=False, loader=load_runs, executor=None, chooser=ask_jev,
        echo=None):
    """Injection seams are read-only loader(), executor.run(job, log, echo), chooser(...).

    Budgets count durably *before* a launch/call. A crash may spend an attempt
    without producing a result; explicit retry spends another attempt, never a refund.
    """
    cfg = config.document()
    if not execute:
        return plan(config)
    echo = echo or (lambda message: print(message, flush=True))
    if backup is None or not Path(backup).is_file() or Path(backup).stat().st_size == 0:
        raise ValueError("execution requires an existing nonempty local DB backup; operator owns rollback")
    for value in (budget, jev_budget):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("budgets must be nonnegative integers")
    journal = Path(journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    executor = executor or LocalExecutor()
    # The workspace-wide lock also excludes runners with *different* journals.
    global_lock = paths.ROOT / "data/runs/auto-sweeper"
    global_lock.parent.mkdir(parents=True, exist_ok=True)
    with _lock(global_lock) as lock_fd, _lock(journal), _signals():
        if getattr(executor, "owns_child", False) is True:
            executor.lock_fd = lock_fd
        state = _read_state(journal, cfg) if journal.exists() else _new_state(cfg, budget or 0, jev_budget or 0)
        real_io = loader is load_runs or getattr(executor, "owns_child", False) is True
        context = database_identity() if real_io else hashlib.sha256(b"injected-replay-context").hexdigest()
        if state["database_identity"] is not None and state["database_identity"] != context:
            raise ValueError("incompatible database identity; cannot resume against another database")
        state["database_identity"] = context
        for key, value in (("budget", budget), ("jev_budget", jev_budget)):
            if value is not None and value != state[key]:
                if value < state[key] or not increase_budget:
                    raise ValueError(f"{key} can only increase with explicit increase_budget")
                state[key] = value
        pool = {Settings.from_dict(s).key: s for s in cfg["pool"]}
        work = {j["id"]: j for s in cfg["pool"] for j in requirements(s, cfg)}
        runs = {}
        in_flight = None

        def save():
            _atomic(journal, state)

        def reconcile():
            nonlocal runs
            current = {}
            observed = {}
            for a in state["attempts"]:
                if a.get("pid") and not a.get("reaped"):
                    try:
                        os.kill(a["pid"], 0)
                    except ProcessLookupError:
                        pass
                    except PermissionError as ex:
                        raise RuntimeError(f"owned sweep PID {a['pid']} may still be alive; operator inspection "
                                           "required before resuming") from ex
                    else:
                        raise RuntimeError(f"owned sweep PID {a['pid']} may still be alive; "
                                           "inspect/reap it before resuming, never blindly retry")
            for r in (loader(work) if loader is load_runs else loader()):
                jid = job_id(r["year"], r["settings"])
                if jid in work:
                    if not r["metrics"].get("weekends"):
                        raise ValueError(f"stored run {r['run_id']} has no weekend evidence")
                    observed.setdefault(jid, {})[r["run_id"]] = r
            for jid, rid in state["pins"].items():
                if rid not in observed.get(jid, {}):
                    raise RuntimeError(f"previously committed sweep disappeared or was replaced: {jid} run {rid}; "
                                       "inspect DB/backup before continuing")
            for jid, by_id in observed.items():
                rid = state["pins"].setdefault(jid, min(by_id))
                current[jid] = by_id[rid]
            runs = current
            for a in state["attempts"]:
                if a["id"] in runs:
                    a.update(status="done", run_id=runs[a["id"]]["run_id"])
                elif a["status"] == "launched":
                    a["status"] = "interrupted"
                elif a["status"] == "done":
                    raise RuntimeError("previously committed sweep disappeared; inspect DB/backup before continuing")

        def jobs_done():
            return [dict(work[jid], run_id=r["run_id"], rounds=None) for jid, r in runs.items()]

        try:
            reconcile()
            for c in state["choices"]:
                if c["status"] == "calling":
                    c["status"] = "interrupted"
            bad_attempt = any(a["status"] in ("failed", "interrupted") for a in state["attempts"]
                              if a["id"] not in runs)
            bad_choice = bool(state["choices"] and state["choices"][-1]["status"] in ("failed", "interrupted"))
            if (bad_attempt or bad_choice or state["failure"]) and not retry_failed:
                # A commit-before-checkpoint is recovered without asking for a retry.
                recovered = state["failure_job"] in runs if state["failure_job"] else not state["failure"]
                if bad_attempt or bad_choice or not recovered:
                    raise RuntimeError("previous failure/interruption; inspect journal, then explicitly retry_failed")
            state["failure"] = None
            state["failure_job"] = None
            save()
            while not state["stopped"]:
                reconcile()
                active = state["active"]
                if active is None:
                    # Already committed complete evaluations need no Jev selection.
                    ready = [k for k, s in pool.items() if k not in state["evaluations"]
                             and all(j["id"] in runs for j in requirements(s, cfg))]
                    if ready:
                        active = state["active"] = ready[0]
                        save()
                    else:
                        options = [k for k in pool if k not in state["evaluations"]]
                        if not options:
                            state["stopped"] = "pool exhausted"
                            break
                        if len(state["attempts"]) >= state["budget"]:
                            break
                        if len(state["choices"]) >= state["jev_budget"]:
                            break
                        evidence = dict(objective=OBJECTIVE, years=[cfg["target"], cfg["holdout"]],
                                        candidates=[dict(id=k, settings=pool[k]) for k in options],
                                        completed=state["evaluations"],
                                        remaining_sweeps=state["budget"] - len(state["attempts"]))
                        evidence["stored"] = stored_evidence(jobs_done(), runs, cfg)
                        evidence["noise"] = dict(policy=cfg["noise_policy"], **cfg["noise"])
                        choice = dict(status="calling", options=options + [STOP], evidence=evidence)
                        state["choices"].append(choice)
                        save()
                        try:
                            with heartbeat("Jev choice", echo):
                                answer = chooser(evidence, choice["options"], cfg["model"])
                            if not isinstance(answer, dict) or answer.get("choice") not in choice["options"]:
                                raise ValueError("Jev returned an out-of-pool Choice")
                            choice.update(status="done", answer=answer)
                            if answer["choice"] == STOP:
                                state["stopped"] = "Jev STOP"
                            else:
                                state["active"] = answer["choice"]
                            save()  # Cache the answer and active evaluation before any execution.
                        except BaseException:
                            choice["status"] = "interrupted" if sys.exc_info()[0] is KeyboardInterrupt else "failed"
                            raise
                        continue
                needed = requirements(pool[active], cfg)
                pending = [j for j in needed if j["id"] not in runs]
                if pending:
                    if len(state["attempts"]) >= state["budget"]:
                        break
                    job = pending[0]
                    # Reconcile immediately before *each* launch, including baselines.
                    reconcile()
                    if job["id"] in runs:
                        continue
                    attempt = dict(job, status="launched")
                    state["attempts"].append(attempt)
                    in_flight = job["id"]
                    save()
                    echo(f"auto-sweeper: {len(state['attempts'])}/{state['budget']} · {job['id']}")
                    try:
                        args = (job, journal.parent / (job["id"].replace(":", "-") + ".log"), echo)
                        if getattr(executor, "owns_child", False) is True:
                            def started(pid):
                                attempt["pid"] = pid
                                save()
                            try:
                                executor.run(*args, started=started)
                            finally:
                                attempt["reaped"] = True
                        else:
                            executor.run(*args)
                        reconcile()
                        if job["id"] not in runs:
                            raise RuntimeError("child exited without a committed exact-key sweep")
                    except BaseException:
                        attempt["status"] = "interrupted" if sys.exc_info()[0] is KeyboardInterrupt else "failed"
                        raise
                    save()
                    in_flight = None
                    continue
                ranking, _, _, _ = score_results(jobs_done(), runs, cfg, pool[active])
                matches = [r for r in ranking if Settings.from_dict(r["settings"]).key == active]
                if len(matches) != 1 or not math.isfinite(matches[0]["score"]):
                    raise RuntimeError("completed config has no unique finite search-report score")
                result = _evidence_row(matches[0], cfg)
                state["evaluations"][active] = result
                value = result["score"]
                if state["best"] is None or value > state["best"] + cfg["margin"]:
                    state["misses"] = 0
                else:
                    state["misses"] += 1
                state["best"] = value if state["best"] is None else max(state["best"], value)
                state["active"] = None
                if cfg["stop_after"] and state["misses"] >= cfg["stop_after"]:
                    state["stopped"] = "no improvement"
                save()
                _write_reports(journal.parent, jobs_done(), runs, cfg)
                echo(f"auto-sweeper: scored {active} · {value:.2f} · {result['verdict']} · "
                     f"confirmation {result['confirmed'] or 'n/a'}")
            save()
            # Rebuild reports after a restart too, including commit-before-checkpoint recovery.
            if state["evaluations"]:
                _write_reports(journal.parent, jobs_done(), runs, cfg)
            return state
        except BaseException as ex:
            state["failure"] = f"{type(ex).__name__}: {ex}"
            state["failure_job"] = in_flight or state["failure_job"]
            save()
            raise
