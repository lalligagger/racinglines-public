"""The public /term page: recorded CLI runs (racinglines/web/term/demos.toml), and the recorder that renders them."""

import importlib.util
import json
import tomllib
from pathlib import Path

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
    for d in tomllib.loads((term_routes.TERM / "demos.toml").read_text()).get("demo", []):
        assert d["command"] in r.text and f'id="{d["id"]}"' in r.text
    if not term_routes.demos():
        assert "No recordings yet" in r.text


def test_every_demo_has_a_saved_result_and_a_render_that_matches_it():
    rec = _recorder()
    for d in rec.demos():
        out = json.loads((term_routes.TERM / d["result"]).read_text())
        assert out["lines"] and d["render"] in ("map", "price", "settle")
        # the committed fragment is what the recorder makes from the committed result (re-record after any change)
        assert (term_routes.TERM / f"{d['id']}.html").read_text() == rec.render(d)


def test_a_demo_not_yet_rendered_is_left_out(tmp_path, monkeypatch):
    (tmp_path / "demos.toml").write_text('[[demo]]\nid = "nope"\ntitle = "t"\ncommand = "c"\n')
    monkeypatch.setattr(term_routes, "TERM", tmp_path)
    assert term_routes.demos() == []
