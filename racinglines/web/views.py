"""
The core maker views, all built on venues.event_matrix / season_matrix:

    /                 Markets: every sport, next races, season, recent results
    /race/{race_id}   one race: our fair vs every venue, my quotes, results, chart
    /season/{code}    a competition's season-long markets, same layout
    /book             my positions across venues
    /lab              launch backtests / scenario forecasts / diagnostics; compare runs
"""

from datetime import timedelta

import pandas as pd
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from racinglines.db.config import get_session

from racinglines.web import board as B
from racinglines.web import diag
from racinglines.markets import private_book as house
from racinglines.web import jobs
from racinglines.markets import venues as V
from racinglines.web.app import ANY, allow, app, audit, check_csrf, conn, data, render, rows
from racinglines.web.viz import price_chart

KIND_ORDER = ["race_win", "race_podium", "race_top10", "race_make_final", "race_h2h", "race_constructor_top",
              "champion", "constructors_champion", "season_wins_ge", "standings_h2h"]


def _maker(user):
    return house.ALL if user["role"] == "admin" else user["id"]


def _groups(df):
    if not len(df):
        return []
    kinds = sorted(df["kind"].unique(), key=lambda k: KIND_ORDER.index(k) if k in KIND_ORDER else 99)
    return [(k, V.KIND_LABEL.get(k, k), rows(df[df["kind"] == k])) for k in kinds]


# ---------------------------------------------------------------------------
# Markets (home)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def board_page(request: Request, c=Depends(conn)):
    user = request.state.user
    if user["role"] == "taker":
        return RedirectResponse("/bet", status_code=303)
    return render(request, "board.html", sports=B.board(c, _maker(user)), h=B.headline(c, _maker(user)))


# ---------------------------------------------------------------------------
# Race / season pages
# ---------------------------------------------------------------------------

def _race_chart(c, info, pricing, df):
    wins = df[(df["kind"] == "race_win")] if len(df) else df
    tops = [r for r in wins.to_dict("records") if (r["venues"] or {}).get("polymarket")][:5]
    if not tops:
        return None
    now = pd.Timestamp.now(tz="UTC")
    start = info["race_start"] if info["race_start"] is not None and not pd.isna(info["race_start"]) else None
    start = pd.Timestamp(start).tz_localize("UTC") if start is not None else None
    if info["status"] == "completed" and start is not None:
        t0, t1 = start - timedelta(hours=72), start + timedelta(hours=1)
    else:
        t0, t1 = now - timedelta(hours=72), now
    toks = {r["venues"]["polymarket"]["token"]: r for r in tops}
    series = V.price_series(c, list(toks), t0.to_pydatetime(), t1.to_pydatetime())
    markers = []
    sess = data.q(c, """SELECT kind, (extra->>'session_date')::timestamp AS ts FROM rounds
                        WHERE race_id = :r AND extra->>'session_date' IS NOT NULL""", r=info["race_id"])
    for k, ts in zip(sess["kind"], sess["ts"]):
        markers.append((pd.Timestamp(ts).tz_localize("UTC"), {"qual": "quali", "race": "race", "final": "final"}.get(k, k)))
    if pricing.get("as_of") is not None:
        markers.append((pd.Timestamp(pricing["as_of"]).tz_localize("UTC"), "our price"))
    return price_chart(series, {t: r["subject"] for t, r in toks.items()}, {t: r["fair"] for t, r in toks.items()},
                       markers)


