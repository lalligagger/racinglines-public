"""
The season sweep for any sport: every raced event of a season, traded through its stages by the taker modes
(update / hold / last / early) and the maker variants (maker, maker_flat, maker_skew, maker_widen, maker_all) of
pipelines/weekend_sweep.py, against one exchange's recorded tape (markets/venue_replay.py EXCHANGES: Polymarket,
Kalshi, OG.com), then settled on the result. Tuned on one season, held out on another (the search, sweeps/*.toml).

Nothing here names a sport. The sport's schema (sports/<code>.toml) says everything that differs:

    [sweep] stages      the default stage mode, i.e. where the stages and the fair values come from; a sweep picks
                        another one the schema supports with its `stages` setting (sweep_settings.py; a search job's
                        `stages = "weekend"`), so the earlier weekend-based results stay reproducible beside a
                        session-aware path:
        "sessions"      the session schedule ([sessions.schedule], [stages]) with one diagnostic run per stage, priced
                        as of each cutoff (pipelines/weekend_sweep.py run_sweep; F1's default and only mode, its
                        results as they were). Needs [sessions.schedule]
        "weekend"       fixed weekend stages, [replay] stages (hours from 00:00 UTC on race day), priced once per race
                        by [sport] pricing_model from results strictly before the event (a results-only model: one
                        pricing serves every stage), settled by markets/kinds.settle (pipelines/position_replay.py;
                        NASCAR's and MotoGP's default). Needs [replay] stages
    kinds               [sweep] kinds, else [markets] weekend_kinds ("sessions") or [replay] kinds ("weekend")
    venues              [markets] venues that are exchanges, then OG.com where exchanges/og.toml lists the sport
    [sweep] late_stages the stages the stage-aware taker ("early") skips (default none)
    [sweep] quote_until_hours
                        "weekend": the hour (UTC) of race day the maker stops quoting

    run(engine, engine_url, "nascar", 2026, settings=settings_class("nascar").from_dict({"venue": "kalshi"}))
        -> dict(weekends, by_stage, by_kind, totals, trades, scores, calibration, reliability, params)
           params carries sport, venue, the settings (settings_key, model_key) and the data fingerprint (data_key)
    settings_class(sport)       the sweep's settings for the sport: its pricing model's own settings plus the shared
                                entry timing, taker, maker and markets settings (pipelines/sweep_settings.py), with the
                                stage labels, kinds and venues of the schema as their choices (F1: sweep_settings.Settings)

Read-only: the "weekend" mode stores nothing (the CLI's --save stores the sweep run itself, kind 'sweep').
"""

import hashlib
import zlib
from dataclasses import replace
from datetime import timedelta
from functools import cache

import numpy as np
import pandas as pd

from racinglines import progress as PG
from racinglines import sports
from racinglines.pipelines import sweep_settings as SS

MODES = SS.STAGE_MODES                 # ("sessions", "weekend")


# --- the schema ------------------------------------------------------------------------------------------

def spec(sport):
    """The sport's [sweep] table (its default stage mode, late stages, quoting window), with defaults."""
    s = sports.load(sport)
    sw = dict(s.get("sweep") or {})
    if not sw:
        raise ValueError(f"sport {sport!r} has no [sweep] table in sports/{sport}.toml (stages, ...)")
    if sw.get("stages") not in modes(sport):
        raise ValueError(f"sports/{sport}.toml [sweep] stages {sw.get('stages')!r}: one of the modes its schema "
                         f"supports, {modes(sport)} (sessions: [sessions.schedule]; weekend: [replay] stages)")
    return dict(dict(late_stages=[], quote_until_hours=0.0), **sw)


def modes(sport):
    """The stage modes the sport's schema supports: "sessions" with a session schedule ([sessions.schedule]),
    "weekend" with fixed weekend stages ([replay] stages)."""
    s = sports.load(sport)
    have = dict(sessions=bool(s.get("sessions", {}).get("schedule")), weekend=bool(s.get("replay", {}).get("stages")))
    return tuple(m for m in MODES if have[m])


def mode_of(sport, settings=None):
    """The stage mode of a sweep: its `stages` setting, else the schema's default ([sweep] stages)."""
    m = (settings or {}).get("stages") or spec(sport)["stages"]
    if m not in modes(sport):
        raise ValueError(f"{sport}: stages {m!r} is not a mode its schema supports, {modes(sport)}")
    return m


def engine_of(sport):
    """The schema's default stage mode (mode_of without settings)."""
    return mode_of(sport)


def supports(sport):
    """True when the sport's schema has what a sweep needs: a [sweep] stage mode its schema supports and a pricing model."""
    try:
        spec(sport)
        from racinglines.models import race_model as RM
        RM.model_class(sport)
    except (ValueError, FileNotFoundError):
        return False
    return True


