"""The demo store behind `--demo` (racinglines/cli/source.py, racinglines/demo/store.py, racinglines/demo/mk_demo/generate.py):
the generator writes FastF1-shaped files, the real ingest loads them into a separate database, and the real commands
run on it unchanged. The end-to-end test builds a smaller store (the two newest seasons) into a database next to the
test one and runs the quickstart's commands as subprocesses, with small settings. Skipped without Postgres.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_demo_flag_only_switches_the_source(monkeypatch, tmp_path):
    """`--demo [PACK]` is taken out of argv and points the database, data folder and FastF1 at the pack's store."""
    from racinglines.cli import source
    for k in ("RACINGLINES_DEMO", "RACINGLINES_DEMO_DATABASE_URL", "RACINGLINES_DEMO_DATA", "RACINGLINES_OFFLINE"):
        monkeypatch.setenv(k, "")                                    # restored (removed) after the test ...
        monkeypatch.delenv(k)                                        # ... and unset during it
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db.example:5433/racinglines")
    monkeypatch.setenv("RACINGLINES_DATA", str(tmp_path / "real"))
    built = []
    monkeypatch.setattr(source, "ensure", lambda pk, url, data, console=None: built.append((pk.name, url, data)))
    assert source.apply(["model", "backtest", "f1", "--races", "3"]) == ["model", "backtest", "f1", "--races", "3"]
    assert not built and os.environ.get("RACINGLINES_DEMO") is None
    assert source.apply(["model", "backtest", "f1", "--demo", "--races", "3"]) == ["model", "backtest", "f1", "--races", "3"]
    assert built == [("kart", "postgresql+psycopg://u:p@db.example:5433/racinglines_demo_kart",
                      source.ROOT / "data" / "demo" / "kart")]
    assert os.environ["DATABASE_URL"].endswith("/racinglines_demo_kart") and os.environ["RACINGLINES_OFFLINE"] == "1"
    assert os.environ["RACINGLINES_DEMO"] == "kart"
    assert source.take_demo(["book", "price", "--demo", "kart", "x.toml"]) == (["book", "price", "x.toml"], "kart", True)
    assert source.take_demo(["live", "run", "f1/x", "--demo=kart"]) == (["live", "run", "f1/x"], "kart", True)
    assert source.take_demo(["live", "run", "--demo", "f1/x"]) == (["live", "run", "f1/x"], None, True)   # not a pack
    with pytest.raises(SystemExit, match="no pack"):
        source.pack("nonesuch")
    source.reset()


def _no_config(monkeypatch, tmp_path):
    for k in ("DATABASE_URL", "RACINGLINES_DEMO", "RACINGLINES_DEMO_DATABASE_URL", "RACINGLINES_DEMO_MCP_URL"):
        monkeypatch.setenv(k, "")
        monkeypatch.delenv(k)
    monkeypatch.setenv("RACINGLINES_CLI_CONFIG", str(tmp_path / "cli.toml"))


def test_first_run_asks_once_and_saves_the_source(monkeypatch, tmp_path, capsys):
    """No database configured: the first command that needs one asks local or remote (once, saved as `source`); with no
    terminal it prints both options and exits 2. A configured `db` or DATABASE_URL is used without asking."""
    from racinglines.cli import config as C
    from racinglines.cli import source
    from racinglines.db import config as DBC
    _no_config(monkeypatch, tmp_path)
    assert not source.configured()
    monkeypatch.setattr(sys, "stdin", open(os.devnull))              # no terminal
    with pytest.raises(SystemExit) as ex:
        source.choose_first_run()
    err = capsys.readouterr().err
    assert ex.value.code == 2 and "1) local" in err and "2) remote" in err and "docker compose up -d" in err
    assert not (tmp_path / "cli.toml").exists()
    answers = iter(["x", "1"])
    assert source.choose_first_run(ask=lambda prompt: next(answers)) == "local"
    assert C.load() == {"source": "local"} and source.configured()
    assert source.default_url() == DBC.DEFAULT_URL                    # asked once: no question now
    C.set_key("source", "remote")
    with pytest.raises(SystemExit, match="source is remote"):
        source.default_url()                                          # a database command with the remote source
    C.set_key("db", "postgresql+psycopg://u:p@mine:5432/rl")
    assert source.default_url() == "postgresql+psycopg://u:p@mine:5432/rl"
    try:                                                              # what get_engine() sees while a command runs
        source.apply(["db", "stats"])
        assert DBC.database_url() == "postgresql+psycopg://u:p@mine:5432/rl"
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@env:5432/rl")
        assert DBC.database_url() == "postgresql+psycopg://u:p@env:5432/rl"
    finally:
        source.reset()
    monkeypatch.delenv("DATABASE_URL")
    assert DBC.database_url() == DBC.DEFAULT_URL                      # library callers outside a command


