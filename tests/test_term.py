"""The public /term page: recorded CLI runs (racinglines/web/term/demos.toml), and the recorder that renders them."""

import html
import importlib.util
import json
from pathlib import Path

import pytest

from racinglines.web import term_routes

ROOT = Path(__file__).resolve().parents[1]


def _recorder():
    spec = importlib.util.spec_from_file_location("record_term", ROOT / "scripts" / "demo" / "record_term.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_term_is_public_and_shows_each_recorded_command():
    from fastapi.testclient import TestClient

    from racinglines.web.app import app
    cl = TestClient(app)
    old = cl.get("/term", follow_redirects=False)
    assert old.status_code == 307 and old.headers["location"] == "/docs/quickstart/term"
    r = cl.get("/docs/quickstart/term", follow_redirects=False)
    assert r.status_code == 200
    for d in term_routes.demos():
        assert html.escape(d["command"], quote=False) in r.text and f'id="{d["id"]}"' in r.text
    if not term_routes.demos():
        assert "No recordings yet" in r.text


def test_every_demo_has_saved_output_and_a_render_that_matches_it():
    rec = _recorder()
    for d in rec.demos():
        if not d.get("record", True):                                            # shown, never run (pack.toml)
            assert (term_routes.TERM / f"{d['id']}.html").read_text() == ""
            continue
        ansi = (term_routes.TERM / f"{d['id']}.ansi").read_text()
        assert ansi.strip() and "/home/" not in ansi and "/tmp/" not in ansi     # paths read relative to the repo
        # the committed fragment is what the recorder makes from the committed output (re-record after any change)
        assert (term_routes.TERM / f"{d['id']}.html").read_text() == rec.render(d)


def test_the_page_replays_the_packs_quickstart_as_written():
    # one source: the recorded list is the pack manifest's [[quickstart]] (docs/quickstart.md is built from it too)
    store = pytest.importorskip("racinglines.demo.store")
    rec = _recorder()
    pack = rec.config().get("pack", "kart")
    if store.find(pack) is None:
        pytest.skip(f"no {pack} demo pack in this checkout")
    recorded = json.loads((term_routes.TERM / "quickstart.json").read_text())
    assert recorded == rec.quickstart(pack), "re-record: python scripts/demo/record_term.py --run"
    for name in rec.config().get("parts", []):      # an extra part, once recorded, is its steps file as written
        f = term_routes.TERM / f"{name}.json"
        if f.is_file():
            want = {d["id"]: d for d in rec.part(name)}       # an optional group may have been left out
            assert all(want.get(d["id"]) == d for d in json.loads(f.read_text())), f"re-record on the VM: {name}"


def test_extra_parts_follow_the_pack_and_its_steps_take_the_default_section(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from racinglines.web.app import app
    (tmp_path / "quickstart.json").write_text(json.dumps([{"id": "step-1", "title": "k", "command": "racinglines k",
                                                           "about": ""}]))
    (tmp_path / "f1.json").write_text(json.dumps([{"id": "f1-1", "title": "f", "command": "racinglines f", "about": "",
                                                   "section": "F1 part"}]))
    for i in ("step-1", "f1-1"):
        (tmp_path / f"{i}.html").write_text("<pre>out</pre>")
    (tmp_path / "demos.toml").write_text('recorded = "x"\nsection = "Kart"\nparts = ["f1", "missing"]\n')
    monkeypatch.setattr(term_routes, "TERM", tmp_path)
    assert [(d["id"], d["section"]) for d in term_routes.demos()] == [("step-1", "Kart"), ("f1-1", "F1 part")]
    html = TestClient(app).get("/docs/quickstart/term").text
    assert "data-term-parts" in html and "Next: Part 2, F1 part" in html


def test_a_part_records_in_one_folder_to_out(tmp_path, monkeypatch):
    """--part runs its steps one after another in one fresh folder (a file one step writes is there for the next) and
    --out saves the recording there, not in the checkout."""
    rec = _recorder()
    term = tmp_path / "term"
    term.mkdir()
    (term / "demos.toml").write_text('parts = ["p"]\n')
    (term / "p.toml").write_text('[[steps]]\nsection = "P"\ntitle = "a"\nrun = "touch made.txt"\n'
                                 '[[steps]]\nsection = "P"\ntitle = "b"\nrun = "ls made.txt"\n')
    monkeypatch.setattr(rec, "TERM", term)
    out = tmp_path / "out"
    rec.main(["--run", "--part", "p", "--out", str(out)])
    assert sorted(f.name for f in out.iterdir()) == ["p-1.ansi", "p-2.ansi", "p.json"]
    assert "made.txt" in (out / "p-2.ansi").read_text()
    assert [d["id"] for d in json.loads((out / "p.json").read_text())] == ["p-1", "p-2"]
    assert sorted(f.name for f in term.iterdir()) == ["demos.toml", "p.toml"]           # the checkout is untouched
    with pytest.raises(SystemExit):
        rec.main(["--run", "--part", "nope", "--out", str(out)])


def test_a_demo_not_yet_rendered_is_left_out(tmp_path, monkeypatch):
    (tmp_path / "quickstart.json").write_text('[{"id": "nope", "title": "t", "command": "c", "about": ""}]')
    monkeypatch.setattr(term_routes, "TERM", tmp_path)
    assert term_routes.demos() == []


def test_terminal_links_never_reach_the_page(tmp_path, monkeypatch):
    rec = _recorder()
    (tmp_path / "x.ansi").write_text("\x1b]8;;javascript:alert(1)\x1b\\click\x1b]8;;\x1b\\ ok\x1b]8;;https://e.x\x07b\x1b]8;;\x07\n")
    monkeypatch.setattr(rec, "TERM", tmp_path)
    html = rec.render({"id": "x"})
    assert "click" in html and "javascript" not in html and "<a " not in html and "href" not in html


def test_steps_group_under_their_section_and_wait_on_play(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from racinglines.web.app import app
    steps = [{"id": f"s{i}", "title": f"t{i}", "command": f"racinglines c{i}", "about": "", "section": sec}
             for i, sec in enumerate(["Part one", "Part one", "Part two"], 1)]
    (tmp_path / "quickstart.json").write_text(json.dumps(steps))
    for s in steps:     # s3 is shown but not run (pack record = false): an empty fragment
        (tmp_path / f"{s['id']}.html").write_text("" if s["id"] == "s3" else "<pre>out</pre>")
    (tmp_path / "demos.toml").write_text('recorded = "x"\n')
    monkeypatch.setattr(term_routes, "TERM", tmp_path)
    html = TestClient(app).get("/docs/quickstart/term").text
    assert html.count('class="term-part"') == 2 and html.index("Part one") < html.index("Part two")
    assert "1. t1" in html and "2. t2" in html and "1. t3" in html       # numbered within each part
    assert html.count("data-term-play") == 3                             # each step waits paused on Play
    assert html.count("data-term-out") == 2 and "racinglines c3" in html  # the unrun step is its command only
    # two parts: a part nav (tabs on a phone, a sidebar when wide), each part its own box, a link on to the next
    assert "data-term-parts" in html and html.count('data-term-tab="part-') == 3     # 2 tabs + 1 "next"
    assert 'id="part-1"' in html and 'id="part-2"' in html and "Next: Part 2, Part two" in html


def test_a_failed_run_keeps_the_saved_recording(tmp_path, monkeypatch):
    rec = _recorder()
    (tmp_path / "step-1.ansi").write_text("old")
    (tmp_path / "quickstart.json").write_text("[]")
    monkeypatch.setattr(rec, "TERM", tmp_path)
    monkeypatch.setattr(rec, "config", dict)
    monkeypatch.setattr(rec, "quickstart", lambda pack: [{"id": "step-1", "title": "t", "command": "false", "about": ""}])
    with pytest.raises(SystemExit):
        rec.main(["--run"])
    assert (tmp_path / "step-1.ansi").read_text() == "old" and (tmp_path / "quickstart.json").read_text() == "[]"


def test_replay_is_public_by_exact_path_only(tmp_path, monkeypatch):
    """/docs/quickstart/term is public, but not as a prefix: /docs/quickstart/term/../../webapp/ reaches the /docs
    catch-all, which resolves the dots inside site/, so it must need a session. Sent as a raw ASGI path, since
    TestClient normalizes the dots away."""
    import asyncio

    from racinglines.web import info_routes
    from racinglines.web.app import app
    (tmp_path / "webapp").mkdir()
    (tmp_path / "index.html").write_text("docs")
    (tmp_path / "webapp" / "index.html").write_text("webapp docs")
    monkeypatch.setattr(info_routes, "SITE", tmp_path)          # a built docs site, so the catch-all would serve it

    async def status(path):
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            if msg["type"] == "http.response.start":
                sent.append(msg["status"])
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
                 "headers": [(b"host", b"testserver")], "client": ("127.0.0.1", 1), "server": ("testserver", 80)}
        await app(scope, receive, send)
        return sent[0]
    assert asyncio.run(status("/docs/quickstart/term")) == 200
    for path in ("/docs/quickstart/term/../../webapp/", "/docs/quickstart/term/../../"):
        assert asyncio.run(status(path)) in (303, 307, 401, 404), path      # sent to sign in, or not found



def test_an_optional_step_that_fails_drops_its_group_only(tmp_path, monkeypatch):
    rec = _recorder()
    term = tmp_path / "term"
    term.mkdir()
    (term / "demos.toml").write_text('parts = ["p"]\n')
    (term / "p.toml").write_text('[[steps]]\ntitle = "a"\nrun = "false"\ngroup = "k"\noptional = true\n'
                                 '[[steps]]\ntitle = "b"\nrun = "echo k2"\ngroup = "k"\n'
                                 '[[steps]]\ntitle = "c"\nrun = "echo pm"\ngroup = "pm"\n')
    monkeypatch.setattr(rec, "TERM", term)
    out = tmp_path / "out"
    rec.main(["--run", "--part", "p", "--out", str(out)])
    assert [d["id"] for d in json.loads((out / "p.json").read_text())] == ["p-3"]
    assert sorted(f.name for f in out.iterdir()) == ["p-3.ansi", "p.json"]


def test_a_part_whose_every_group_failed_saves_nothing(tmp_path, monkeypatch):
    rec = _recorder()
    term = tmp_path / "term"
    term.mkdir()
    (term / "demos.toml").write_text('parts = ["p"]\n')
    (term / "p.toml").write_text('[[steps]]\ntitle = "a"\nrun = "false"\ngroup = "k"\noptional = true\n')
    monkeypatch.setattr(rec, "TERM", term)
    with pytest.raises(SystemExit):
        rec.main(["--run", "--part", "p", "--out", str(tmp_path / "out")])
    assert not (tmp_path / "out" / "p.json").exists()