def kinds(sport, mode=None):
    """The market kinds the sweep trades: [sweep] kinds, else the stage mode's own list."""
    s, sw = sports.load(sport), spec(sport)
    if sw.get("kinds"):
        return tuple(sw["kinds"])
    if (mode or sw["stages"]) == "sessions":
        return tuple(s["markets"]["weekend_kinds"])
    return tuple(s["replay"]["kinds"])


def venues(sport):
    """The exchanges a sweep of the sport can trade: [markets] venues that are exchanges (markets/venue_replay.py),
    in the schema's order, then OG.com where its schema (exchanges/og.toml) lists the sport."""
    from racinglines import exchanges
    from racinglines.markets.venue_replay import EXCHANGES
    out = [v for v in sports.load(sport).get("markets", {}).get("venues", ()) if v in EXCHANGES]
    out += [v for v in EXCHANGES if v not in out and sport in _exchange_sports(exchanges, v)]
    return tuple(out)


def _exchange_sports(exchanges, code):
    """The sports an exchange's own schema (exchanges/<code>.toml) lists; () for one defined in code."""
    try:
        return exchanges.sports(code)
    except FileNotFoundError:                    # Polymarket, Kalshi: no schema file
        return ()


def stage_labels(sport, mode=None):
    """The labels of the sport's stages, in order ("weekend": [replay] stages; "sessions": sweep_settings.STAGES)."""
    if (mode or engine_of(sport)) == "sessions":
        return SS.STAGES
    return tuple(str(label) for label, _ in sports.load(sport)["replay"]["stages"])


@cache
def settings_class(sport):
    """The sweep's settings for the sport. A pricing model whose settings already hold the shared sweep settings
    (F1's: sweep_settings.Settings) is used as it is; any other gets them added, with the schema's stage labels,
    kinds and venues as their choices and defaults (the model's own settings keep their names, so its model_key is
    the same as its walk-forward's)."""
    from racinglines.models import race_model as RM
    base = RM.model_class(sport).Settings
    shared = [s.name for s in SS.SHARED_SETTINGS]
    if all(n in base.BY for n in shared):
        return base
    labels, ks, vs = stage_labels(sport), kinds(sport), venues(sport)
    if not vs:
        raise ValueError(f"sport {sport!r}: no exchange to sweep ([markets] venues, exchanges/*.toml)")
    late = tuple(x for x in labels if x in spec(sport)["late_stages"])
    over = dict(
        taker_stages=dict(default=labels, choices=labels),
        late_stages=dict(default=late, choices=labels),
        min_edge_by_kind=dict(choices=ks),
        coherence_tol_by_kind=dict(choices=ks),
        market_kinds=dict(default=ks, choices=ks, help=f"Any of sports/{sport}.toml's sweep kinds."),
        venue=dict(choices=vs, unset=vs[0], help=f"Whose markets and recorded tape the strategies trade: one of "
                                                 f"{', '.join(vs)}. Unset = {vs[0]}."),
        stages=dict(choices=modes(sport), unset=engine_of(sport),
                    help=f"Stage mode, one of {', '.join(modes(sport))}. Unset = {engine_of(sport)} (sports/{sport}.toml "
                         "[sweep] stages)."))
    extra = [replace(s, **over.get(s.name, {})) for s in SS.SHARED_SETTINGS]
    spec_ = list(base.SPEC) + [s for s in extra if s.name not in base.BY]
    return type(f"{base.__name__}Sweep", (base,), dict(SPEC=spec_, BY={s.name: s for s in spec_}, MODEL=list(base.MODEL),
                                                       DEFAULT_VENUE=vs[0], SPORT=sport))


# --- the season ------------------------------------------------------------------------------------------

def run(engine, engine_url, sport, year, rounds=None, settings=None, fetch=False, reprice=False, echo=print):
    """The sport's season sweep in its stage mode (mode_of: the `stages` setting, else the schema's default).
    settings: settings_class(sport) (None = the defaults). rounds: event numbers within the season (1 = its first
    raced event), None = all. fetch / reprice: the "sessions" mode's (Polymarket download, re-pricing stored stages)."""
    if mode_of(sport, settings) == "sessions":
        from racinglines.pipelines import weekend_sweep as SW
        return SW.run_sweep(engine, engine_url, year, rounds, fetch=fetch, reprice=reprice, settings=settings, echo=echo)
    return replay_sweep(engine, sport, year, rounds, settings, echo)


def _rounds(rs, rounds):
    rs = rs.assign(round=np.arange(1, len(rs) + 1))
    return rs[rs["round"].isin(list(rounds))] if rounds else rs


