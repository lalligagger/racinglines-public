"""
/term: recorded CLI runs replayed in the browser, public like /pitch (PUBLIC_PATHS in web/app.py). No shell runs
here: each demo is a saved result (racinglines/web/term/demos.toml) rendered once by the CLI's own Rich renderer
(scripts/demo/record_term.py) into an HTML fragment, which the page types out after its command.
"""

import tomllib
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse

from racinglines.web.app import app, render

TERM = Path(__file__).resolve().parent / "term"


def demos():
    """[demo dict + `html`, the recorded output] in demos.toml order; a demo not yet rendered is left out."""
    out = []
    for d in tomllib.loads((TERM / "demos.toml").read_text()).get("demo", []):
        f = TERM / f"{d['id']}.html"
        if f.is_file():
            out.append(dict(d, html=f.read_text()))
    return out


@app.get("/term", response_class=HTMLResponse)
def term(request: Request):
    return render(request, "term.html", demos=demos())