def test_demo_with_the_remote_source_aims_at_the_hosted_store(monkeypatch, tmp_path):
    """`--demo --remote`, or `--demo` with source = remote: the command's own --remote path, at the pack's demo server;
    only the commands the hosted server runs; never a local build."""
    from racinglines.cli import config as C
    from racinglines.cli import source
    _no_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RACINGLINES_MCP_URL", "https://example.invalid/mcp")
    monkeypatch.setattr(source, "ensure", lambda *a, **k: pytest.fail("no local store on the remote source"))
    pk = source.pack("kart")
    assert pk.remote["mcp_url"].startswith("https://")
    assert source.apply(["book", "price", "--demo", "--remote", "--json"]) == ["book", "price", "--remote", "--json"]
    assert os.environ["RACINGLINES_MCP_URL"] == pk.remote["mcp_url"] and os.environ["RACINGLINES_DEMO"] == "kart"
    C.set_key("source", "remote")
    monkeypatch.setenv("RACINGLINES_DEMO_MCP_URL", "http://127.0.0.1:9/mcp")
    assert source.apply(["model", "backtest", "f1", "--demo", "--races", "3"]) == \
        ["model", "backtest", "f1", "--races", "3", "--remote"]
    assert os.environ["RACINGLINES_MCP_URL"] == "http://127.0.0.1:9/mcp"
    with pytest.raises(SystemExit, match="needs a local store"):
        source.apply(["live", "run", "f1/demo-2026-09", "--demo", "--simulate"])
    source.reset()


def test_pack_sport_name_reads_as_its_stored_sport():
    from racinglines.cli import source
    from racinglines.demo import store
    kart = store.find("kart")
    assert (kart.sport, kart.sport_name) == ("f1", "kart")
    assert source.sport_names(kart, ["model", "backtest", "kart", "--races", "3"]) == ["model", "backtest", "f1", "--races", "3"]
    assert source.sport_names(kart, ["live", "run", "kart/demo-2026-09", "--simulate"]) == ["live", "run", "f1/demo-2026-09", "--simulate"]
    assert source.sport_names(kart, ["model", "backtest", "f1"]) == ["model", "backtest", "f1"]     # the stored name still works
    assert source.sport_names(kart, ["book", "price", "karts.toml"]) == ["book", "price", "karts.toml"]


def test_kart_classic_pack_loads_and_answers_to_kart():
    from racinglines.demo import store
    pk = store.find("kart-classic")
    assert pk is not None and (pk.sport, pk.sport_name) == ("f1", "kart") and (pk.path / "world.toml").is_file()


def test_remote_model_flags_map_to_the_hosted_job():
    from racinglines.cli import remote as RM
    assert RM.job_params("f1", "backtest", ["--races", "3", "--sims", "300", "--track", "on", "--remote"]) == \
        ("f1_backtest", {"races": 3, "sims": 300, "track": "on"})
    assert RM.job_params("f1", "forecast", ["--save", "--no-track"]) == ("f1_scenario", {"track": "off", "label": "cli forecast"})
    assert RM.job_params("mtb_dh", "backtest", ["--db", "--half-life-days", "100"]) == ("dh_backtest", {"half_life": 100.0})
    with pytest.raises(RM.RemoteError, match="local only"):
        RM.job_params("f1", "backtest", ["--start-year", "2024"])
    with pytest.raises(RM.RemoteError, match="doesn't run on the hosted server"):
        RM.job_params("nascar", "backtest", [])


