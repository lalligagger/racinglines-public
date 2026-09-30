"""
`racinglines nascar season`: the NASCAR Cup season forecast (models/nascar_season.py) and, with --quotes, its Cup
champion price beside every exchange's champion quote on file (market_links: OG.com's 17 contracts, Kalshi's
KXNASCARCUPSERIES / CUPCHAMP, Polymarket's champion market). Read-only: nothing is written to the database, and
nothing changes on the board, in the app or in any sync (OG.com's NASCAR links stay `modeled = false` in
exchanges/og.toml, every NASCAR link stays `unmodeled`).

Off by default: the command runs only with RACINGLINES_NASCAR_SEASON=1.
"""

import os

import numpy as np
import pandas as pd

from racinglines.models import nascar_season as NS

SWITCH = "RACINGLINES_NASCAR_SEASON"
N_SIMS = 4000
SEED = 7


def enabled():
    return os.environ.get(SWITCH, "").strip().lower() in ("1", "true", "yes", "on")


def forecast(engine, year, n_sims=N_SIMS, seed=SEED, stage_noise=5.0, race_noise="auto", standings="feed",
             model_settings=None, echo=print):
    """(standings frame, state, audit) for `year`: the race model (sports/nascar.toml pricing_model) prices every
    remaining points race for the field of the last race run, and the season is simulated through the format.

    standings: "feed" = NASCAR's points-feed.json when it is on disk (official points, penalties, seeds), else the
    points summed from race results; "results" = always the results. race_noise: "auto" = the spread of finishing
    positions measured on the last two seasons (NS.estimate_noise), a number = that many places, None = the race
    model's own default (2.0, which puts most simulated wins on one favourite)."""
    from sqlalchemy import text as sql

    from racinglines.models.race_model import Event
    from racinglines.pipelines import position_replay as PR
    from racinglines.sources.nascar import fetch
    fmt = NS.FORMATS.get(year)
    if fmt is None:
        raise ValueError(f"no championship format for {year}; known: {sorted(NS.FORMATS)}")
    sp = PR.spec("nascar")
    model = PR.model_for(sp)
    with engine.connect() as conn:
        results, schedule = NS.load_state(conn, year, competition=sp["competition"], source=sp["source"])
        ids = {} if standings != "feed" else {
            int(v): int(a) for v, a in conn.execute(sql("SELECT value, athlete_id FROM athlete_identifiers WHERE scheme = 'nascar'"))
            if str(v).isdigit()}
    if schedule.empty or results.empty:
        raise ValueError(f"no {year} Cup points races with results in the database (racinglines nascar ingest)")
    state = NS.standings_now(fmt, results, schedule)
    computed = state
    feed = fetch.read(fetch.feed_path(year, 1, "points-feed")) if standings == "feed" else None
    matched = 0
    if feed:
        state, matched = NS.apply_feed(fmt, state, feed, ids)
    data = model.load(engine.url.render_as_string(hide_password=False))
    noise = race_noise
    if race_noise == "auto":
        noise = NS.estimate_noise(data[data["season"] >= year - 1])
    settings = {"seed": seed, **(model_settings or {}), "sims": n_sims}
    if noise is not None:
        settings["noise"] = round(float(noise), 2)
    st = model.Settings.from_dict(settings)
    done = schedule[schedule["done"]]
    last = done["event_id"].iloc[-1]
    field = sorted(int(a) for a in results.loc[results["event_id"] == last, "athlete_id"])
    rem = schedule[~schedule["done"]].reset_index(drop=True)
    hist = model.history(data, st)
    rng = np.random.default_rng(seed)
    race_sims = []
    for r in rem.itertuples():
        ev = Event(id=f"{year}::{r.event_id}", season=year, cutoff=r.date, name=str(r.name), info={"field": field})
        race_sims.append(model.price(hist, ev, st, rng))
    remaining = [dict(chase=bool(r.chase), stages=None if pd.isna(r.stages) else int(r.stages)) for r in rem.itertuples()]
    if not remaining:
        echo(f"{year}: every points race is run; the standings are final")
    ss = NS.simulate_season(fmt, state, remaining, race_sims, rng, stage_noise=stage_noise) if remaining else None
    names = data.drop_duplicates("athlete_id", keep="last").set_index("athlete_id")["driver"].to_dict()
    frame = NS.standings_frame(ss, state, names) if ss is not None else None
    audit = dict(year=year, format=fmt.source, races_run=int(schedule["done"].sum()), races_left=len(remaining),
                 chase_races_left=sum(r["chase"] for r in remaining), field=len(field), n_sims=n_sims, seed=seed,
                 stage_noise=stage_noise, model=sp["model"], settings=st.changed(),
                 standings=f"NASCAR points feed ({matched} drivers matched)" if matched else "summed from race results",
                 computed=computed, feed=feed, names=names, standings_mode=standings)
    return frame, state, audit


