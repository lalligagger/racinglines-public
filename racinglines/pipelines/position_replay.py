"""
Taker replay for the result-only sports (NASCAR Cup, MotoGP): every raced event of a season, priced by the sport's
model and traded at a few fixed times before the race against an exchange's recorded prices.

    out = run(engine, "nascar", [2025, 2026], venue="kalshi")
    out["races"]     one row per race: markets, tradeable, P&L per taker mode (update / hold / last)
    out["trades"]    every trade of the `update` mode, with its P&L to resolution
    out["totals"]    per mode: P&L, Kalshi's taker fees, P&L after fees, races up
    out["by_kind"]   P&L of the `update` trades by market kind
    out["calibration"], out["reliability"]   model vs exchange, scored on the results (core/calibration.py)

The F1 weekend sweep (pipelines/weekend_sweep.py) is not used or changed: its stages come from F1's session
schedule and its fairs from position_sim. Here, per race:

  1. The field is the race's start list (the drivers or riders with a result in its race round: known before the
     start; their positions are read only in step 4).
  2. The model (sports/<code>.toml [sport] pricing_model) prices the race from results strictly before the event
     (race_model.Event with the field in `info`). It uses race results only, so one pricing serves every stage.
  3. At each stage of [replay] stages (hours from 00:00 UTC on race day), the venue (markets/venue_replay.py:
     Kalshi's or Polymarket's recorded prices and tape) says the price and whether the market was tradeable (priced,
     liquid, open, a coherent group), and the taker strategies (markets/strategies/taker_weekend.py) trade.
  4. Only then the result settles each market: by classified position (NASCAR classifies every car, retirements by
     laps run; an unclassified MotoGP rider has no position and is NO for every top-n market).

Markets: the sport's links on the venue whose kind is in [replay] kinds. The kind, driver and race come from the
stored link (NASCAR's `nascar link --apply` writes params.kind, athlete_id and race_id), else from the sport's
matcher run in memory ([replay] linker): nothing is written to market_links.

Run with `racinglines nascar replay` / `racinglines motogp replay` (every exchange the sport lists on, by default).
`save` also stores one as-of model run per race (model_runs kind 'diagnostic' + race_predictions, and prediction
records with the sims, on for these sports unless RACINGLINES_PREDICTION_RECORDS is set off); the CLI asks for a
fresh backup first and every saved run carries the batch
id that `undo` deletes.
"""

import importlib
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text

from racinglines import sports
from racinglines.core import calibration as CAL
from racinglines.markets.strategies import taker_weekend as RB

N_OF = {"race_win": 1, "race_podium": 3, "race_top5": 5, "race_top10": 10, "race_top20": 20}
TAKER_MODES = ("update", "hold", "last")
STALE = timedelta(hours=6)
COHERENCE_TOL = 0.25                 # as the F1 sweep's (a priori, not tuned for these sports)
MIN_VOLUME_24H = 50.0                # $ traded in the market over the previous 24 h (the F1 taker's floor)
SEED = 7                             # the model's Monte Carlo seed when the settings leave it unset


def spec(sport):
    """The sport's [replay] section, with its competition, events source and pricing model."""
    s = sports.load(sport)
    rp = s.get("replay")
    if not rp:
        raise ValueError(f"sport {sport!r} has no [replay] section in sports/{sport}.toml")
    return dict(rp, sport=sport, competition=s["competition"]["code"], model=s["sport"]["pricing_model"])


def venues(sport):
    """The exchanges the sport's schema lists ([markets] venues)."""
    return tuple(sports.load(sport)["markets"]["venues"])


def records_on():
    """Prediction records for a replay save: on unless RACINGLINES_PREDICTION_RECORDS is set to an off value
    (the replay of these sports writes them by default; every other writer keeps the switch's own default, off)."""
    import os

    from racinglines.db import records as REC
    v = os.environ.get(REC.SWITCH)
    return True if v is None or not v.strip() else REC.enabled()


def model_for(sp):
    mod, _, cls = sp["model"].partition(":")
    return getattr(importlib.import_module(mod), cls)()


# --- what was knowable, per race ------------------------------------------------------------------------

