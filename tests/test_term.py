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
    r = TestClient(app).get("/term", follow_redirects=False)
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
    assert rec.demos() == rec.quickstart(pack), "re-record: python scripts/demo/record_term.py --run"


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
    html = TestClient(app).get("/term").text
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
