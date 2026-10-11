"""The demo store behind `--demo` (racinglines/cli/source.py, racinglines/demo/store.py, racinglines/demo/generate.py):
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


def test_generator_writes_fastf1_shapes_reproducibly(tmp_path):
    from racinglines.demo import generate as G
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
    assert meta["synthetic"] and meta["location"] == "Mario Circuit"
    sch = pd.read_parquet(tmp_path / "a" / "2026" / "schedule.parquet")
    assert list(sch.columns) == F.SCHEDULE_COLS and len(sch) == w["rounds"]


def test_offline_schedule_reads_the_saved_copy(tmp_path, monkeypatch):
    """RACINGLINES_OFFLINE=1: the schedule comes from data/raw/f1/fastf1/<year>/schedule.parquet, FastF1 never called."""
    from racinglines.demo import generate as G
    from racinglines.models.position_sim import pricing as P
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
    env = dict(os.environ, RACINGLINES_DEMO_DATABASE_URL=url, RACINGLINES_DEMO_DATA=str(data),
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
    small = {"model backtest f1": ["--races", "3", "--sims", "300", "--track", "on"], "model forecast f1": ["--sims", "500"]}
    outs = []
    for step in store.find("kart").quickstart:
        argv = step["run"].split()[1:]
        outs.append(_run(env, *argv, *small.get(" ".join(argv[:3]), [])))
    joined = "\n".join(outs)
    assert "Track features ON: mean over 3 races" in joined and "Saved forecast run" in joined
    assert "2026-09 results:" in joined and "simulated 2026-09" in joined
    assert (Path(env["RACINGLINES_DEMO_DATA"]) / "runs" / "live" / "demo-2026-09" / "report" / "report.md").exists()
    price = json.loads(_run(env, "book", "price", "--demo", "--json"))
    lines = {r["id"]: r for r in price["lines"]}
    assert lines["win"]["model_prob"] is not None and lines["win"]["market_prob"] is not None
    assert lines["p2"]["model_prob"] is None and lines["p2"]["legs"][0]["market_exchange"] == "kalshi"
    assert price["unmapped"] == ["typo"]


TINY_DH = """name = "tinydh"
title = "Tiny downhill (test fixture)"
sport = "mtb_dh"
files = "files"

[load]
commands = ["racinglines data ingest mtb_dh"]

[[quickstart]]
title = "Backtest"
run = "racinglines model backtest mtb_dh --demo tinydh --db --sims 200"
"""


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