def races(conn, sp, seasons=None):
    """The sport's completed races, in date order: race_id, event_key, name, season, start (the event's first day)."""
    df = pd.read_sql(text("""
        SELECT ra.id AS race_id, e.source_key AS event_key, e.name, s.year AS season, e.start_date AS start
        FROM races ra JOIN events e ON e.id = ra.event_id JOIN seasons s ON s.id = e.season_id
        JOIN competitions co ON co.id = s.competition_id
        WHERE co.code = :c AND e.source = :src AND e.status = 'completed'
          AND EXISTS (SELECT 1 FROM rounds ro WHERE ro.race_id = ra.id AND ro.kind = 'race')
        ORDER BY e.start_date, ra.id"""), conn, params=dict(c=sp["competition"], src=sp["source"]))
    if seasons:
        df = df[df["season"].isin(list(seasons))]
    return df.reset_index(drop=True)


def race_results(conn, race_id):
    """The race round's classification: athlete_id, position (NaN = unclassified), status."""
    return pd.read_sql(text("""
        SELECT r.athlete_id, r.position, r.status FROM results r JOIN rounds ro ON ro.id = r.round_id
        WHERE ro.race_id = :r AND ro.kind = 'race' ORDER BY r.position NULLS LAST, r.athlete_id"""),
                       conn, params=dict(r=int(race_id)))


def stage_times(race_start, sp):
    """[(label, time)] of the race's stages: [replay] stages are hours from 00:00 UTC on race day, which is
    race_day_offset days after the event's first day. Naive UTC."""
    day = pd.Timestamp(race_start) + pd.Timedelta(days=int(sp.get("race_day_offset", 0)))
    return [(str(label), day + pd.Timedelta(hours=float(h))) for label, h in sp["stages"]]


def _identifier(sp, conn):
    name = sp.get("linker")
    if not name:
        return None
    L = importlib.import_module(f"racinglines.sources.{name}.links").Linker(conn)
    if name == "nascar":                                   # Found -> the dict the MotoGP linker returns
        def ident(link):
            f = L.identify(link)
            return dict(kind=f.kind, athlete_id=f.athlete_id, race_id=f.race_id, opponent_id=f.opponent_id)
        return ident
    return L.identify


def links(conn, sp, venue):
    """The sport's links on `venue` with a kind of [replay] kinds, one per market (Polymarket: the first token of
    each condition, as the F1 sweep; Kalshi: every ticker). `prediction` is set to the kind (in this frame only)."""
    df = pd.read_sql(text("""SELECT ml.*, a.display_name AS athlete FROM market_links ml
                             JOIN competitions co ON co.id = ml.competition_id
                             LEFT JOIN athletes a ON a.id = ml.athlete_id
                             WHERE co.code = :c AND ml.exchange = :x ORDER BY ml.id"""),
                     conn, params=dict(c=sp["competition"], x=venue))
    if not len(df):
        return df
    ident = _identifier(sp, conn)
    rows = []
    for link in df.to_dict("records"):
        p = dict(link.get("params") or {})
        kind, ath, rid, opp = p.get("kind"), link.get("athlete_id"), link.get("race_id"), p.get("opponent_id")
        ath = None if ath is None or pd.isna(ath) else int(ath)
        rid = None if rid is None or pd.isna(rid) else int(rid)
        if ident is not None and (kind is None or ath is None or rid is None or (kind == "race_h2h" and opp is None)):
            got = ident(link)
            kind, ath, rid, opp = kind or got["kind"], ath or got["athlete_id"], rid or got["race_id"], opp or got["opponent_id"]
        if kind not in sp["kinds"] or ath is None or rid is None or (kind == "race_h2h" and opp is None):
            continue
        if opp is not None:
            p["opponent_id"] = int(opp)
        rows.append(dict(link, prediction=kind, athlete_id=ath, race_id=rid, params=p))
    out = pd.DataFrame(rows)
    if not len(out):
        return out
    return out.drop_duplicates("condition_id" if venue == "polymarket" else "token_id", keep="first").reset_index(drop=True)


# --- fair values and settlement -------------------------------------------------------------------------

def fair(sims, kind, athlete_id, opponent_id=None):
    """P(YES) from the simulations, or None when the model has no column for the athlete (or opponent)."""
    try:
        i = sims.index(athlete_id)
        j = sims.index(opponent_id) if kind == "race_h2h" else None
    except ValueError:
        return None
    if kind == "race_h2h":
        return float((sims.rank[:, i] < sims.rank[:, j]).mean())
    return float(((sims.rank[:, i] <= N_OF[kind]) & sims.finished[:, i]).mean())