@app.get("/race/{race_id}", response_class=HTMLResponse)
def race_page(request: Request, race_id: int, msg: str = "", c=Depends(conn)):
    user = request.state.user
    if user["role"] == "taker":
        return RedirectResponse(f"/bet?race_id={race_id}", status_code=303)
    info, pricing, df = V.event_matrix(c, race_id, _maker(user))
    if info is None:
        raise HTTPException(404)
    completed = info["status"] == "completed"
    wins = df[df["kind"] == "race_win"] if len(df) else df
    fav = rows(wins.head(1))[0] if len(wins) else None
    winner, results = None, []
    if completed:
        w = wins[wins["result"] == True] if len(wins) else wins  # noqa: E712
        winner = rows(w)[0] if len(w) else None
        res = house.race_outcomes(c, race_id).sort_values("position", na_position="last")
        names = data.q(c, "SELECT id AS athlete_id, display_name AS athlete FROM athletes WHERE id = ANY(:i)",
                       i=res["athlete_id"].astype(int).tolist())
        res = res.merge(names, on="athlete_id", how="left")
        fair = {(r["kind"], r["athlete_id"]): r["fair"] for r in df.to_dict("records")} if len(df) else {}
        results = [dict(r, win=fair.get(("race_win", r["athlete_id"])), podium=fair.get(("race_podium", r["athlete_id"])))
                   for r in rows(res)]
    diag_runs = rows(data.q(c, """SELECT id, left(params->>'cutoff', 16) AS cutoff FROM model_runs
                                  WHERE kind = 'diagnostic' AND params->>'event_key' = :k ORDER BY id""",
                            k=info["source_key"]))
    return render(request, "race.html", info=info, pricing=pricing, groups=_groups(df), fav=fav, winner=winner,
                  results=results, completed=completed, season=False, venue_sum=V.venue_summary(df), mine=B._mine(df),
                  exchanges=V.EXCHANGES, has_pm=bool(len(df) and df["pm_mid"].notna().any()),
                  chart_data=_race_chart(c, info, pricing, df), countdown=B._countdown(info["start_date"]),
                  diag_runs=diag_runs, msg=msg, kind_label=V.KIND_LABEL,
                  quote_kinds=list(V.STANDARD_KINDS.get(info["competition"], ("race_win", "race_podium"))))


@app.get("/season/{code}", response_class=HTMLResponse, dependencies=[allow("admin", "maker")])
def season_page(request: Request, code: str, c=Depends(conn)):
    info, pricing, df = V.season_matrix(c, code, _maker(request.state.user))
    if info is None:
        raise HTTPException(404)
    info = dict(info, status=None, start_date=None, name="Season-long markets", event_id=None, race_id=0, source_key=None)
    champs = df[df["kind"] == "champion"] if len(df) else df
    return render(request, "race.html", info=info, pricing=pricing, groups=_groups(df),
                  fav=rows(champs.head(1))[0] if len(champs) else None, winner=None, results=[], completed=False,
                  season=True, strategy=latest_season_strategy(c, code), venue_sum=V.venue_summary(df), mine=B._mine(df), exchanges=V.EXCHANGES,
                  has_pm=bool(len(df) and df["pm_mid"].notna().any()), chart_data=None, countdown="", diag_runs=[],
                  msg="", kind_label=V.KIND_LABEL, quote_kinds=[])


# ---------------------------------------------------------------------------
# My book
# ---------------------------------------------------------------------------