def test_generator_writes_fastf1_shapes_reproducibly(tmp_path):
    from racinglines.demo.mk_demo import generate as G
    from racinglines.sources.fastf1 import fetch as F
    w = dict(G.world(), seasons=[2026], raced_2026=2)
    G.write_fastf1(tmp_path / "a", w)
    G.write_fastf1(tmp_path / "b", w)
    a = sorted(p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*.*"))
    assert a == sorted(p.relative_to(tmp_path / "b") for p in (tmp_path / "b").rglob("*.*"))
    assert all((tmp_path / "a" / p).read_bytes() == (tmp_path / "b" / p).read_bytes() for p in a)      # seeded
    res = pd.read_parquet(tmp_path / "a" / "2026" / "01_R.results.parquet")
    laps = pd.read_parquet(tmp_path / "a" / "2026" / "01_R.laps.parquet")
    assert list(res.columns) == F.RESULT_COLS and list(laps.columns) == F.LAP_COLS
    assert len(res) == 20 and res["Points"].sum() == sum(G.RACE_POINTS)
    meta = json.loads((tmp_path / "a" / "2026" / "01_R.meta.json").read_text())
    assert meta["synthetic"] and meta["location"] == "Mario Kart Stadium"
    sch = pd.read_parquet(tmp_path / "a" / "2026" / "schedule.parquet")
    assert list(sch.columns) == F.SCHEDULE_COLS and len(sch) == w["rounds"]



def test_no_generated_lap_beats_a_world_record():
    """The kart world's tracks are Mario Kart 8 Deluxe courses: every lap the generator writes, in every session of
    every raced weekend, is slower than the course's fastest 150cc record lap (world.toml wr_lap_s)."""
    from racinglines.demo.mk_demo import generate as G
    w = G.world()
    W = G.World(w)
    for year, rnd, tr, day, sprint in G.calendar(w):
        if not G.raced(w, year, rnd):
            continue
        assert tr["lap_s"] > tr["wr_lap_s"] and tr["wr_race_s"] > 3 * tr["wr_lap_s"]
        for code, (_, laps, _) in G.weekend(W, year, rnd, tr, day, sprint).items():
            assert laps["LapTime"].min() > tr["wr_lap_s"], (year, rnd, tr["name"], code)


def test_offline_schedule_reads_the_saved_copy(tmp_path, monkeypatch):
    """RACINGLINES_OFFLINE=1: the schedule comes from data/raw/f1/fastf1/<year>/schedule.parquet, FastF1 never called."""
    from racinglines.demo.mk_demo import generate as G
    from racinglines.models.inputs import laps_pricing as P
    from racinglines.sources.fastf1 import fetch as F
    (tmp_path / "2026").mkdir()
    G.schedule(G.world(), 2026).to_parquet(tmp_path / "2026" / "schedule.parquet", index=False)
    monkeypatch.setattr(F, "OUT", tmp_path)
    monkeypatch.setenv("RACINGLINES_OFFLINE", "1")
    monkeypatch.setitem(sys.modules, "fastf1", None)                 # an import would fail
    s = P.upcoming_schedule(2026)
    assert s.loc[s["round"] == 10, "location"].item() == "Rainbow Road" and s.loc[s["round"] == 10, "sprint"].item()
    with pytest.raises(FileNotFoundError):
        F.event_schedule(2031)


def _run(env, *args, timeout=900):
    p = subprocess.run([sys.executable, "-m", "racinglines", *args], cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=timeout)
    assert p.returncode == 0, f"{args}: {p.stdout[-2000:]}\n{p.stderr[-3000:]}"
    return p.stdout


def _drop(url):
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    eng = create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{make_url(url).database}" WITH (FORCE)'))
    eng.dispose()


def _store(test_engine, tmp_path_factory, name, pack_ref, options=None, packs_dir=None):
    """A pack's store in a database next to the test one, and the environment that points --demo at it."""
    from sqlalchemy.engine import make_url

    from racinglines.demo import store
    url = make_url(test_engine.url.render_as_string(hide_password=False)).set(database=name)
    url = url.render_as_string(hide_password=False)
    data = tmp_path_factory.mktemp(name) / "demo"
    old = os.environ.get("RACINGLINES_DEMO_PACKS")
    if packs_dir:
        os.environ["RACINGLINES_DEMO_PACKS"] = str(packs_dir)
    try:
        summary = store.build(store.find(pack_ref), url, data, options=options)
    except Exception as ex:                                          # noqa: BLE001
        pytest.skip(f"no Postgres for the demo store: {ex}")
    finally:
        if packs_dir:
            os.environ.pop("RACINGLINES_DEMO_PACKS") if old is None else os.environ.update(RACINGLINES_DEMO_PACKS=old)
    env = dict(os.environ, DATABASE_URL=test_engine.url.render_as_string(hide_password=False),   # configured: no first-run question
               RACINGLINES_DEMO_DATABASE_URL=url, RACINGLINES_DEMO_DATA=str(data),
               RACINGLINES_PROGRESS_SEC="0", RACINGLINES_CLI_CONFIG=str(data.parent / "cli.toml"), COLUMNS="160")
    if packs_dir:
        env["RACINGLINES_DEMO_PACKS"] = str(packs_dir)
    env.pop("RACINGLINES_DEMO", None)
    return url, env, summary


@pytest.fixture(scope="module")
def demo_env(test_engine, tmp_path_factory):
    """The kart pack's store, smaller (2025 and 2026 only)."""
    url, env, summary = _store(test_engine, tmp_path_factory, "racinglines_test_demo", "kart",
                               options=dict(seasons=2, quote_sims=60))
    yield env, summary
    _drop(url)


def test_store_is_built_by_the_real_ingest(demo_env):
    env, summary = demo_env
    from sqlalchemy import create_engine, text
    assert summary["pack"] == "kart" and summary["generated"]["weekends"] == 12 + 9
    eng = create_engine(env["RACINGLINES_DEMO_DATABASE_URL"])
    with eng.connect() as c:
        n = dict(c.execute(text("""SELECT ro.kind, count(*) FROM results r JOIN rounds ro ON ro.id = r.round_id
                                   GROUP BY 1""")).all())
        links = dict(c.execute(text("SELECT exchange, count(race_id) FROM market_links GROUP BY 1")).all())
        profiles = c.execute(text("SELECT count(*) FROM track_profiles WHERE features ? 'speed_index'")).scalar()
        names = set(c.execute(text("SELECT display_name FROM athletes")).scalars())
    eng.dispose()
    assert n["race"] == 21 * 20 and n["qual"] == 21 * 20 and n["sprint"] == 5 * 20      # sprints: 2025 R3/6/10, 2026 R3/6
    assert set(links) == {"polymarket", "kalshi"} and min(links.values()) > 20 and profiles == 21
    assert {"Mario", "Luigi", "Peach", "Bowser"} <= names and len(names) == 20


def test_kart_quickstart_runs_on_the_store(demo_env):
    """The kart pack's quickstart (docs/quickstart.md), small settings where a command has them: the real commands,
    unchanged, on the demo store."""
    from racinglines.demo import store
    env, _ = demo_env
    small = {"model backtest kart": ["--races", "3", "--sims", "300", "--track", "on"], "model forecast kart": ["--sims", "500"],
             "live run kart/demo-2026-09": ["--tick", "60"]}                 # hourly steps, not 5-minute ones
    outs = []
    for step in store.find("kart").quickstart:
        if not step.get("record", True):                                 # the install step: shown, never run
            continue
        argv = step["run"].split()[1:]
        outs.append(_run(env, *argv, *small.get(" ".join(argv[:3]), [])))
    outs.append(_run(env, "live", "report", "f1/demo-2026-09", "--demo"))   # not in the kart quickstart, still works
    joined = "\n".join(outs)
    assert "Track features ON: mean over 3 races" in joined and "Saved forecast run" in joined
    assert "2026-09 results:" in joined and "simulated 2026-09" in joined
    assert (Path(env["RACINGLINES_DEMO_DATA"]) / "runs" / "live" / "demo-2026-09" / "report" / "report.md").exists()
    price = json.loads(_run(env, "book", "price", "--demo", "--json"))
    lines = {r["id"]: r for r in price["lines"]}
    assert lines["win"]["model_prob"] is not None and lines["win"]["market_prob"] is not None
    assert lines["p2"]["model_prob"] is None and lines["p2"]["legs"][0]["market_exchange"] == "kalshi"
    assert price["unmapped"] == ["typo"]


def _free_port():
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_remote_demo_runs_on_a_hosted_demo_store(test_engine, demo_env, tmp_path):
    """`--demo --remote` (and `source = "remote"`): the hosted demo server is the VM's command, `racinglines mcp --http
    --demo` (scripts/vm/demo_store.sh), over the demo store, with the accounts read from another database
    (RACINGLINES_MCP_ACCOUNTS_URL, production's on the VM, the test database here). A Pro account's rl_ token prices
    the pack's book and runs the backtest and forecast as hosted jobs; nothing touches a local store."""
    import time
    import urllib.request
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    from racinglines.cli import remote as RM
    from racinglines.mcp import auth
    from racinglines.web import users as U
    env, _ = demo_env
    with sessionmaker(test_engine)() as s:
        if not s.execute(text("SELECT 1 FROM users WHERE username = 'demo_pro'")).first():
            U.create_user(s, "demo_pro", "pw", "pro")
        s.commit()
    tok = auth.new_token(test_engine, "demo_pro")
    port = _free_port()
    mcp = f"http://127.0.0.1:{port}/mcp"
    accounts = test_engine.url.render_as_string(hide_password=False)
    srv_env = dict(env, APP_SECRET="test-secret", RACINGLINES_MCP_ACCOUNTS_URL=accounts, RACINGLINES_MCP_URL=mcp)
    log = open(tmp_path / "mcp.log", "w")
    srv = subprocess.Popen([sys.executable, "-m", "racinglines", "mcp", "--http", "--port", str(port), "--demo"],
                           cwd=ROOT, env=srv_env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(200):
            try:
                urllib.request.urlopen(urllib.request.Request(mcp, method="POST", data=b"{}"), timeout=1)
            except urllib.error.HTTPError:
                break                                                # 401: up
            except OSError:
                time.sleep(0.1)
        cli = dict(env, RACINGLINES_DEMO_MCP_URL=mcp, RACINGLINES_MCP_TOKEN=tok,
                   RACINGLINES_DEMO_DATABASE_URL="postgresql+psycopg://nobody:x@127.0.0.1:1/racinglines_demo_nowhere")
        p = subprocess.run([sys.executable, "-m", "racinglines", "book", "price", "--demo", "--remote", "--json"],
                           cwd=ROOT, env=cli, capture_output=True, text=True, timeout=300)
        assert p.returncode == 0, p.stderr[-3000:] + (tmp_path / "mcp.log").read_text()[-3000:]
        assert p.stderr.startswith(RM.WARNING) and p.stderr.count("#aintcare") == 1
        lines = {r["id"]: r for r in json.loads(p.stdout)["lines"]}             # stdout: clean JSON
        assert lines["win"]["market_prob"] is not None and json.loads(p.stdout)["unmapped"] == ["typo"]
        (Path(cli["RACINGLINES_CLI_CONFIG"])).write_text('source = "remote"\n')        # the defaults file's source
        out = _run(cli, "model", "backtest", "f1", "--demo", "--races", "3", "--sims", "300", "--track", "on")
        assert "Track features ON: mean over 3 races" in out
        out = _run(cli, "model", "forecast", "f1", "--demo", "--sims", "1000")
        assert "Saved" in out and "scenario" in out.lower()
        bad = subprocess.run([sys.executable, "-m", "racinglines", "db", "stats", "--demo"], cwd=ROOT, env=cli,
                             capture_output=True, text=True, timeout=120)
        assert bad.returncode != 0 and "needs a local store" in bad.stderr
        bad = subprocess.run([sys.executable, "-m", "racinglines", "model", "backtest", "f1", "--demo", "--variant", "x"],
                             cwd=ROOT, env=cli, capture_output=True, text=True, timeout=120)
        assert bad.returncode == 2 and "local only" in bad.stderr
    finally:
        srv.terminate()
        srv.wait(20)
        log.close()


TINY_DH = """name = "tinydh"
title = "Tiny downhill (test fixture)"
sport = "mtb_dh"
files = "files"

[load]
commands = ["racinglines data ingest mtb_dh"]

[[quickstart]]
title = "Backtest"
section = "Model"
run = "racinglines model backtest mtb_dh --demo tinydh --db --sims 200"

[[quickstart]]
title = "Forecast"
section = "Race week"
run = "racinglines model forecast mtb_dh --demo tinydh --db"

[[quickstart]]
title = "Look at the store"
section = "Model"
run = "racinglines db stats --demo tinydh"
"""


def test_quickstart_sections_group_with_no_code(tmp_path, monkeypatch):
    """[[quickstart]] entries' optional `section` key: one heading per section in first-seen order in the rendered doc
    and in --commands; a pack with none (kart) renders as one plain list."""
    import importlib.util
    from racinglines.demo import store
    (tmp_path / "tinydh").mkdir()
    (tmp_path / "tinydh" / "pack.toml").write_text(TINY_DH)
    monkeypatch.setenv("RACINGLINES_DEMO_PACKS", str(tmp_path))
    spec = importlib.util.spec_from_file_location("build_quickstart", ROOT / "scripts" / "build_quickstart.py")
    BQ = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(BQ)
    pk = store.find("tinydh")
    assert [(n, [s["title"] for s in steps]) for n, steps in pk.sections()] == \
        [("Model", ["Backtest", "Look at the store"]), ("Race week", ["Forecast"])]
    md = BQ.render(pk)
    assert md.index("### Model") < md.index("#### Step 1: Backtest") < md.index("#### Step 2: Look at the store") \
        < md.index("### Race week") < md.index("#### Step 1: Forecast")
    assert "####" not in BQ.render(store.find("kart")) and [n for n, _ in store.find("kart").sections()] == [""]
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_quickstart.py"), "--commands", "tinydh",
                        "--section", "Race week"], capture_output=True, text=True, env=dict(os.environ))
    assert p.returncode == 0 and p.stdout.split("\n")[0] == "racinglines model forecast mtb_dh --demo tinydh --db"