def settle(kind, athlete_id, opponent_id, res):
    """YES / NO from the classification (None when the athlete, or a head-to-head's opponent, has no result)."""
    pos = {int(a): (np.inf if pd.isna(p) else float(p)) for a, p in zip(res["athlete_id"], res["position"])}
    if athlete_id not in pos:
        return None
    if kind == "race_h2h":
        if opponent_id not in pos or (np.isinf(pos[athlete_id]) and np.isinf(pos[opponent_id])):
            return None
        return bool(pos[athlete_id] < pos[opponent_id])
    return bool(pos[athlete_id] <= N_OF[kind])


def _open(link, t):
    end = link.get("end_date")
    if end is None or pd.isna(end):
        return True
    end = pd.Timestamp(end)
    end = end.tz_convert("UTC").tz_localize(None) if end.tzinfo is not None else end
    return t < end


def race_markets(venue, race_links, sims, res, stages, min_volume_24h=MIN_VOLUME_24H):
    """Per market: each stage's fair, exchange price and tradeable flag, and the outcome, in the shape
    taker_weekend.run_weekend reads. venue: a venue_replay venue over these links (view, coherent)."""
    coherent = {(k, lab): venue.coherent(k, t) for lab, t in stages for k in venue.group_target}
    out = []
    for link in race_links.to_dict("records"):
        kind, a = link["prediction"], int(link["athlete_id"])
        b = (link["params"] or {}).get("opponent_id")
        f = fair(sims, kind, a, b) if sims is not None else None
        st = []
        for lab, t in stages:
            price, _, liquid = venue.view(link, t, min_volume_24h)
            ok = liquid and f is not None and _open(link, t) and coherent.get((kind, lab), True)
            st.append(dict(label=lab, t=t, fair=f, price=price, tradeable=ok))
        subject = link.get("athlete") or link.get("group_title")
        if kind == "race_h2h":
            subject = f"{subject} v {b}"
        out.append(dict(key=link["token_id"], kind=kind, subject=subject, stages=st, link=link,
                        outcome=settle(kind, a, b, res)))
    return out


def kalshi_fees(trades):
    """Kalshi's taker fee on each trade (venue_replay.Kalshi.taker_fee at the mid, per order), in dollars."""
    from racinglines.markets.venue_replay import Kalshi
    if not len(trades):
        return 0.0
    return float(sum(Kalshi.taker_fee(m, abs(s)) for m, s in zip(trades["mid"], trades["shares"])))


# --- the season -----------------------------------------------------------------------------------------

def _venue(conn, venue, race_links, stages, sp):
    from racinglines.markets.venue_replay import EXCHANGES
    start = min(t for _, t in stages) - timedelta(hours=1)
    end = max(t for _, t in stages) + timedelta(hours=1)
    gt = {k: int(v) for k, v in (sp.get("group_target") or {}).items()}
    return EXCHANGES[venue](conn, race_links, start, end, gt, COHERENCE_TOL, STALE)