@app.get("/book", response_class=HTMLResponse)
def book_page(request: Request, maker: str = "", c=Depends(conn), user=allow("admin", "maker")):
    maker_id = user["id"] if user["role"] == "maker" else house.ALL
    if user["role"] == "admin" and maker:
        mk = data.q(c, "SELECT id FROM users WHERE username = :u", u=maker)
        maker_id = int(mk["id"].iloc[0]) if len(mk) else -1
    bk = house.book(c, maker_id=maker_id)
    groups = []
    if len(bk):
        bk["race_key"] = bk["race_id"].fillna(0).astype(int)
        meta = data.q(c, """SELECT ra.id AS race_key, v.name AS venue, e.start_date, e.status, co.code AS competition
                            FROM races ra JOIN events e ON e.id = ra.event_id JOIN seasons s ON s.id = e.season_id
                            JOIN competitions co ON co.id = s.competition_id LEFT JOIN venues v ON v.id = e.venue_id
                            WHERE ra.id = ANY(:r)""", r=[int(x) for x in bk["race_key"].unique() if x])
        meta = {int(r["race_key"]): r for r in meta.to_dict("records")}
        for rk, g in bk.groupby("race_key", sort=False):
            mt = meta.get(rk, {})
            title = "Season-long markets" if rk == 0 else (
                f"{mt.get('venue')} GP" if mt.get("competition") == "f1_wdc" else mt.get("venue"))
            groups.append(dict(race_id=rk, title=title, sport=V.SPORT_NAME.get(mt.get("competition"), ""),
                               date=mt.get("start_date"), status=mt.get("status", "open"),
                               markets=len(g), open=int((g["status"] == "open").sum()), bets=int(g["bets"].sum()),
                               staked=float(g["staked"].sum()), ev=float(g.loc[g["status"] == "open", "ev"].sum()),
                               worst=float(g.loc[g["status"] == "open", "worst"].sum()),
                               settled=float(g["settled_pnl"].dropna().sum()),
                               top=rows(g.sort_values("staked", ascending=False).head(5))))
        groups.sort(key=lambda x: (x["status"] == "completed", str(x["date"] or "9999")))
    tot = dict(markets=len(bk), open=int((bk["status"] == "open").sum()) if len(bk) else 0,
               bets=int(bk["bets"].sum()) if len(bk) else 0, staked=float(bk["staked"].sum()) if len(bk) else 0.0,
               ev=float(bk.loc[bk["status"] == "open", "ev"].sum()) if len(bk) else 0.0,
               worst=float(bk.loc[bk["status"] == "open", "worst"].sum()) if len(bk) else 0.0,
               settled=float(bk["settled_pnl"].dropna().sum()) if len(bk) else 0.0)
    makers = rows(data.q(c, "SELECT username FROM users WHERE role IN ('maker', 'admin') ORDER BY username"))
    orders = data.q(c, "SELECT status, count(*) AS n FROM orders GROUP BY status")
    return render(request, "book.html", groups=groups, tot=tot, makers=makers, maker=maker,
                  orders=dict(zip(orders["status"], orders["n"])) if len(orders) else {})


# ---------------------------------------------------------------------------
# Lab: launch runs, compare them, diagnostics
# ---------------------------------------------------------------------------

def backtest_runs(c, limit=12):
    df = data.q(c, """
        SELECT mr.id, mr.created_at, co.code AS competition, mr.params, mr.metrics->'summary' AS summary,
               jsonb_array_length(coalesce(mr.metrics->'events', '[]'::jsonb)) AS rows_
        FROM model_runs mr JOIN competitions co ON co.id = mr.competition_id
        WHERE mr.kind = 'backtest' ORDER BY mr.id DESC LIMIT :n""", n=limit)
    out = []
    for r in df.to_dict("records"):
        p, s = r["params"] or {}, r["summary"] or {}
        for track in ("True", "False"):
            pre = s.get(f"pre_race|track={track}")
            if not pre:
                continue
            out.append(dict(id=r["id"], created_at=r["created_at"], sport=V.SPORT_NAME.get(r["competition"]),
                            races=p.get("races") or "all", half_life=p.get("half_life_days", 120), sims=p.get("sims"),
                            track="on" if track == "True" else "off",
                            win=pre.get("brier_win"), win_grid=pre.get("brier_win_grid"),
                            podium=pre.get("brier_podium"), podium_grid=pre.get("brier_podium_grid"),
                            top10=pre.get("brier_top10"), top10_grid=pre.get("brier_top10_grid"),
                            pre_quali_win=(s.get(f"pre_quali|track={track}") or {}).get("brier_win"),
                            pre_weekend_win=(s.get(f"pre_weekend|track={track}") or {}).get("brier_win")))
    return out