def text(frame, audit, top=20):
    L = [f"NASCAR Cup {audit['year']}: {audit['races_run']} points races run, {audit['races_left']} left "
         f"({audit['chase_races_left']} in the Chase); field {audit['field']}; {audit['n_sims']:,} sims, seed {audit['seed']}",
         f"format: {audit['format']}", f"race model: {audit['model']} {audit['settings'] or '(defaults)'}",
         f"standings today: {audit['standings']}",
         "NOT CALIBRATED: races are simulated independently (no form drift, no track types) and the race noise is a",
         "measured spread, not a backtested one. On 2026-09-30 it was still more favourite-heavy than every exchange",
         "(points leader 68% vs about 42%); read these as an indicator, not as prices to trade.", "",
         f"{'driver':<24}{'seed':>5}{'pts now':>9}{'exp pts':>9}{'chase':>7}{'champ':>7}{'top3':>7}{'top10':>7}"]
    for r in frame.head(top).itertuples():
        L.append(f"{str(r.driver)[:23]:<24}{r.seed or '':>5}{r.current_points:9.0f}{r.exp_points:9.0f}{r.chase_prob:7.1%}"
                 f"{r.champion_prob:7.1%}{r.top3_prob:7.1%}{r.top10_prob:7.1%}")
    return "\n".join(L)


# --- the exchanges' champion quotes, read-only -----------------------------------------------------------------------

def champion_links(conn, year, competition="nascar_cup"):
    """Every NASCAR link that is a Cup champion contract for `year`, any exchange, with the driver it names (the
    link's athlete_id, else the NASCAR linker's reading of it in memory; nothing is written)."""
    from sqlalchemy import text as sql

    from racinglines.sources.nascar.links import Linker
    df = pd.read_sql(sql("""SELECT ml.* FROM market_links ml JOIN competitions co ON co.id = ml.competition_id
                            WHERE co.code = :c ORDER BY ml.exchange, ml.id"""), conn, params=dict(c=competition))
    return champions(df.to_dict("records"), Linker(conn), year) if len(df) else df


def champions(links, linker, year):
    """The Cup champion contracts for `year` among `links` (market_links rows as dicts), each with its driver: the
    stored athlete_id / params, else what `linker` (sources/nascar/links.Linker) reads from the listing."""
    rows = []
    for link in links:
        p = dict(link.get("params") or {})
        kind, series, season, ath = p.get("kind"), p.get("nascar_series"), p.get("season"), link.get("athlete_id")
        if kind is None or ath is None or pd.isna(ath) or season is None:
            f = linker.identify(link)
            kind, series, season = kind or f.kind, series or f.series, season or f.year
            ath = ath if ath is not None and not pd.isna(ath) else f.athlete_id
        if kind != "champion" or series not in (None, "cup") or (season is not None and int(season) != year):
            continue
        rows.append(dict(link, athlete_id=None if ath is None or pd.isna(ath) else int(ath)))
    return pd.DataFrame(rows)