def run(engine, sport, seasons=None, venue="kalshi", taker=None, min_volume_24h=MIN_VOLUME_24H, model_settings=None,
        kinds=None, data=None, save=None, echo=print):
    """The replay over `seasons` (None = every season with races). taker: TakerParams (None = the defaults).
    model_settings: dict for the model's Settings (seed defaults to SEED). kinds: a subset of [replay] kinds.
    data: the model's frame, already loaded. save: None, or dict(engine_url, batch) to store one model run per race."""
    sp = spec(sport)
    if kinds:
        bad = set(kinds) - set(sp["kinds"])
        if bad:
            raise ValueError(f"kinds {sorted(bad)} are not in sports/{sport}.toml [replay] kinds {sp['kinds']}")
        sp = dict(sp, kinds=list(kinds))
    model = model_for(sp)
    st = model.Settings.from_dict({"seed": SEED, **(model_settings or {})})
    t = taker or RB.TakerParams()
    plist = [RB.TakerParams(**{**t.__dict__, "mode": m}) for m in TAKER_MODES]
    from racinglines.models.race_model import Event
    with engine.connect() as conn:
        rs = races(conn, sp, seasons)
        lk = links(conn, sp, venue)
    echo(f"progress {sport} {venue}: {len(rs)} races, {len(lk)} markets of kinds {', '.join(sp['kinds'])}")
    if data is None:
        data = model.load(engine.url.render_as_string(hide_password=False))
    hist = model.history(data, st)
    rng = np.random.default_rng(st.rng_seed)
    rows, trades, calib = [], [], []
    for r in rs.itertuples():
        race_links = lk[lk["race_id"] == r.race_id] if len(lk) else lk
        with engine.connect() as conn:
            res = race_results(conn, r.race_id)
            if res.empty:
                continue
            field = sorted(int(a) for a in res["athlete_id"])
            ev = Event(id=r.event_key, season=int(r.season), cutoff=r.start, name=str(r.name), info={"field": field})
            sims = model.price(hist, ev, st, rng)            # every race is priced, traded or not: one rng stream
            if save is not None and sims is not None:
                save_run(save, sp, model, st, r, sims)
            if not len(race_links):
                continue
            stages = stage_times(r.start, sp)
            v = _venue(conn, venue, race_links, stages, sp)
            markets = race_markets(v, race_links, sims, res, stages, min_volume_24h)
        row = dict(season=int(r.season), event_key=r.event_key, race=r.name, race_id=int(r.race_id), markets=len(markets),
                   tradeable=sum(any(s["tradeable"] for s in m["stages"]) for m in markets))
        for p in plist:
            tr, per = RB.run_weekend(markets, p)
            s = RB.summarize(tr, per)
            fees = kalshi_fees(tr) if venue == "kalshi" else 0.0
            row.update({f"{p.mode}_{k}": s[k] for k in ("traded", "trades", "bought", "pnl")}, **{f"{p.mode}_fees": fees})
            if p.mode == "update" and len(tr):
                trades.append(tr.assign(event_key=r.event_key, race=r.name))
        calib += [dict(event_key=r.event_key, stage=s["label"], kind=m["kind"], model=s["fair"], market=s["price"],
                       y=float(m["outcome"])) for m in markets if m["outcome"] is not None
                  for s in m["stages"] if s["tradeable"]]
        rows.append(row)
        echo(f"progress {len(rows)} {r.event_key} {r.name}: {row['markets']} markets, {row['tradeable']} tradeable, "
             f"update {row['update_pnl']:+.2f} (fees {row['update_fees']:.2f})")
    out = summarize(pd.DataFrame(rows), trades, calib, dict(sport=sport, venue=venue, seasons=seasons,
                                                              taker={k: v for k, v in t.__dict__.items() if k != "mode"},
                                                              model=model.name, model_settings=st.to_json(),
                                                              min_volume_24h=min_volume_24h, kinds=sp["kinds"],
                                                              stages=sp["stages"], coherence_tol=COHERENCE_TOL,
                                                              group_target=sp.get("group_target") or {}))
    return dict(out, data=data)                  # data: the model's frame, for a second venue's pass


def summarize(races_df, trades, calib, params):
    trades = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    totals = {}
    for mode in TAKER_MODES:
        col = f"{mode}_pnl"
        if col in races_df:
            pnl, fees = float(races_df[col].fillna(0).sum()), float(races_df[f"{mode}_fees"].sum())
            totals[mode] = dict(pnl=pnl, fees=fees, net=pnl - fees, bought=float(races_df[f"{mode}_bought"].sum()),
                                races_up=int((races_df[col] > 0).sum()), races=int(races_df[col].notna().sum()))
    cal = pd.DataFrame(calib, columns=["event_key", "stage", "kind", "model", "market", "y"])
    cal_all, rel = CAL.table(cal, ("model", "market"), by=("kind",))
    return dict(races=races_df, trades=trades, totals=totals, by_kind=RB.by(trades, "kind"), calibration=cal_all,
                reliability=rel, params=params)


# --- saved runs (the backfill) --------------------------------------------------------------------------