def scenarios(c):
    df = data.q(c, """
        SELECT mr.id, mr.created_at, mr.kind, co.code AS competition, mr.competition_id, mr.category_id, mr.params
        FROM model_runs mr JOIN competitions co ON co.id = mr.competition_id
        WHERE mr.kind = 'scenario' OR (mr.kind = 'forecast' AND mr.params ? 'label')
        ORDER BY mr.id DESC LIMIT 12""")
    out = []
    for r in df.to_dict("records"):
        live, _ = data.latest_forecast_run(c, r["competition_id"], r["category_id"])
        nxt = data.q(c, """SELECT rp.race_id, a.display_name, rp.win_prob FROM race_predictions rp
                           JOIN athletes a ON a.id = rp.athlete_id
                           WHERE rp.model_run_id = :m AND rp.race_id = (SELECT min(race_id) FROM race_predictions
                                                                        WHERE model_run_id = :m AND race_id IS NOT NULL)
                           ORDER BY rp.win_prob DESC LIMIT 3""", m=r["id"])
        diff = None
        if live and len(nxt):
            lv = data.q(c, "SELECT athlete_id, win_prob FROM race_predictions WHERE model_run_id = :m AND race_id = :r",
                        m=live, r=int(nxt["race_id"].iloc[0]))
            sc = data.q(c, "SELECT athlete_id, win_prob FROM race_predictions WHERE model_run_id = :m AND race_id = :r",
                        m=r["id"], r=int(nxt["race_id"].iloc[0]))
            j = sc.merge(lv, on="athlete_id", suffixes=("", "_live"))
            diff = float((j["win_prob"] - j["win_prob_live"]).abs().max()) if len(j) else None
        p = r["params"] or {}
        out.append(dict(id=r["id"], created_at=r["created_at"], sport=V.SPORT_NAME.get(r["competition"]),
                        label=p.get("label"), half_life=p.get("half_life_days"), sims=p.get("sims"),
                        track=p.get("track_features"), live=r["id"] == live, kind=r["kind"],
                        top=[(n, w) for n, w in zip(nxt["display_name"], nxt["win_prob"])], max_diff=diff))
    return out


def latest_season_strategy(c, competition="f1_wdc"):
    """The latest saved default season strategy (kind='season_strategy') for a competition."""
    df = data.q(c, """SELECT mr.id, mr.created_at, mr.params, mr.metrics FROM model_runs mr
                      JOIN competitions co ON co.id = mr.competition_id
                      WHERE mr.kind = 'season_strategy' AND co.code = :c ORDER BY mr.id DESC LIMIT 1""", c=competition)
    if not len(df):
        return None
    r = df.iloc[0].to_dict()
    m = r["metrics"] or {}
    eq = pd.DataFrame(m.get("equity", []))
    chart = None
    if len(eq):
        eq["t"] = pd.to_datetime(eq["t"], utc=True)
        from racinglines.web.viz import line_chart
        series = {"strategy": list(zip(eq["t"], eq["equity"].astype(float)))}
        if "hold" in eq:
            series["hold"] = list(zip(eq["t"], eq["hold"].astype(float)))
        chart = line_chart(series, {"strategy": "update after every race", "hold": "enter pre-season & hold"})
    now = m.get("now", [])
    actions = [n for n in now if n.get("action") not in ("hold", "no position")]
    return dict(id=int(r["id"]), created_at=r["created_at"], params=r["params"] or {}, summary=m.get("summary", {}),
                hold=m.get("hold", {}), positions=m.get("positions", []), trades=m.get("trades", []), now=now,
                actions=actions, decisions=m.get("decisions", []), chart=chart)


def latest_sweep(c):
    df = data.q(c, "SELECT id, created_at, params, metrics FROM model_runs WHERE kind = 'sweep' ORDER BY id DESC LIMIT 1")
    if not len(df):
        return None
    r = df.iloc[0].to_dict()
    m = r["metrics"] or {}
    return dict(id=int(r["id"]), created_at=r["created_at"], params=r["params"] or {}, weekends=m.get("weekends", []),
                totals=m.get("totals", {}), by_stage=m.get("by_stage", []), by_kind=m.get("by_kind", []),
                scores=m.get("scores", []))


def _events_for_diagnostic(c):
    return rows(data.q(c, """
        SELECT e.source_key AS key, v.name AS venue, e.start_date,
               (SELECT min((ro.extra->>'session_date')::timestamp) FROM rounds ro WHERE ro.race_id = ra.id
                 AND ro.kind = 'race') AS race_start,
               EXISTS (SELECT 1 FROM market_links ml WHERE ml.race_id = ra.id AND ml.prediction <> 'unmodeled'
                       AND ml.closed) AS tape
        FROM events e JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id
        JOIN races ra ON ra.event_id = e.id LEFT JOIN venues v ON v.id = e.venue_id
        WHERE co.code = 'f1_wdc' AND e.status = 'completed' ORDER BY e.start_date DESC LIMIT 40"""))


