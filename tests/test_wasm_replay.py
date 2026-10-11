"""The maker replay the browser runs (racinglines/web/static/replay.wasm, built from wasm/ by wasm/build.sh) gives
the Python replay's results: the per-kind summary, the stages and the skip reasons, for every fill rule and option it
supports. Runs the committed .wasm through its browser interface under Node; skipped where node is missing. After a
change to maker_replay.replay or wasm/src/lib.rs, rebuild with wasm/build.sh and run this."""

import json
import math
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from racinglines.markets import settlement_rules as SR
from racinglines.markets.strategies import maker_replay as R
from racinglines.markets.strategies.replay_json import event_json, params_json
from racinglines.testing import synthetic as SY

from test_replay_parity import VARIANTS, _two_stages

ROOT = Path(__file__).resolve().parents[1]
WASM = ROOT / "racinglines/web/static/replay.wasm"
COLUMNS = ("markets", "quoted_share", "fills", "shares", "notional", "spread_pnl", "markout_60m", "model_edge", "pnl",
           "worst_case")

# The browser's calls (static/replay.js) under Node: alloc + load the event once, then run() per params set.
RUNNER = r"""
const fs = require("fs");
const [wasm, evPath, callsPath] = process.argv.slice(1);
const x = new WebAssembly.Instance(new WebAssembly.Module(fs.readFileSync(wasm)), {}).exports;
const enc = new TextEncoder(), dec = new TextDecoder();
function call(fn, text) {
  const b = enc.encode(text), p = x.alloc(b.length);
  new Uint8Array(x.memory.buffer, p, b.length).set(b);
  try { return fn(p, b.length); } finally { x.dealloc(p, b.length); }
}
if (call(x.load, fs.readFileSync(evPath, "utf8")) !== 0) throw new Error("load failed");
const out = JSON.parse(fs.readFileSync(callsPath, "utf8")).map(p => {
  const ptr = call(x.run, JSON.stringify(p));
  return JSON.parse(dec.decode(new Uint8Array(x.memory.buffer, ptr, x.result_len())));
});
process.stdout.write(JSON.stringify(out));
"""

needs_node = pytest.mark.skipif(shutil.which("node") is None or not WASM.exists(), reason="needs node and replay.wasm")


def _run_wasm(tmp_path, ev, params):
    (tmp_path / "ev.json").write_text(json.dumps(event_json(ev)))
    (tmp_path / "calls.json").write_text(json.dumps([params_json(p) for p in params]))
    out = subprocess.run(["node", "-e", RUNNER, str(WASM), str(tmp_path / "ev.json"), str(tmp_path / "calls.json")],
                         capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout)


def _close(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)


def _check(ev, p, w):
    assert "error" not in w, w
    res = R.replay(ev, p)
    s = R.summary(res)
    assert [r["kind"] for r in w["summary"]] == list(s.index)
    for row in w["summary"]:
        for col in COLUMNS:
            assert _close(row[col], s.loc[row["kind"], col]), (row["kind"], col, row[col], s.loc[row["kind"], col])
    st = R.by_stage(res, ev)
    assert [r["run_id"] for r in w["stages"]] == list(st["run_id"])
    for row, (_, py) in zip(w["stages"], st.iterrows()):
        for col in ("fills", "notional", "spread_pnl", "markout_60m", "model_edge", "pnl"):
            assert _close(row[col], py[col]), (row["run_id"], col)
    assert dict(w["skips"]) == R.skip_reasons(res).to_dict()
    assert w["fills"] == len(res["fills"]) and w["quotes"] == len(res["quotes"])


def _mixed(ev):
    """Two market kinds and every kind of outcome the replay settles: payout, void, fair (undecided) and none."""
    for i, mk in enumerate(ev["markets"]):
        mk.kind = "race_podium" if i % 2 else "race_win"
    outcomes = [SR.VOID, SR.FAIR, 0.5, None]
    for mk, o in zip(ev["markets"], outcomes):
        mk.outcome = o
    return ev


@needs_node
@pytest.mark.parametrize("seed", [1, 7, 42])
def test_browser_replay_matches_python(tmp_path, seed):
    ev = _mixed(_two_stages(SY.replay_markets(n=8, seed=seed)))
    params = list(VARIANTS.values()) + [replace(VARIANTS["skew-kind"], half_spread_by_kind={"race_podium": 0.04})]
    for p, w in zip(params, _run_wasm(tmp_path, ev, params)):
        _check(ev, p, w)


@needs_node
def test_bad_params_come_back_as_an_error(tmp_path):
    ev = _two_stages(SY.replay_markets(n=2, seed=1))
    (tmp_path / "ev.json").write_text(json.dumps(event_json(ev)))
    (tmp_path / "calls.json").write_text(json.dumps([dict(fill="queue")]))
    out = subprocess.run(["node", "-e", RUNNER, str(WASM), str(tmp_path / "ev.json"), str(tmp_path / "calls.json")],
                         capture_output=True, text=True, timeout=60, check=True)
    assert "touch or through" in json.loads(out.stdout)[0]["error"]


def test_params_json_refuses_the_queue_fill():
    with pytest.raises(ValueError):
        params_json(R.Params(fill="queue"))


def test_the_tape_route_sends_gzip_or_plain_json(monkeypatch):
    import gzip

    import pandas as pd
    from fastapi import Request
    from fastapi.testclient import TestClient

    from racinglines.web import app as A
    from racinglines.web import diag
    from racinglines.web import diag_routes  # noqa: F401  (registers the route)

    def as_pro(request: Request):
        request.state.user = dict(id=1, username="tester", role="pro", sid=None)
        return request.state.user
    monkeypatch.setitem(A.app.dependency_overrides, A.authenticate, as_pro)
    monkeypatch.setitem(A.app.dependency_overrides, A.conn, lambda: None)
    body = gzip.compress(b'{"event": {}}')
    monkeypatch.setattr(diag, "event_runs", lambda c, run_id: pd.DataFrame({"id": [7] if run_id == 7 else []}))
    monkeypatch.setattr(diag, "tape", lambda c, run_id, exchange: body)
    client = TestClient(A.app)
    r = client.get("/lab/diagnostics/7/tape.json", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip" and r.json() == {"event": {}}
    r = client.get("/lab/diagnostics/7/tape.json", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200 and "content-encoding" not in r.headers and r.json() == {"event": {}}
    assert client.get("/lab/diagnostics/8/tape.json").status_code == 404
