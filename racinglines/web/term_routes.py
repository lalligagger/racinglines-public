"""
/term: the demo pack's quickstart, recorded and replayed in the browser, public like /pitch (PUBLIC_PATHS in
web/app.py). No shell runs here: scripts/demo/record_term.py runs the quickstart's commands once, snapshots the list
(racinglines/web/term/quickstart.json) and saves each command's output as an HTML fragment. Each replay waits paused on
its full command; Play types it and plays the output, one step at a time, so a reader can follow along in their own
shell. Steps with a pack `section` group under it (the quickstart's parts).
"""

import itertools
import json
import tomllib
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse

from racinglines.web.app import app, render

TERM = Path(__file__).resolve().parent / "term"


def demos():
    """[step dict + `html`, its recorded output] in quickstart order; a step not yet rendered is left out."""
    f = TERM / "quickstart.json"
    out = []
    for d in json.loads(f.read_text()) if f.is_file() else []:
        h = TERM / f"{d['id']}.html"
        if h.is_file():
            out.append(dict(d, html=h.read_text()))
    return out


@app.get("/term", response_class=HTMLResponse)
def term(request: Request):
    recorded = tomllib.loads((TERM / "demos.toml").read_text()).get("recorded", "")
    ds = demos()
    parts = [(k, list(g)) for k, g in itertools.groupby(ds, lambda d: d.get("section", ""))]
    return render(request, "term.html", demos=ds, parts=parts, recorded=recorded)