@app.get("/lab", response_class=HTMLResponse, dependencies=[allow("admin", "maker")])
def lab_page(request: Request, job: str = "", event: str = "", msg: str = "", c=Depends(conn)):
    recent_jobs = rows(data.q(c, """SELECT j.*, u.username FROM jobs j LEFT JOIN users u ON u.id = j.user_id
                                    ORDER BY j.id DESC LIMIT 15"""))
    active = any(j["status"] in ("queued", "running") for j in recent_jobs)
    evs = _events_for_diagnostic(c)
    for e in evs:
        rs = e["race_start"]
        e["default_cutoff"] = ((pd.Timestamp(rs) - timedelta(days=1)).strftime("%Y-%m-%dT23:59") if rs is not None
                               else f"{pd.Timestamp(e['start_date']) - timedelta(days=1):%Y-%m-%d}T23:59")
    sel_event = event or (evs[0]["key"] if evs else "")
    sel = next((e for e in evs if e["key"] == sel_event), None)
    sports = [(code, V.SPORT_NAME[code], [j for j in jobs.CATALOG.values() if j.sport == sport])
              for code, sport in (("f1_wdc", "f1"), ("uci_dhi_wc", "mtb_dh"))]
    return render(request, "lab.html", sports=sports, jobs=recent_jobs, active=active, sel_job=job,
                  events=evs, sel_event=sel_event, sel_cutoff=sel["default_cutoff"] if sel else "",
                  scenarios=scenarios(c), backtests=backtest_runs(c), forecasts=rows(data.latest_forecasts(c)),
                  event_diags=diag.event_summaries(c), recent=rows(diag.recent_runs(c)), msg=msg, sweep=latest_sweep(c))


@app.post("/lab/run", dependencies=[Depends(check_csrf)])
async def lab_run(request: Request, user=allow("admin", "maker")):
    form = await request.form()
    jt = jobs.CATALOG.get(form.get("job"))
    if jt is None:
        raise HTTPException(400, "unknown job")
    try:
        params = jobs.parse(jt, form)
    except (ValueError, TypeError) as e:
        return RedirectResponse(f"/lab?job={jt.code}&msg=Error: {e}#run", status_code=303)
    job_id = jobs.submit(jt, params, user["id"])
    audit(request, "job_submit", job_id=job_id, kind=jt.code, params=params)
    return RedirectResponse(f"/lab?msg=Job {job_id} queued: {jt.label}#jobs", status_code=303)


@app.post("/lab/promote/{run_id}", dependencies=[Depends(check_csrf)])
def lab_promote(request: Request, run_id: int, user=allow("admin", "maker")):
    try:
        with get_session() as s:
            jobs.promote(s, run_id)
    except ValueError as e:
        return RedirectResponse(f"/lab?msg=Error: {e}", status_code=303)
    audit(request, "promote_forecast", run_id=run_id)
    return RedirectResponse(f"/lab?msg=Run {run_id} is now the live forecast#scenarios", status_code=303)


@app.get("/diag", dependencies=[allow("admin", "maker")])
def diag_redirect():
    return RedirectResponse("/lab#diagnostics", status_code=303)


@app.get("/runs", dependencies=[allow("admin", "maker")])
def runs_redirect():
    return RedirectResponse("/lab", status_code=303)


@app.get("/me", response_class=HTMLResponse, dependencies=[allow(*ANY)])
def me_redirect(request: Request, c=Depends(conn)):
    user = request.state.user
    if user["role"] != "taker":
        return RedirectResponse("/book", status_code=303)
    my_bets = house.taker_bets(c, user["id"])
    summary = dict(bets=len(my_bets), staked=float(my_bets["stake"].sum()), open=int((my_bets["status"] == "open").sum()),
                   pnl=float(my_bets["pnl"].sum())) if len(my_bets) else None
    return render(request, "me.html", my_bets=rows(my_bets), my_book=[], summary=summary)
