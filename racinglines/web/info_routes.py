"""
Read-only pages: model runs, events, athletes, the built docs, the intro and the pitch deck.
Split out of web/app.py, which imports this module to register the routes.
"""

import pandas as pd
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from racinglines.web import roles as R
from racinglines.web.app import ANY, PRO, allow, app, audit, check_csrf, conn, data, render, rows  # noqa: F401
from racinglines.web.app import ROOT, SITE


PRED_COLS = ["athlete", "nation", "win_prob", "podium_prob", "top10_prob", "make_final_prob", "exp_points"]
STAND_COLS = ["athlete", "current_points", "exp_points", "points_p10", "points_p90", "champion_prob",
              "top3_prob", "exp_rank"]


@app.get("/lab/runs/{run_id}", response_class=HTMLResponse, dependencies=[allow(*PRO)])
def run_detail(request: Request, run_id: int, c=Depends(conn)):
    run = data.model_run(c, run_id)
    if not run:
        raise HTTPException(404)
    metrics = {k: pd.DataFrame(v) if isinstance(v, list) else pd.DataFrame([v])
               for k, v in (run.get("metrics") or {}).items()}
    targets = rows(data.run_race_targets(c, run_id))
    preds = [dict(t, table=rows(data.race_predictions(c, run_id, t["target"]))) for t in targets]
    return render(request, "run.html", run=run, metrics={k: (list(v.columns), rows(v)) for k, v in metrics.items()},
                  preds=preds, standings=rows(data.standings_predictions(c, run_id)),
                  pred_cols=PRED_COLS + ["attend_prob", "actual_final_rank", "actual_points"], stand_cols=STAND_COLS)


@app.get("/events/by-key/{source_key}")
def event_by_key(source_key: str, c=Depends(conn)):
    """Stable link to an event by its source key (e.g. ChronoRace 20260925_mtb)."""
    ev = data.q(c, "SELECT id FROM events WHERE source_key = :k ORDER BY id DESC LIMIT 1", k=source_key)
    if not len(ev):
        raise HTTPException(404, f"no event {source_key}")
    return RedirectResponse(f"/events/{int(ev['id'].iloc[0])}", status_code=303)


@app.get("/racinglines101", response_class=HTMLResponse)
def racinglines101(request: Request):
    """Plain-language intro to makers, takers (the pro and basic tiers) and the paper-trading demo (public, linked from the login page)."""
    return render(request, "racinglines101.html")


@app.get("/pitch", response_class=HTMLResponse)
def pitch():
    """The pitch deck (pitch.html at the repo root), public like /login and /signup."""
    from fastapi.responses import FileResponse
    return FileResponse(ROOT / "pitch.html", media_type="text/html")




@app.get("/docs")
def docs_root():
    return RedirectResponse("/docs/", status_code=307)


@app.get("/docs/{path:path}")
def docs(path: str):
    """The built docs (site/), behind the same login."""
    from fastapi.responses import FileResponse
    f = (SITE / path).resolve()
    if not f.is_relative_to(SITE.resolve()):
        raise HTTPException(404)
    if f.is_dir():
        f = f / "index.html"
    if not f.is_file():
        if not SITE.is_dir():
            raise HTTPException(404, "Docs not built: run python -m mkdocs build -d site")
        raise HTTPException(404)
    return FileResponse(f)


@app.get("/events/{event_id}", response_class=HTMLResponse)
def event_detail(request: Request, event_id: int, c=Depends(conn)):
    ev = data.event(c, event_id)
    if not ev:
        raise HTTPException(404)
    res = data.event_results(c, event_id)
    groups = [dict(category=cat, round=rnd, table=rows(g))
              for (cat, _, rnd), g in res.groupby(["category", "ordinal", "round"], sort=True)] if len(res) else []
    preds = data.event_predictions(c, event_id)
    pred_groups = [dict(run=int(run), kind=g["kind"].iloc[0], category=cat, table=rows(g.head(30)))
                   for (run, cat), g in preds.groupby(["run", "category"], sort=False)] if len(preds) else []
    if R.is_basic(request.state.user):
        pred_groups = []  # model fair values are the makers' edge
    return render(request, "event.html", ev=ev, groups=groups, pred_groups=pred_groups)


@app.get("/athletes/{athlete_id}", response_class=HTMLResponse)
def athlete_detail(request: Request, athlete_id: int, c=Depends(conn)):
    a = data.athlete(c, athlete_id)
    if not a:
        raise HTTPException(404)
    preds = [] if R.is_basic(request.state.user) else rows(data.athlete_predictions(c, athlete_id))
    return render(request, "athlete.html", a=a, results=rows(data.athlete_results(c, athlete_id)), preds=preds)