def quote_rows(links, frame):
    """The model's champion price beside each link's last quote: one row per link, edges net of the exchange's
    schema taker fee (OG.com; Kalshi's and Polymarket's fees are not applied here, so their edges are before fees).
    A "No"-type token (invert) is priced 1 - P(champion). A link whose driver the model does not have gets no fair."""
    from racinglines.markets import venues
    if links is None or links.empty:
        return pd.DataFrame()
    p = dict(zip(frame["athlete_id"], frame["champion_prob"])) if frame is not None else {}
    out = []
    for link in links.to_dict("records"):
        fair = p.get(link.get("athlete_id"))
        if fair is not None and link.get("invert"):
            fair = 1 - fair
        bid, ask = (None if link.get(k) is None or pd.isna(link.get(k)) else float(link[k]) for k in ("last_bid", "last_ask"))
        fee = venues.schema_fee(link["exchange"])
        e = venues.net_edge(fee, fair, bid, ask) if fair is not None else dict(edge_yes=None, edge_no=None, call="")
        out.append(dict(exchange=link["exchange"], contract=link.get("group_title") or link.get("outcome") or link.get("question"),
                        athlete_id=link.get("athlete_id"), fair=fair, bid=bid, ask=ask, fee=fee, edge_yes=e["edge_yes"],
                        edge_no=e["edge_no"], call=e["call"], token=link.get("token_id")))
    return pd.DataFrame(out)


def quotes_text(q):
    if q.empty:
        return "No Cup champion links on file (racinglines markets --exchange og sync --sport nascar; nascar link)."
    f = lambda v: f"{v:7.2f}" if v is not None and not pd.isna(v) else "      -"
    L = ["", "Cup champion: model vs the exchanges' last quotes (edges net of the schema fee: OG.com only)",
         f"{'exchange':<11}{'contract':<30}{'fair':>7}{'bid':>7}{'ask':>7}{'edge YES':>10}{'edge NO':>9}  call"]
    for r in q.itertuples():
        L.append(f"{r.exchange:<11}{str(r.contract)[:29]:<30}{f(r.fair)}{f(r.bid)}{f(r.ask)}{f(r.edge_yes):>10}"
                 f"{f(r.edge_no):>9}  {r.call}" + ("   (driver not matched)" if r.fair is None or pd.isna(r.fair) else ""))
    return "\n".join(L)


def feed_check(audit):
    """How the points summed from race results compare with NASCAR's own points feed, when the feed is on disk:
    penalties, and seeds the results' tie-break got wrong, show up here (the forecast itself uses the feed)."""
    feed, comp, names = audit.get("feed"), audit.get("computed"), audit.get("names") or {}
    if audit.get("standings_mode") == "results":
        return "points feed: not used (--standings results), standings summed from race results"
    if not feed:
        return "points feed: not on disk (racinglines nascar fetch --years YEAR --feeds points-feed), standings from results"
    st = audit.get("standings", "")
    if comp is None or "matched" not in st:
        return f"points feed: on disk but no driver matched a NASCAR id ({st})"
    return f"points feed: {st}; results-summed standings shown for comparison below" + "\n" + _diffs(comp, feed, names)


def _diffs(comp, feed, names, chase_size=16):
    by_name = {norm_name(names.get(a, "")): a for a in comp["athlete_id"]}
    c = comp.set_index("athlete_id")
    L = []
    for r in feed:
        a = by_name.get(norm_name(r.get("driver_name") or ""))
        if a is None:
            continue
        dp = float(c.loc[a, "points"]) - float(r["points"])
        seed = int(c.loc[a, "seed"])
        rank = int(r.get("playoff_rank") or 0)
        fseed = rank if c["chase_set"].any() and 0 < rank <= chase_size else 0
        if abs(dp) > 0.5 or seed != fseed:
            L.append(f"  {r.get('driver_name')}: results {c.loc[a, 'points']:.0f} (seed {seed or '-'}), feed {r['points']} (seed {fseed or '-'})")
    return "\n".join([f"  {len(L)} drivers differ"] + L[:30])


def norm_name(n):
    from racinglines.sources.nascar.identity import norm
    return norm(n)