def data_key(data):
    """Fingerprint of the model's data (row count and numeric column sums, database ids left out), as
    sweep_settings.data_key does for F1's stages."""
    if not isinstance(data, pd.DataFrame):
        return None
    num = data.select_dtypes("number")
    num = num[[c for c in num.columns if not (c == "id" or str(c).endswith("_id"))]]
    blob = f"{len(data)}:{float(num.fillna(0).to_numpy().sum()) if len(num.columns) else 0:.8g}"
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def replay_sweep(engine, sport, year, rounds=None, settings=None, echo=print):
    """The "weekend" mode: per race, the field (its start list: the entrants with a race result, known before the
    start), one pricing by the sport's model as of the event's first day, each [replay] stage read on the venue
    (price, bid / ask, 24 h volume, open, coherent group), the takers and makers traded, then the race settled."""
    from racinglines.markets.strategies import maker_replay as R
    from racinglines.models.race_model import Event
    from racinglines.pipelines import position_replay as P
    from racinglines.pipelines import weekend_sweep as SW
    cls = settings_class(sport)
    st = settings if settings is not None else cls.from_dict()
    venue = SS.venue_of(st)
    if venue not in venues(sport):
        raise ValueError(f"{sport}: venue {venue!r} is not one of {venues(sport)}")
    sw = spec(sport)
    sp = dict(P.spec(sport), kinds=[k for k in kinds(sport) if k in st["market_kinds"]])
    model = P.model_for(sp)
    ms = model.Settings.from_dict({k: st[k] for k in model.Settings.BY})
    base, params_list = SW.taker_params(st)
    with engine.connect() as conn:
        rs = _rounds(P.races(conn, sp, [year]), rounds)
        lk = P.links(conn, sp, venue)
    echo(f"progress {sport} {year} on {venue}: {len(rs)} races, {len(lk)} markets of kinds {', '.join(sp['kinds'])}")
    data = model.load(engine.url.render_as_string(hide_password=False))
    hist = model.history(data, ms)
    tol = SS.parse_map(st["coherence_tol_by_kind"])
    thin = st["thin_edge_mult"] is not None
    events = [dict(round=int(r.round), event_key=r.event_key, event=str(r.name), format=None,
                   stages=len(sp["stages"]), last_run_id=None, race=r) for r in rs.itertuples()]

    def trade_event(ev, plist, widen_kinds):
        r = ev["race"]
        race_links = lk[lk["race_id"] == r.race_id] if len(lk) else lk
        if not len(race_links):
            return None
        stages = P.stage_times(r.start, sp)
        day = pd.Timestamp(r.start) + pd.Timedelta(days=int(sp.get("race_day_offset", 0)))
        until = day + pd.Timedelta(hours=float(sw["quote_until_hours"]))
        with engine.connect() as conn:
            res = P.race_results(conn, r.race_id)
            if res.empty:
                return None
            field = sorted(int(a) for a in res["athlete_id"])
            sims = model.price(hist, Event(id=r.event_key, season=int(r.season), cutoff=r.start, name=str(r.name),
                                           info={"field": field}), ms,
                               np.random.default_rng([ms.rng_seed, zlib.crc32(str(r.event_key).encode())]))
            v = P._venue(conn, venue, race_links, stages, sp)
            v.tol_by_kind = dict(tol)
            if thin:
                v.load_books(conn, min(t for _, t in stages) - timedelta(hours=1), max(t for _, t in stages))
            markets = race_markets(v, race_links, sims, res, stages, st["min_volume_24h"], thin)

            def tape():
                return maker_event(conn, race_links, venue, sims, res, stages, until, books=st["fill"] == "queue")
            return SW.trade(markets, [lab for lab, _ in stages], plist, st, tape, widen_kinds, tuple(sp["kinds"]), echo)

    out = SW.season(events, trade_event, st, params_list, stage_labels(sport), echo=echo)
    return dict(out, params=dict({k: v for k, v in base.__dict__.items() if k != "stages" and not
                                  (k in ("scale", "max_deployed", "min_edge_by_kind", "thin_edge_mult", "kelly", "bankroll")
                                   and v == SW.RB.TakerParams.__dataclass_fields__[k].default)},
                                 sport=sport, venue=venue, model=model.name, stages_mode="weekend",
                                 n_sims=ms.get("sims"), stages=[list(x) for x in sp["stages"]], kinds=list(sp["kinds"]),
                                 min_volume_24h=st["min_volume_24h"], coherence_tol=P.COHERENCE_TOL,
                                 group_target=dict(sp.get("group_target") or {}), quote_until_hours=sw["quote_until_hours"],
                                 settings=st.to_json(), settings_key=st.key, model_key=st.model_key, data_key=data_key(data),
                                 label=st.label(), weekends=len(out["weekends"])))