def batch_id():
    return "replay-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def save_run(save, sp, model, st, race, sims):
    """One as-of run of one race: model_runs (kind 'diagnostic', params.cutoff = the event's first day, so the race
    page reads it as the pre-race price) and race_predictions (win / podium / top 10; top 5 and top 20 in extra);
    prediction records beside it when RACINGLINES_PREDICTION_RECORDS is on. Returns the run id."""
    from racinglines.db import models as m
    from racinglines.db import records as REC
    from racinglines.db.config import get_session
    from racinglines.models import outcomes as O
    p = {k: [fair(sims, k, a) for a in sims.entrants] for k in N_OF}
    cutoff = pd.Timestamp(race.start)
    with get_session(save["engine_url"]) as s:
        comp = s.execute(text("SELECT id FROM competitions WHERE code = :c"), dict(c=sp["competition"])).scalar()
        season = s.execute(text("SELECT id FROM seasons WHERE competition_id = :c AND year = :y"),
                           dict(c=comp, y=int(race.season))).scalar()
        run = m.ModelRun(competition_id=comp, season_id=season, model=model.name, kind="diagnostic",
                         data_through=(cutoff - pd.Timedelta(days=1)).date(),
                         params=dict(mode="replay as-of", replay_batch=save["batch"], sport=sp["sport"],
                                     event_key=race.event_key, cutoff=str(cutoff), sims=int(sims.n_sims),
                                     model_settings=st.to_json(), model_key=st.model_key, field=len(sims.entrants)))
        s.add(run)
        s.flush()
        for i, a in enumerate(sims.entrants):
            s.add(m.RacePrediction(model_run_id=run.id, race_id=int(race.race_id), target=f"asof:{race.event_key}",
                                   athlete_id=int(a), win_prob=p["race_win"][i], podium_prob=p["race_podium"][i],
                                   top10_prob=p["race_top10"][i],
                                   extra=dict(top5_prob=p["race_top5"][i], top20_prob=p["race_top20"][i])))
        s.commit()
        rid = run.id
    if records_on():
        df = O.to_records(sims, rid, sp["sport"], model.name, int(race.season), race.event_key, race.name, "asof",
                          cutoff, kinds=["race_win", "race_podium", "race_top10", "race_h2h"])
        REC.write(rid, df, sims)
    return rid


def undo(session, batch):
    """Delete every run a save pass stored (race_predictions go with them). Returns runs deleted."""
    ids = [r for (r,) in session.execute(text("SELECT id FROM model_runs WHERE params->>'replay_batch' = :b"),
                                         dict(b=batch)).all()]
    if ids:
        session.execute(text("DELETE FROM race_predictions WHERE model_run_id = ANY(:i)"), dict(i=ids))
        session.execute(text("DELETE FROM model_runs WHERE id = ANY(:i)"), dict(i=ids))
    return len(ids)


def format_report(out):
    """The run's text: totals per mode, P&L by kind, calibration."""
    p = out["params"]
    lines = [f"{p['sport']} on {p['venue']}, seasons {p['seasons'] or 'all'}: {len(out['races'])} races traded "
             f"(model {p['model']}; stages {', '.join(l for l, _ in p['stages'])})"]
    for mode, v in out["totals"].items():
        lines.append(f"  {mode:7} P&L {v['pnl']:+9.2f}  fees {v['fees']:7.2f}  net {v['net']:+9.2f}  bought {v['bought']:9.2f}  "
                     f"races up {v['races_up']}/{v['races']}")
    if len(out["by_kind"]):
        lines.append("  update trades by kind:")
        lines += ["    " + x for x in out["by_kind"].to_string(index=False).splitlines()]
    if len(out["calibration"]):
        lines.append("  model vs exchange at tradeable stages (lower is better):")
        lines += ["    " + x for x in out["calibration"].to_string(index=False).splitlines()]
    return "\n".join(lines)


def write(out, folder):
    """races.csv, trades.csv, calibration.csv and summary.json into `folder`."""
    import json
    folder.mkdir(parents=True, exist_ok=True)
    out["races"].to_csv(folder / "races.csv", index=False)
    out["trades"].to_csv(folder / "trades.csv", index=False)
    out["calibration"].to_csv(folder / "calibration.csv", index=False)
    (folder / "summary.json").write_text(json.dumps(dict(params=out["params"], totals=out["totals"]), indent=1,
                                                    default=lambda v: v.isoformat() if isinstance(v, date) else str(v)))
    return folder
