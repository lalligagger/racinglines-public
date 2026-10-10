"""
/mybets: the owner's personal bets calendar, a standalone HTML page kept on the server, not in the repo.

The page is a file under the data folder (RACINGLINES_MYBETS, default data/mybets/index.html), copied onto the VM
by hand like any other data. It is served as is: no site header, no nav, and no page links to it. Admin only, behind
the usual sign-in. Missing file: 404.
"""

import os
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from racinglines.paths import DATA
from racinglines.web.app import allow, app


def page() -> Path:
    return Path(os.environ.get("RACINGLINES_MYBETS", DATA / "mybets" / "index.html"))


@app.get("/mybets", dependencies=[allow("admin")])
def mybets():
    p = page()
    if not p.is_file():
        raise HTTPException(404, "No bets page on this server yet.")
    return FileResponse(p, media_type="text/html", headers={"Cache-Control": "no-store"})