def test_a_second_pack_needs_no_code(test_engine, tmp_path_factory):
    """A pack under another sport (a few synthetic downhill results, ChronoRace's format) goes through the same
    resolver and builder, and its quickstart runs: adding a pack is adding a folder."""
    from racinglines.testing import synthetic as SY
    packs = tmp_path_factory.mktemp("packs")
    raw = packs / "tinydh" / "files" / "raw" / "mtb_dh" / "chronorace"
    raw.mkdir(parents=True)
    (packs / "tinydh" / "pack.toml").write_text(TINY_DH)
    for name, text in SY.mtb_results_md(n_events=4, n_riders=24).items():
        (raw / name).write_text(text)
    url, env, summary = _store(test_engine, tmp_path_factory, "racinglines_test_demo_dh", "tinydh", packs_dir=packs)
    try:
        assert summary["sport"] == "mtb_dh"
        from racinglines.demo import store
        os.environ["RACINGLINES_DEMO_PACKS"] = str(packs)
        try:
            steps = store.find("tinydh").quickstart
        finally:
            os.environ.pop("RACINGLINES_DEMO_PACKS")
        out = _run(env, *steps[0]["run"].split()[1:])
        assert "2026" in out
    finally:
        _drop(url)


def test_quickstart_doc_is_rendered_from_the_pack():
    """docs/quickstart.md's command blocks come from the pack manifests (scripts/build_quickstart.py)."""
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_quickstart.py"), "--check"], capture_output=True,
                       text=True)
    assert p.returncode == 0, p.stderr