def race_markets(venue, race_links, sims, res, stages, min_volume_24h, thin_depth=False):
    """Per market: each stage's fair, exchange price (and bid / ask where the venue quotes one, so a taker buys at
    the ask and sells at the bid), tradeable flag and the outcome, in the shape taker_weekend.run_weekend reads.
    The F1 sweep's rules (weekend_sweep.weekend_markets): tradeable = priced inside (0, 1), over the volume floor,
    open, a coherent group; with thin_depth, a stage that fails only the volume floor is marked `thin` with the size
    at the touch. Fairs and settlement: pipelines/position_replay.py."""
    from racinglines.pipelines import position_replay as P
    coherent = {(k, lab): venue.coherent(k, t) for lab, t in stages for k in venue.group_target}
    out = []
    for link in race_links.to_dict("records"):
        kind, a = link["prediction"], int(link["athlete_id"])
        b = (link["params"] or {}).get("opponent_id")
        f = P.fair(sims, kind, a, b) if sims is not None else None
        st = []
        for lab, t in stages:
            price, _, liquid = venue.view(link, t, min_volume_24h)
            open_ = P._open(link, t)
            ok = liquid and f is not None and open_ and coherent.get((kind, lab), True)
            stage = dict(label=lab, t=t, fair=f, price=price, tradeable=ok, open=open_)
            q = venue.quote(link["token_id"], t)
            if q is not None:
                stage.update(bid=q[0], ask=q[1])
            if thin_depth and not liquid and price is not None and 0 < price < 1 and f is not None and open_ \
                    and coherent.get((kind, lab), True):
                d = venue.touch_depth(link["token_id"], t)
                if d is not None and (d[0] > 0 or d[1] > 0):
                    stage.update(thin=True, depth_yes=d[0], depth_no=d[1])
            st.append(stage)
        subject = link.get("athlete") or link.get("group_title")
        if kind == "race_h2h":
            subject = f"{subject} v {b}"
        out.append(dict(key=link["token_id"], kind=kind, subject=subject, stages=st, link=link,
                        outcome=P.settle(kind, a, b, res)))
    return out


def maker_event(conn, race_links, venue, sims, res, stages, until, books=False):
    """The maker replay's event (maker_replay.replay): the race's markets from the venue's tape, each stage quoting
    from its time to the next stage's (the last to `until`, then pulled), fairs keyed by the stage's index."""
    from racinglines.markets.strategies import maker_replay as R
    from racinglines.pipelines import position_replay as P
    times = [t for _, t in stages] + [pd.Timestamp(until)]
    st = [dict(run_id=i, start=R._ns(times[i]), end=R._ns(times[i + 1]), session_end=i == len(stages) - 1)
          for i in range(len(stages)) if times[i + 1] > times[i]]
    if not st:
        raise ValueError(f"no maker stage before {until} (quote_until_hours)")

    def fairs_of(link):
        b = (link["params"] or {}).get("opponent_id")
        f = P.fair(sims, link["prediction"], int(link["athlete_id"]), b) if sims is not None else None
        return {s["run_id"]: f for s in st}

    def outcome_of(link, mids):
        return P.settle(link["prediction"], int(link["athlete_id"]), (link["params"] or {}).get("opponent_id"), res)

    t0, t1 = st[0]["start"] - int(48 * 3600e9), st[-1]["end"] + int(6 * 3600e9)
    markets = R.tape_markets(conn, race_links, venue, t0, t1, fairs_of, outcome_of, books)
    return dict(markets=markets, stages=st, qual_start=None, runs=[dict(run_id=s["run_id"], cutoff=s["start"]) for s in st])


# --- saving, for the CLI and the search -------------------------------------------------------------------

def save(engine_url, sport, year, rounds, out, reliability=False):
    """Store one sweep (model_runs kind 'sweep', the sport's competition, params with sport and venue); its id."""
    from racinglines.db.config import get_session
    from racinglines.db.queries import records, save_model_run
    s_ = sports.load(sport)
    comp = s_["competition"]
    with get_session(engine_url) as s:
        return save_model_run(s, competition=comp["code"], season=year, category=next(iter(comp.get("categories") or {}), None),
                              model=out["params"].get("model") or "sweep", kind="sweep",
                              params=dict(out["params"], year=year, rounds=rounds),
                              metrics=dict(weekends=records(out["weekends"]), totals=out["totals"],
                                           by_stage=records(out["by_stage"]), by_kind=records(out["by_kind"]),
                                           scores=records(out["scores"]),
                                           **(dict(calibration=records(out["calibration"]),
                                                   reliability=records(out["reliability"])) if reliability else {})))
