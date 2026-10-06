"""
racinglines f1 <command>: Formula 1.

  Data
    fetch        Download sessions from the F1 live-timing archive (FastF1) to data/raw/f1/fastf1/.
    ingest       Load data/raw/f1/fastf1/ into the database (events, results, laps, track profiles).
    (exchange data: racinglines markets sync | history | trades | record | archive)

  Pricing (all through models.position_sim.pricing.price_race with a hard as-of cutoff)
    backtest     HISTORICAL: price every past race as of just before qualifying and just
                 before the race; score against outcomes. Saved as kind='backtest'.
    compare      Two saved backtest runs, paired by race: challenger − baseline ± 2 SE per metric
                 and pricing stage (the roadmap's promotion evidence); --reliability adds calibration.
    matrix       Every model variant x every trading strategy: accuracy (latest saved backtest per
                 variant, paired vs baseline) and 2026 P&L (latest sweep + season strategy per variant).
    diagnostic   ONE PAST EVENT at a chosen cutoff (e.g. yesterday); saved as kind='diagnostic'.
    sweep        Every race of a season traded through the weekend: price before any running
                 and after each session, trade Polymarket (update / hold / after-quali taker
                 strategies, maker replay), settle; per-weekend P&L. Saved as kind='sweep'.
    season-strategy  Default championship-market strategy through the season: as-of season
                 forecasts pre-season and after every race, trades at Polymarket's recorded
                 prices (+ spread and slippage), settles eliminated markets, marks the rest.
    season-checkpoints  Championship markets entered at fixed points (pre-season, after 3 and
                 after 6 grands prix) and held, per model variant: P&L over the next 3 GPs and
                 to date, and how far the market moved toward our fair value.
    scorecard    ONE EXCHANGE WEEKEND (or --all: a season), traded or not: the stored stage runs' fair
                 values at each stage cutoff scored against the result and against the venue's mid
                 (Polymarket, Kalshi or both). Nothing is priced or stored; writes data/runs/f1/scorecard/.
    replay       Replay a maker quoting Polymarket from one or more diagnostic runs against
                 the real trade tape; fills, inventory, P&L at resolution, mark-outs.
    forecast     LIVE: cutoff = now; upcoming races + championships. Saved as kind='forecast'
                 (the only kind the web app uses for live fair prices).
    props        Race props (safety car, red flag, rain, fastest lap) for one event from the race
                 history, or --check: their walk-forward calibration (models/position_sim/props.py).
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # the repository


def _years(spec):
    if "," in spec:
        return [int(y) for y in spec.split(",")]
    a, _, b = spec.partition("-")
    return list(range(int(a), int(b or a) + 1))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="racinglines f1", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="Database URL (default: $DATABASE_URL / docker-compose).")
    ap.add_argument("--variant", default="baseline",
                    help="Model variant for pricing (position_sim/variants.py), e.g. grid, gbm, grid+tail. "
                         "Saved runs record it.")
    ap.add_argument("--half-life", type=float, default=None,
                    help="Recency half-life in days for the pace models (default: position_sim.model.HALF_LIFE_DAYS).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--years", default="2026,2025,2024,2023,2022,2021,2020")
    p.add_argument("--sessions", default="Q,S,R", help="Q,S,R and/or practice FP1,FP2,FP3,SQ")
    p.add_argument("--rounds", default=None, help="Only these rounds, e.g. 6-15")
    p.add_argument("--sprints-from", type=int, default=None, help="Fetch sprint races from this season on (default 2026).")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("ingest")
    p.add_argument("--years", default="2020-2026")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("pm-sync")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--closed", action="store_true", help="Also every closed event of that year (e.g. a past season).")
    p.add_argument("--alert", action="store_true", help="Notify about markets seen for the first time (markets/alerts.py).")
    p = sub.add_parser("signals", help="Live paper signals of users' strategy profiles (pipelines/signals.py). "
                                       "Recommendations only: never places an order.")
    p.add_argument("--profile", default=None, help="Candidate id, name, or A / C (default: each user's own).")
    p.add_argument("--user", nargs="*", default=None, help="Only these usernames.")
    p.add_argument("--event", default="next", help="next (default), a round number, or YEAR-ROUND.")
    p.add_argument("--asof", default=None, help="Replay at this UTC time (prints only; markets read at each "
                                               "stage's cutoff, like the sweep).")
    p.add_argument("--no-fetch", action="store_true", help="Don't refresh FastF1 / Polymarket data first.")
    p.add_argument("--no-alert", action="store_true")
    p = sub.add_parser("demo-history", help="Backfill the demo accounts' track record from backtest replays "
                                            "(pipelines/demo_history.py).")
    p.add_argument("--reset", action="store_true", help="Delete the existing backfill first.")
    p.add_argument("--user", nargs="*", default=None, help="Only these demo accounts (maker, taker).")
    p.add_argument("--venue", default="polymarket", choices=["polymarket", "kalshi"],
                   help="Whose recorded tape the maker replays (kalshi: the maker's Kalshi record; maker accounts only).")
    p = sub.add_parser("reconcile", help="One account's live paper weekend against the backtest's replay of it on the "
                                         "recorded tape (pipelines/reconcile.py; docs/paper-trading.md, rule 1). "
                                         "Exit 1 when flagged, 2 without live rows.")
    p.add_argument("--event", required=True, help="YEAR-ROUND, e.g. 2026-16.")
    p.add_argument("--profile", required=True, help="Candidate id, name, or A / C / M1-M3.")
    p.add_argument("--venue", default="polymarket", choices=["polymarket", "kalshi"])
    p.add_argument("--user", default=None, help="The account (default: the profile's demo account).")
    p.add_argument("--replicates", type=int, default=2,
                   help="Seed replicates for the noise band besides the profile's seed (default 2: seeds 43 and 44; "
                        "their stage pricings are cached like a sweep's).")
    p.add_argument("--no-price", action="store_true", help="Read-only on the database: only replicates whose stage "
                                                          "pricings are already cached.")
    p.add_argument("--asof", default=None, help="Replay as of this UTC time instead of a day after the race.")
    p.add_argument("--markdown", action="store_true", help="Also print the block for the weekend report.")
    p = sub.add_parser("profiles", help="List strategy profiles; create A / C / K as Lab candidates if missing.")
    p.add_argument("--assign-demo", action="store_true", help="Demo taker -> A, demo maker -> C.")
    p.add_argument("--venue", default="polymarket", choices=["polymarket", "kalshi"],
                   help="With --assign-demo: kalshi assigns the demo maker K as its Kalshi profile "
                        "(users.prefs['strategy_profile_kalshi']) and leaves the Polymarket profiles alone.")
    for name, hlp in (("pm-links-export", "Write market links to data/archive/markets/<exchange>/links/ (stable keys)."),
                      ("pm-links-import", "Load that file into this database (no exchange access needed).")):
        sub.add_parser(name, help=hlp).add_argument("--exchange", default="polymarket", choices=["polymarket", "kalshi"])
    p = sub.add_parser("pm-history")
    p.add_argument("--events", nargs="+", required=True, help="Polymarket event slugs (or a prefix ending in %%).")
    p.add_argument("--start", required=True, help="UTC start, e.g. 2026-09-23T00:00")
    p.add_argument("--end", required=True, help="UTC end")
    p.add_argument("--fidelity", type=int, default=60, help="Minutes per point (1 = minute-level).")
    p = sub.add_parser("pm-trades")
    p.add_argument("--events", nargs="+", required=True, help="Polymarket event slugs (or a prefix ending in %%).")
    p = sub.add_parser("pm-record")
    p.add_argument("--events", nargs="*", help="Event slugs / prefixes (default: open markets of races not yet run).")
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--minutes", type=int, default=0, help="Stop after this many minutes (0 = run until stopped).")
    p.add_argument("--sync-every", type=int, default=30, help="Re-sync Polymarket's F1 events every N minutes "
                                                              "so new race markets get recorded (0 = never).")
    p.add_argument("--no-alerts", action="store_true", help="Don't notify about new markets found by the re-sync.")
    p.add_argument("--year", type=int, default=2026)
    p = sub.add_parser("pm-archive")
    p.add_argument("--hours", type=float, default=None,
                   help="Archive every row older than this instead of the retention policy (keep upcoming / "
                        "in-progress races, the latest completed race, the last 7 days of open season markets).")
    p.add_argument("--vacuum-full", action="store_true", help="Return freed space to the OS (locks the tables briefly).")
    p.add_argument("--compact", action="store_true", help="Also merge each month into one deduplicated file.")
    p.add_argument("--stats", action="store_true", help="Only show where the rows are.")
    p = sub.add_parser("record", help="Live F1 session recorder: fetch current session via FastF1 and store snapshot to database.")
    p.add_argument("--status", action="store_true", help="Show last passes and snapshots stored (default: record one snapshot).")
    p = sub.add_parser("sweep")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--rounds", default=None, help="e.g. 1-15 (default: every raced round)")
    p.add_argument("--no-fetch", action="store_true", help="Don't download Polymarket history/trades.")
    p.add_argument("--fetch-only", action="store_true", help="Only download the season's Polymarket history/trades.")
    p.add_argument("--reprice", action="store_true", help="Re-price stages even if stored.")
    p.add_argument("--save", action="store_true")
    p.add_argument("--reliability", action="store_true",
                   help="Also score calibration: our fair values and Polymarket's prices at every tradeable stage, "
                        "per market kind (Brier, log loss, ECE, reliability bins); saved with --save.")
    p.add_argument("--grid", default=None, metavar="FILE.json",
                   help="Several settings in one process: a JSON list of {\"job\": id, \"settings\": {...}}, each "
                        "swept as if alone (same results and saved runs) while sharing the measurements, stage "
                        "pricings, markets and maker tape. Prints 'Saved sweep run N for job ID.' per entry "
                        "(the search's maker_grid). The settings flags are ignored.")
    from racinglines.pipelines import sweep_settings as _SS
    _SS.add_arguments(p.add_argument_group("settings (racinglines/pipelines/sweep_settings.py; default = baseline)"))
    p = sub.add_parser("season-strategy")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--sims", type=int, default=5000)
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--reforecast", action="store_true")
    p.add_argument("--min-edge", type=float, default=0.03)
    p.add_argument("--stake-per-edge", type=float, default=500.0)
    p.add_argument("--max-stake", type=float, default=150.0)
    p.add_argument("--capital", type=float, default=1500.0)
    p.add_argument("--save", action="store_true")
    p.add_argument("--paper", action="store_true",
                   help="The championship sleeve (paper only): replay through the decision after --after-round on "
                        "--venue and store that rebalance as the demo maker's paper positions "
                        "(venue 'season:<venue>', kept out of the weekend records). Off unless given.")
    p.add_argument("--venue", choices=("polymarket", "kalshi", "og"), default="polymarket",
                   help="The exchange: Polymarket's championship markets (the default), Kalshi's KXF1 / "
                        "KXF1CONSTRUCTORS champion markets, or OG.com's drivers' and constructors' champion contracts "
                        "(the replay only, not --paper). Kalshi and OG.com replay their stored tape (no fetch)")
    p.add_argument("--after-round", type=int, default=None, help="With --paper: the round just raced (default: the last)")
    p.add_argument("--user", default=None, help="With --paper: the account (default: the demo maker)")
    p = sub.add_parser("season-checkpoints")
    p.add_argument("--variants", default=None,
                   help="Comma-separated model variants (default: every variant whose season forecast "
                        "differs, and the combos)")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--entries", default="0,3,6", help="Grands prix completed at each entry")
    p.add_argument("--window", type=int, default=3, help="Grands prix per scoring window")
    p.add_argument("--sims", type=int, default=5000)
    p.add_argument("--save", action="store_true")
    p.add_argument("--out", default=None, help="Markdown file (default data/runs/f1/season_checkpoints.md)")
    p = sub.add_parser("search")
    p.add_argument("queue", help="Queue file, e.g. sweeps/poc.toml (re-read while running: edit it to steer)")
    p.add_argument("--leaderboard", action="store_true", help="Only rewrite the leaderboard from state.json")
    p = sub.add_parser("search-report")
    p.add_argument("queue", help="The search's queue file: labels, noise floor, confirmations and candidates from its "
                                 "finished jobs (an optional [report] table configures it)")
    p = sub.add_parser("search-import")
    p.add_argument("results", help="A search's results.json (e.g. from a cloud session)")
    p = sub.add_parser("search-analyze", help="Analyze saved F1 sweep-search runs and write report artifacts "
                                              "(curves, rankings, charts, noise, HTML; beside search-report).")
    p.add_argument("search", help="Search name under data/runs/search/.")
    p.add_argument("--write-candidates", action="store_true", help="Regenerate ranked candidate JSON and TOML files.")
    p.add_argument("--plot", action="store_true", help="Write the top/bottom cumulative P&L chart.")
    p.add_argument("--noise", action="store_true", help="Write the report-specific Monte Carlo noise summary.")
    p.add_argument("--html", metavar="MARKDOWN", help="Render this Markdown report to HTML in the search directory.")
    p = sub.add_parser("scorecard", help="Pricing scorecard of an exchange weekend (pipelines/scorecard.py): the stored "
                                         "stage runs' fair values vs the result and vs the venue's mid at each stage.")
    p.add_argument("--event", default=None, help="Season-round, e.g. 2026-15")
    p.add_argument("--all", action="store_true", help="Every raced weekend of --year instead.")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--rounds", default=None, help="With --all: only these rounds, e.g. 1-15")
    p.add_argument("--venue", default="polymarket", choices=["polymarket", "kalshi", "both"])
    p.add_argument("--model-key", default=None, help="Stage runs of this model_key (default: the sweep defaults for --variant).")
    p.add_argument("--out", default=None, help="Output folder (default data/runs/f1/scorecard/).")
    p = sub.add_parser("replay")
    p.add_argument("--runs", required=True, help="Diagnostic run ids in time order, e.g. 11,9")
    p.add_argument("--sweep", action="store_true", help="Also sweep half-spread and fill rule.")
    p = sub.add_parser("backtest")
    p.add_argument("--start-year", type=int, default=2021)
    p.add_argument("--sims", type=int, default=4000)
    p.add_argument("--no-track", action="store_true", help="Only the run without track features.")
    p.add_argument("--out", default=None, help="Per-race rows CSV (default data/runs/f1/backtests/).")
    p.add_argument("--save", action="store_true", help="Store as a model run (kind='backtest').")
    p.add_argument("--races", type=int, default=None, help="Only the last N races (quick runs).")
    p.add_argument("--track", choices=["both", "on", "off"], default="both", help="Track features: compare both, or one.")
    p = sub.add_parser("compare")
    p.add_argument("baseline", type=int, help="Saved backtest run id (the reference)")
    p.add_argument("challenger", type=int, help="Saved backtest run id to compare against it")
    p.add_argument("--reliability", action="store_true", help="Also print reliability tables (runs saved with probabilities)")
    p = sub.add_parser("matrix")
    p.add_argument("--variants", default="baseline,grid,gridq,pretrain,gbm,tail,gridq+pretrain",
                   help="Comma-separated model variants (rows)")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--out", default=None, help="Markdown file (default data/runs/f1/matrix.md)")
    p = sub.add_parser("diagnostic")
    p.add_argument("--event", required=True, help="Season-round, e.g. 2026-15")
    p.add_argument("--cutoff", required=True, help="UTC as-of time, e.g. 2026-09-25T23:59")
    p.add_argument("--sims", type=int, default=10000)
    p.add_argument("--no-track", action="store_true")
    p.add_argument("--save", action="store_true")
    p = sub.add_parser("forecast")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--sims", type=int, default=10000)
    p.add_argument("--save", action="store_true")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--no-track", action="store_true")
    p.add_argument("--scenario", default=None, metavar="LABEL",
                   help="Save as kind='scenario' (not used for live prices until promoted in the web app).")
    p = sub.add_parser("inrace-backfill", help="After a race: the Live tab's in-race win chart from the race's laps, "
                                               "one point per lap, as if the live-timing relay had run all race.")
    p.add_argument("--event", required=True, help="YEAR-ROUND, e.g. 2026-16.")
    p = sub.add_parser("props", help="Race props: safety car, red flag, rain, fastest lap (props.py).")
    p.add_argument("event", nargs="?", default=None, help="Season-round, e.g. 2026-16 (the yes/no props)")
    p.add_argument("--run", type=int, default=None, help="A stored stage run id: adds the fastest-lap prices")
    p.add_argument("--check", action="store_true", help="Walk-forward calibration of the yes/no props")
    p.add_argument("--from", dest="start_year", type=int, default=2022, help="--check: first season scored")
    p.add_argument("--prior-n", type=float, default=None, help="Shrinkage to the field rate, in races (default: props.PRIOR_N)")
    p.add_argument("--history", default=None, metavar="CSV",
                   help="--check: score a history CSV (props.history()'s columns) instead of the database")
    p.add_argument("--dnf-check", default=None, metavar="CSV",
                   help="The position simulation's DNF calibration on an as-of export (position_sim/dnf_check.py)")
    p.add_argument("--forecast", default=None, metavar="CSV",
                   help="--check / --dnf-check: the weather leads CSV (racinglines weather leads; weather/wet.py "
                        "p_wet_series) adds the -WX variants; needs a race history (--history CSV or the database)")
    p.add_argument("--lead", type=int, default=5, help="--forecast: the forecast issued this many days before (default 5)")
    args = ap.parse_args(argv)
    from racinglines.models.position_sim import variants as V
    V.switches(args.variant)                         # fail fast on an unknown name
    with V.use(args.variant):
        return _run(args)


def _season_sleeve(args, engine, prm, SE, get_session, records):
    """f1 season-strategy --paper: the championship sleeve's rebalance after one round on one exchange, stored
    as paper positions (and, with --save, as a model run of kind 'season_sleeve')."""
    from sqlalchemy import text
    echo = lambda m: print(m, flush=True)   # noqa: E731
    username = args.user or SE.SLEEVE_USER
    with engine.connect() as c:
        uid = c.execute(text("SELECT id FROM users WHERE username = :u"), dict(u=username)).scalar()
    if uid is None:
        sys.exit(f"no user {username!r}")
    if args.venue == "polymarket" and not args.no_fetch:
        with engine.connect() as c:
            links = SE.season_links(c, args.year, args.venue)
        with engine.connect() as c, get_session(args.db) as s:
            SE.fetch_history(s, c, links["token_id"].tolist(), echo=echo)
    out = SE.sleeve_rebalance(engine, args.db, args.year, args.after_round, exchange=args.venue, params=prm,
                              n_sims=args.sims, variant=args.variant, echo=echo)
    with engine.begin() as c:
        n = SE.store_sleeve(c, uid, out)
    sm = out["summary"]
    print(f"\n=== Championship sleeve on {args.venue}, {out['label']} ({out['markets']} markets) ===")
    print(f"  decision {out['t']:%Y-%m-%d %H:%M} UTC, executed {out['exec_at']:%H:%M}, forecast run #{out['run_id']}")
    print(f"  {sm['trades']} trades at this decision; {sm['positions']} open positions, {sm['settled']} settled; "
          f"P&L to date {sm['pnl']:+,.2f}")
    print(f"  stored {n} paper positions for {username!r} (venue {out['venue']!r}, event {out['event_key']!r})")
    if len(out["trades"]):
        print("\n=== Trades ===")
        print(out["trades"].drop(columns=["key", "decision"]).to_string(index=False, float_format="{:.3f}".format))
    if out["positions"]:
        import pandas as pd
        print("\n=== Positions ===")
        print(pd.DataFrame(out["positions"]).drop(columns=["market_key"]).to_string(index=False, float_format="{:.3f}".format))
    if args.save:
        from racinglines.db.queries import save_model_run
        tr = out["trades"]
        with get_session(args.db) as s:
            run_id = save_model_run(
                s, competition="f1_wdc", season=args.year, category="DRV", model="season_strategy", kind="season_sleeve",
                params=dict({k: (str(v) if hasattr(v, "total_seconds") else v) for k, v in prm.__dict__.items()},
                            year=args.year, variant=args.variant, venue=args.venue, after_round=out["after_round"],
                            label=out["label"], t=str(out["t"]), forecast_run=out["run_id"], user=username,
                            min_volume=SE.MIN_VOLUME, slippage=SE.SLIPPAGE),
                metrics=dict(summary=sm, positions=out["positions"],
                             trades=records(tr.assign(t=tr["t"].astype(str))) if len(tr) else []))
        print(f"Saved sleeve run {run_id}.")


def _save_sweep(args, out):
    """Store one sweep (kind='sweep'); returns its run id."""
    from racinglines.db.config import get_session
    from racinglines.db.queries import records, save_model_run
    with get_session(args.db) as s:
        return save_model_run(s, competition="f1_wdc", season=args.year, category="DRV", model="f1_sector_sim",
                              kind="sweep", params=dict(out["params"], year=args.year, rounds=args.rounds),
                              metrics=dict(weekends=records(out["weekends"]), totals=out["totals"],
                                           by_stage=records(out["by_stage"]), by_kind=records(out["by_kind"]),
                                           scores=records(out["scores"]),
                                           **(dict(calibration=records(out["calibration"]),
                                                   reliability=records(out["reliability"]))
                                              if args.reliability else {})))


def _run(args):
    import pandas as pd
    pd.set_option("display.width", 220)
    fmt = {c: "{:.1%}".format for c in ("win_prob", "podium_prob", "top10_prob", "pole_prob", "dnf_prob",
                                         "champion_prob", "top3_prob")}

    if args.cmd == "fetch":
        from racinglines.sources.fastf1 import fetch
        sys.argv = (["fetch", "--years", args.years, "--sessions", args.sessions] + (["--force"] if args.force else [])
                    + (["--rounds", args.rounds] if args.rounds else [])
                    + (["--sprints-from", str(args.sprints_from)] if args.sprints_from else []))
        return fetch.main()

    from racinglines.db.config import get_engine, get_session
    from racinglines.db.queries import records
    engine = get_engine(args.db)

    if args.cmd == "ingest":
        from racinglines.sources.fastf1.ingest import ingest
        with get_session(args.db) as s:
            print("Done:", ingest(s, _years(args.years), force=args.force))
        return
    if args.cmd == "inrace-backfill":
        from racinglines.pipelines import live_f1 as LF
        year, rnd = (int(x) for x in args.event.split("-"))
        LF.backfill_inrace(year, rnd)
        return
    if args.cmd == "props":
        from racinglines.models.position_sim import props as PR
        prior_n = PR.PRIOR_N if args.prior_n is None else args.prior_n
        fc = hist = None
        if args.forecast:
            from racinglines.weather import wet as WET
            if args.history:
                hist = pd.read_csv(args.history)
            else:
                with engine.connect() as c:
                    hist = PR.history(c)
            fc = WET.p_wet_series(hist, pd.read_csv(args.forecast), args.lead, prior_n=prior_n)
        if args.dnf_check:
            from racinglines.models.position_sim import dnf_check as DC
            wx = {} if fc is None else dict(forecast=fc, history_df=hist, prior_n=prior_n)
            print(DC.render(DC.check(pd.read_csv(args.dnf_check), **wx)))
            return
        if args.check and args.history:
            h = hist if hist is not None else pd.read_csv(args.history)
            _, summ = PR.check(None, args.start_year, prior_n, history_df=h, forecast=fc)
            print(summ.to_string(index=False, float_format="{:.4f}".format))
            return
        with engine.connect() as c:
            if args.check:
                _, summ = PR.check(c, args.start_year, prior_n, forecast=fc)
                print(summ.to_string(index=False, float_format="{:.4f}".format))
                return
            if not args.event:
                sys.exit("give an event (e.g. 2026-16) or --check")
            kinds = PR.PROP_KINDS if args.run else tuple(PR.BINARY)
            for mk in PR.markets(c, args.event, args.run, kinds, prior_n):
                name = "" if mk["subject"] == PR.LABEL[mk["kind"]] else mk["subject"]
                print(f"{PR.LABEL[mk['kind']]:12} {name:24} {mk['fair']:.1%}")
        return
    if args.cmd in ("pm-links-export", "pm-links-import"):
        from racinglines import paths
        from racinglines.markets.polymarket import links as L
        x = {} if args.exchange == "polymarket" else dict(exchange=args.exchange)
        path = L.path_for(args.exchange)
        if args.cmd == "pm-links-export":
            print(f"exported {L.export(engine, path, **x)} market links -> {paths.rel(path)}")
        else:
            print(f"imported market links: {L.import_(engine, path)}")
        return
    if args.cmd == "demo-history":
        from racinglines.pipelines import demo_history as DH
        from racinglines.pipelines import profiles as PF
        if args.reset:
            print(f"deleted {DH.reset(engine, args.user or list(PF.HISTORY), **({} if args.venue == 'polymarket' else dict(venue=args.venue)))} backfilled signals")
        rep = DH.backfill(engine, args.db, usernames=args.user, echo=lambda m: print(m, flush=True),
                          **({} if args.venue == "polymarket" else dict(venue=args.venue)))
        for u in sorted({r[0] for r in rep}):
            for y in ("2025", "2026"):
                rs = [r for r in rep if r[0] == u and r[2].startswith(y)]
                if rs:
                    print(f"{u} {y}: {len(rs)} weekends, paper P&L {sum(r[4] for r in rs):+.2f}")
        return
    if args.cmd == "reconcile":
        from racinglines.pipelines import reconcile as RC
        res = RC.reconcile(engine, args.db, args.event, args.profile, venue=args.venue, user=args.user,
                           replicates=RC.seeds(args.replicates), price=not args.no_price, now=args.asof,
                           echo=lambda m: print(m, flush=True))
        print(RC.format_table(res))
        if args.markdown:
            print()
            print(RC.format_markdown(res))
        if not res["live"]["signals"] and not res["live"]["positions"]:
            sys.exit(2)
        if not res["verdict"]["ok"]:
            sys.exit(1)
        return
    if args.cmd == "profiles":
        from racinglines.pipelines import profiles as PF
        with engine.begin() as c:
            ids = PF.ensure_candidates(c)
            if args.assign_demo:
                print("assigned:", PF.assign_demo(c, **({} if args.venue == "polymarket" else dict(venue=args.venue))))
            for code, i in ids.items():
                pr = PF.PROFILES[code]
                print(f"{code}  candidate #{i}  {pr['name']}" + (f"  [{pr['venue']}]" if pr.get("venue") else ""))
            for uid, name, role, prof in PF.assigned(c):
                print(f"  user {name} ({role}) -> {prof['name']} (#{prof.get('candidate_id')})")
            for uid, name, role, prof in PF.assigned(c, venue="kalshi"):
                print(f"  user {name} ({role}) -> {prof['name']} (#{prof.get('candidate_id')}) on kalshi")
        return
    if args.cmd == "signals":
        from racinglines.pipelines import signals as SG
        if args.asof:
            from racinglines.pipelines import profiles as PF
            with engine.connect() as c:
                profs = [PF.load(c, args.profile)] if args.profile else [
                    p for _, n, _, p in PF.assigned(c) if not args.user or n in args.user]
            for prof in profs:
                for out in SG.compute_all(engine, args.db, prof, now=args.asof, event=args.event, live=False,
                                          fetch=not args.no_fetch, echo=lambda m: print(m, flush=True)):
                    print(SG.format_replay(out))
            return
        rep = SG.run_all(engine, args.db, users=args.user, profile_ref=args.profile, event=args.event,
                         fetch=not args.no_fetch, alert=not args.no_alert, echo=lambda m: print(m, flush=True))
        if not rep:
            print("no user has a strategy profile (racinglines f1 profiles --assign-demo)")
        return
    if args.cmd == "pm-sync":
        from racinglines.markets.polymarket.sync import sync
        with engine.connect() as c, get_session(args.db) as s:
            if args.alert:
                from racinglines.markets import alerts
                stats, groups, used = alerts.sync_and_alert(s, c, args.year, include_closed=args.closed)
                print(stats)
                for g in groups:
                    print(f"  new: {g['event_title']} ({g['n']} outcomes{', upcoming race' if g['upcoming'] else ''})")
                if groups:
                    print(f"  alerted via {', '.join(used)}")
            else:
                print(sync(s, c, args.year, include_closed=args.closed))
        return
    if args.cmd == "pm-archive":
        from datetime import timedelta

        from sqlalchemy import text

        from racinglines.markets import store as MS
        if not args.stats:
            for name in MS.STORES:
                n = (MS.archive(engine, name, older_than=timedelta(hours=args.hours)) if args.hours
                     else MS.archive(engine, name, policy=True))
                if args.compact:
                    MS.compact(name)
                print(f"{name}: {n:,} rows moved to Parquet", flush=True)
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
                for s in MS.STORES.values():
                    c.execute(text(f"VACUUM {'FULL ' if args.vacuum_full else ''}{s['table']}"))
        for name, st in MS.stats(engine).items():
            print(f"{name:7s} Postgres {st['postgres_rows']:>10,} rows {st['postgres_mb']:8.1f} MB · "
                  f"Parquet {st['parquet_rows']:>10,} rows {st['parquet_mb']:8.1f} MB in {st['parquet_files']} files")
        return
    if args.cmd == "record":
        from datetime import datetime, timezone
        from sqlalchemy import text
        from racinglines.web.f1_live import FastF1LiveClient

        if args.status:
            # Show status of past passes and stored snapshots
            with engine.connect() as c:
                log_file = "data/runs/logs/record-fastf1.log"
                import os
                if os.path.exists(log_file):
                    with open(log_file, "r") as f:
                        lines = f.readlines()
                    print("--- last passes")
                    for line in lines[-12:]:
                        print(line, end="")
                else:
                    print("no pass yet")
                print("\n--- FastF1 snapshots stored (last 24 hours)")
                result = c.execute(text("""
                    SELECT to_char(date_trunc('hour', timestamp) + floor(extract(minute FROM timestamp) / 60) * interval '1 min', 'HH24:MI') AS utc,
                           year, round, session_type, count(*) AS drivers_recorded
                    FROM fastf1_session_snapshots
                    WHERE timestamp > now() - interval '24 hours'
                    GROUP BY 1, 2, 3, 4
                    ORDER BY 1 DESC, 2, 3, 4
                """))
                for row in result:
                    print(f"{row[0]}  {row[1]} R{row[2]:2d}  {row[3]:10s}  {row[4]} drivers")
            return

        # Record one snapshot of current F1 session
        import asyncio

        async def record_snapshot():
            try:
                now = datetime.now(timezone.utc)

                # Check if we're in a race weekend window (calendar-aware polling)
                # Only poll during Thu-Sun of race weekends; skip Mon-Wed to avoid abusing FastF1
                with engine.connect() as c:
                    # Get the next upcoming/ongoing race to determine if we're in its weekend window
                    result = c.execute(text("""
                        SELECT e.year, e.round, r.event_date, r.status
                        FROM events e
                        JOIN races r ON r.event_id = e.id
                        WHERE e.year >= 2020 AND r.status IN ('upcoming', 'ongoing', 'completed')
                        ORDER BY (CASE r.status
                                   WHEN 'ongoing' THEN 0
                                   WHEN 'upcoming' THEN 1
                                   WHEN 'completed' THEN 2 END),
                                 r.event_date DESC
                        LIMIT 1
                    """))
                    race_row = result.fetchone()

                    if race_row:
                        year, round_num, event_date, race_status = race_row
                        # Calculate race weekend window: Wed before to Tue after the race
                        from datetime import timedelta
                        race_date = event_date.date() if hasattr(event_date, 'date') else event_date
                        # Go back to the Wednesday of that week
                        day_of_week = race_date.weekday()  # Monday=0, Sunday=6
                        if day_of_week >= 2:  # Wed(2)=onwards in the week of the race
                            days_back = day_of_week - 2
                        else:  # Mon/Tue - go back to previous week's Wed
                            days_back = day_of_week + 5  # Mon(0)->5 days back, Tue(1)->6 days back
                        wed_start = race_date - timedelta(days=days_back)
                        tue_end = wed_start + timedelta(days=6)  # Wed to following Tue

                        # Check if now is within the race weekend window
                        now_date = now.date()
                        if not (wed_start <= now_date <= tue_end):
                            # Outside race weekend - idle mode, just log and exit
                            return
                    else:
                        # No upcoming races found - idle mode
                        return

                # Detect current F1 session (we're in a race weekend window)
                with engine.connect() as c:
                    # Get upcoming/ongoing/completed races in priority order
                    result = c.execute(text("""
                        SELECT e.year, e.round, r.event_date, r.status
                        FROM events e
                        JOIN races r ON r.event_id = e.id
                        WHERE e.year >= 2020
                        ORDER BY (CASE r.status
                                   WHEN 'ongoing' THEN 0
                                   WHEN 'upcoming' THEN 1
                                   WHEN 'completed' THEN 2
                                   ELSE 3 END),
                                 e.year DESC, e.round DESC
                        LIMIT 1
                    """))
                    row = result.fetchone()
                    if not row:
                        print("no upcoming/ongoing race found", flush=True)
                        return
                    year, round_num, event_date, status = row

                # Fetch current session via FastF1 and store snapshot
                now = datetime.now(timezone.utc)
                client = FastF1LiveClient()

                # Determine which session is likely active: try Race first (most common for live), then Q
                for session_name in ["R", "Q", "S"]:
                    session = await client.get_session(year, round_num, session_name)
                    if session:
                        timing_data = await client.update_live_timing()
                        if not timing_data.get("error") and timing_data.get("drivers"):
                            # Store snapshot and driver positions
                            with engine.begin() as c:
                                snapshot_result = c.execute(text("""
                                    INSERT INTO fastf1_session_snapshots
                                    (timestamp, year, round, session_type, status, lap_count, time_remaining, laps_remaining, flag)
                                    VALUES (:ts, :year, :round, :session_type, :status, :lap_count, :time_remaining, :laps_remaining, :flag)
                                    RETURNING id
                                """), dict(
                                    ts=now,
                                    year=year,
                                    round=round_num,
                                    session_type=timing_data["session"]["session_type"],
                                    status=timing_data["session"]["status"],
                                    lap_count=timing_data["session"].get("lap_count"),
                                    time_remaining=timing_data["session"].get("time_remaining"),
                                    laps_remaining=timing_data["session"].get("laps_remaining"),
                                    flag=timing_data["session"].get("flag")
                                ))
                                snapshot_id = snapshot_result.scalar()

                                # Insert driver positions
                                for driver in timing_data["drivers"]:
                                    c.execute(text("""
                                        INSERT INTO fastf1_driver_positions
                                        (snapshot_id, position, driver_number, driver_name, team, gap_to_leader, last_lap_time, best_lap_time, status, lap_count)
                                        VALUES (:snapshot_id, :position, :driver_number, :driver_name, :team, :gap_to_leader, :last_lap_time, :best_lap_time, :status, :lap_count)
                                    """), dict(
                                        snapshot_id=snapshot_id,
                                        position=driver["position"],
                                        driver_number=driver["driver_number"],
                                        driver_name=driver["driver_name"],
                                        team=driver["team"],
                                        gap_to_leader=driver.get("gap_to_leader"),
                                        last_lap_time=driver.get("last_lap_time"),
                                        best_lap_time=driver.get("best_lap_time"),
                                        status=driver.get("status", "on_track"),
                                        lap_count=driver.get("lap_count")
                                    ))

                            session_type_label = timing_data["session"]["session_type"]
                            n_drivers = len(timing_data["drivers"])
                            print(f"fastf1: {year} R{round_num:2d} {session_type_label:10s} snapshot stored ({n_drivers} drivers)", flush=True)
                            return

                print("fastf1: no active session detected (no driver data)", flush=True)
            except Exception as e:
                import traceback
                print(f"fastf1: FAILED: {e}", flush=True)
                traceback.print_exc()
                sys.exit(1)

        asyncio.run(record_snapshot())
        return
    if args.cmd in ("pm-trades", "pm-record"):
        from sqlalchemy import text

        from racinglines.markets.polymarket.sync import fetch_trades, snapshot_books, sync

        def slugs(pats):
            with engine.connect() as c:
                return [s for pat in pats or [] for s in c.execute(
                    text("SELECT DISTINCT event_slug FROM market_links WHERE event_slug LIKE :p"), dict(p=pat)).scalars()]
        if args.cmd == "pm-trades":
            ev = slugs(args.events)
            with engine.connect() as c, get_session(args.db) as s:
                print(f"{len(ev)} events, {fetch_trades(s, c, ev)} trades fetched")
            return
        import time
        from datetime import datetime, timezone
        from datetime import timedelta

        from racinglines.markets import store as MS
        t0, last_sync, last_archive = time.time(), 0.0, time.time()
        while True:
            try:
                if args.sync_every and time.time() - last_sync >= args.sync_every * 60:
                    with engine.connect() as c, get_session(args.db) as s:
                        if args.no_alerts:
                            st, groups, used = sync(s, c, args.year), [], []
                        else:
                            from racinglines.markets import alerts
                            st, groups, used = alerts.sync_and_alert(s, c, args.year)
                        print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} sync {st}", flush=True)
                        for g in groups:
                            print(f"    new: {g['event_title']} ({g['n']} outcomes"
                                  f"{', upcoming race' if g['upcoming'] else ''}) -> {', '.join(used)}", flush=True)
                    last_sync = time.time()
                ev = slugs(args.events) or None
                with engine.connect() as c, get_session(args.db) as s:
                    n = snapshot_books(s, c, ev)
                print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} {n} books", flush=True)
                if os.environ.get("RACINGLINES_DISAGREE", "0") == "1":     # the cross-venue log's tick (markets/disagree.py)
                    from racinglines.markets import disagree as D
                    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} {D.record(engine)} disagreement rows", flush=True)
            except Exception as e:  # keep recording through transient API errors
                print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} error: {e}", flush=True)
            if time.time() - last_archive >= 3600:
                try:
                    moved = {n: MS.archive(engine, n, policy=True) for n in MS.STORES}
                    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} archived {moved}", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"archive error: {e}", flush=True)
                last_archive = time.time()
            if args.minutes and time.time() - t0 >= args.minutes * 60:
                return
            time.sleep(args.interval)
    if args.cmd == "season-strategy":
        from racinglines.markets.strategies.season import SeasonParams

        from racinglines.pipelines import season_strategy as SE
        prm = SeasonParams(min_edge=args.min_edge, stake_per_edge=args.stake_per_edge, max_stake=args.max_stake,
                           capital=args.capital)
        if args.paper:
            if args.venue == "og":
                sys.exit("--paper: the championship sleeve runs on polymarket or kalshi, not og")
            return _season_sleeve(args, engine, prm, SE, get_session, records)
        out = SE.run_season(engine, args.db, args.year, prm, fetch=not args.no_fetch, reforecast=args.reforecast,
                            n_sims=args.sims, echo=lambda m: print(m, flush=True), variant=args.variant,
                            exchange=args.venue)
        r, h = out["result"], out["hold"]
        on = "" if args.venue == "polymarket" else f" on {args.venue}"
        print(f"\n=== Default season strategy{on}, {args.year} ({out['markets']} markets) ===")
        for k, v in r["summary"].items():
            print(f"  {k:15s} {v:,.2f}" if isinstance(v, float) else f"  {k:15s} {v}")
        print(f"  enter pre-season & hold: {h['summary']['pnl']:+,.2f}")
        print("\n=== Positions ===")
        print(r["positions"].drop(columns=["key"]).to_string(index=False, float_format="{:.3f}".format) if len(r["positions"]) else "none")
        print("\n=== Trades by decision ===")
        if len(r["trades"]):
            t = r["trades"]
            print(t.assign(usd=t["shares"] * t["price"]).groupby("decision", sort=False).agg(trades=("usd", "size"), net_usd=("usd", "sum")).to_string())
        print("\n=== Now (live forecast vs latest price) ===")
        print(out["now"].drop(columns=["key"]).to_string(index=False, float_format="{:.3f}".format) if len(out["now"]) else "none")
        if args.save:
            from racinglines.db.queries import save_model_run
            eq = r["equity"].merge(h["equity"].rename(columns={"equity": "hold"}), on="t", how="left")
            with get_session(args.db) as s:
                run_id = save_model_run(
                    s, competition="f1_wdc", season=args.year, category="DRV", model="season_strategy",
                    # another venue's replay is its own kind: the pages, the matrix and the search read the latest
                    # 'season_strategy' run as Polymarket's
                    kind="season_strategy" if args.venue == "polymarket" else "season_venue_replay",
                    params=dict({k: (str(v) if hasattr(v, "total_seconds") else v) for k, v in prm.__dict__.items()}, year=args.year,
                                variant=args.variant,
                                min_volume=SE.MIN_VOLUME_BY.get(args.venue, SE.MIN_VOLUME), slippage=SE.SLIPPAGE,
                                default_half_spread=SE.DEFAULT_HALF_SPREAD, live_run=out["live_run"],
                                **({} if args.venue == "polymarket" else dict(venue=args.venue))),
                    metrics=dict(summary=r["summary"], hold=h["summary"], equity=records(eq.assign(t=eq["t"].astype(str))),
                                 positions=records(r["positions"]),
                                 trades=records(r["trades"].assign(t=r["trades"]["t"].astype(str))) if len(r["trades"]) else [],
                                 now=records(out["now"]),
                                 decisions=[dict(d, t=str(d["t"])) for d in out["decisions"]]))
            print(f"Saved season strategy run {run_id}.")
        return
    if args.cmd == "search":
        import json as _json
        from datetime import datetime, timezone

        from racinglines import paths
        from racinglines.pipelines import search as SR
        if args.leaderboard:
            cfg, _, _ = SR.load(args.queue)
            out = paths.runs("search", cfg["name"])
            SR.write_outputs(out, _json.loads((out / "state.json").read_text()), args.queue,
                             echo=lambda m: print(m, flush=True))
            return
        SR.run(args.queue, echo=lambda m: print(f"{datetime.now(timezone.utc):%H:%M:%S} {m}", flush=True))
        return
    if args.cmd == "search-report":
        from racinglines.pipelines import search_report as SRR
        SRR.run(args.queue)
        return
    if args.cmd == "search-import":
        from racinglines.pipelines import search as SR
        SR.import_results(args.results, args.db)
        return
    if args.cmd == "search-analyze":
        from racinglines import paths
        from racinglines.reporting import search_analyze as RA
        RA.main([args.search] + (["--write-candidates"] if args.write_candidates else []))
        out = paths.runs("search", args.search)
        if args.plot:
            from racinglines.reporting import search_plot as RP
            RP.main(out)
        if args.noise:
            from racinglines.reporting import search_noise as RN
            RN.main(out)
        if args.html:
            from racinglines.reporting import markdown_html as RH
            print(RH.render(args.html, out / "report.html", title=f"{args.search} backtest report"))
        return
    if args.cmd == "season-checkpoints":
        from racinglines import paths
        from racinglines.pipelines import season_checkpoints as SC
        from racinglines.models.position_sim import variants as V
        variants = [v.strip() for v in args.variants.split(",")] if args.variants else list(SC.VARIANTS)
        entries = tuple(int(x) for x in args.entries.split(","))
        for v in variants:
            V.switches(v)                                  # fail fast on an unknown name
        df, info = SC.run(engine, args.db, variants, args.year, entries=entries, window=args.window, n_sims=args.sims,
                          echo=lambda m: print(m, flush=True))
        md = SC.format_summary(df, args.window) + "\n\n" + SC.format_table(df)
        print(f"\n=== Championship checkpoints, {args.year} ({info['markets']} markets) ===\n")
        print(md)
        cols = ["variant", "entry", "window", "pnl", "bought", "positions", "markets", "edged", "drift", "hit", "slope", "slope_se"]
        print("\n" + df[cols].to_string(index=False, float_format="{:.3f}".format))
        dest = Path(args.out) if args.out else paths.runs("f1") / "season_checkpoints.md"
        dest.write_text(md + "\n")
        print(f"-> {dest}")
        if args.save:
            from racinglines.db.queries import save_model_run
            with get_session(args.db) as s:
                run_id = save_model_run(
                    s, competition="f1_wdc", season=args.year, category="DRV", model="season_checkpoints",
                    kind="season_checkpoints",
                    params=dict(year=args.year, entries=list(entries), window=args.window, variants=variants),
                    metrics=dict(rows=records(df.assign(end=df["end"].astype(str)))))
            print(f"Saved season checkpoints run {run_id}.")
        return
    if args.cmd == "sweep":
        from racinglines.pipelines import sweep_settings as SS
        from racinglines.pipelines import weekend_sweep as SW
        if args.half_life and args.half_life_days is None:              # the older global flag
            args.half_life_days = args.half_life
        settings = SS.from_args(args)
        rounds = _years(args.rounds) if args.rounds else None
        if args.fetch_only:
            with engine.connect() as c, get_session(args.db) as s:
                SW.fetch_market_data(s, c, SW.schedule(args.year, rounds), echo=lambda m: print(m, flush=True))
            return
        if args.grid:
            import json
            entries = json.loads(open(args.grid).read())
            with SW.shared():
                for i, e in enumerate(entries):
                    st = SS.Settings.from_dict(e["settings"])
                    print(f"grid {i + 1}/{len(entries)}: job {e['job']} {st.label()}", flush=True)
                    out = SW.run_sweep(engine, args.db, args.year, rounds, fetch=not args.no_fetch and i == 0,
                                       reprice=args.reprice and i == 0, settings=st,
                                       echo=lambda m: print(m, flush=True))
                    for k, v in out["totals"].items():
                        print(f"{k:7s} P&L {v['pnl']:+9.2f} on ${v['bought']:,.0f} · "
                              f"{v['weekends_up']}/{v['weekends']} weekends up")
                    if args.save:
                        print(f"Saved sweep run {_save_sweep(args, out)} for job {e['job']}.", flush=True)
            return
        out = SW.run_sweep(engine, args.db, args.year, rounds, fetch=not args.no_fetch, reprice=args.reprice,
                           settings=settings, echo=lambda m: print(m, flush=True))
        w = out["weekends"]
        cols = [c for c in ["event_key", "event", "format", "stages", "tradeable_pre", "tradeable_quali",
                            "update_trades", "update_bought", "update_pnl", "hold_pnl", "last_pnl", "maker_fills",
                            "maker_pnl"] if c in w]
        print("\n=== Weekends ===")
        print(w[cols].to_string(index=False, float_format="{:.2f}".format))
        print("\n=== Totals ===")
        for k, v in out["totals"].items():
            print(f"{k:7s} P&L {v['pnl']:+9.2f} on ${v['bought']:,.0f} · {v['weekends_up']}/{v['weekends']} weekends up")
        print("\n=== Update strategy: P&L of the trades made at each stage ===")
        print(out["by_stage"].to_string(index=False, float_format="{:+.2f}".format))
        print("\n=== By market ===")
        print(out["by_kind"].to_string(index=False, float_format="{:+.2f}".format))
        print("\n=== Model vs Polymarket by stage (Brier, lower is better) ===")
        print(out["scores"].to_string(index=False, float_format="{:.4f}".format))
        from racinglines import paths
        outdir = paths.runs("f1", "sweeps")
        if args.reliability:
            cal = out["calibration"]
            print("\n=== Calibration: model vs Polymarket, every tradeable stage (lower is better) ===")
            print(cal.pivot_table(index=["kind", "stage"], columns="source", values=["n", "brier", "logloss", "ece"],
                                  sort=False).to_string(float_format="{:.4f}".format))
            print("\n=== Reliability bins, all stages pooled (|z| > 2: off by more than binomial noise) ===")
            print(out["reliability"].to_string(index=False, float_format="{:.3f}".format))
            cal.to_csv(outdir / f"sweep_{args.year}_calibration.csv", index=False)
            out["reliability"].to_csv(outdir / f"sweep_{args.year}_reliability.csv", index=False)
        w.to_csv(outdir / f"sweep_{args.year}_weekends.csv", index=False)
        if len(out["trades"]):
            out["trades"].to_csv(outdir / f"sweep_{args.year}_trades.csv", index=False)
        if args.save:
            print(f"Saved sweep run {_save_sweep(args, out)}.")
        return
    if args.cmd == "scorecard":
        from racinglines.pipelines import scorecard as SCD
        from racinglines.pipelines import weekend_sweep as SW
        if not args.all and not args.event:
            sys.exit("give --event YEAR-ROUND or --all --year YEAR")
        mk = args.model_key or SCD.default_model_key(args.variant)
        outdir = Path(args.out) if args.out else None
        if outdir:
            outdir.mkdir(parents=True, exist_ok=True)
        venues = list(SCD.VENUES) if args.venue == "both" else [args.venue]
        if args.all:
            for venue in venues:
                print(f"\n=== {args.year} on {venue} (model_key {mk}) ===")
                with engine.connect() as c:
                    out = SCD.season(c, args.year, venue, mk, rounds=_years(args.rounds) if args.rounds else None,
                                    echo=lambda m: print(m, flush=True))
                if len(out["weekends"]):
                    print("\n--- Per weekend ---")
                    print(SCD.format_text(out["weekends"], first=("event_key", "event")))
                    print("\n--- Per kind, all stages and weekends pooled ---")
                    print(SCD.format_text(out["by_kind"], first=("kind",)))
                    print("\n--- Per stage and kind, all weekends pooled ---")
                    print(SCD.format_text(out["by_stage"]))
                files = SCD.write_season(out, mk, outdir)
                print("-> " + ", ".join(str(v) for v in files.values()))
            return
        year, rnd = (int(x) for x in args.event.split("-"))
        w = SW.schedule(year, [rnd]).get(rnd)
        if w is None:
            sys.exit(f"{args.event}: not in the {year} schedule")
        for venue in venues:
            with engine.connect() as c:
                res = SCD.weekend(c, w, venue, mk)
            print(f"\n=== {args.event} {w['name']} on {venue} (model_key {mk}) ===")
            if res["note"]:
                print(f"note: {res['note']}")
            if len(res["scores"]):
                print(SCD.format_text(res["scores"]))
                print("\n--- All stages pooled ---")
                print(SCD.format_text(SCD.score(res["rows"], by=("kind",)), first=("kind",)))
            files = SCD.write(res, mk, outdir)
            print("-> " + ", ".join(str(v) for v in files.values()))
        return
    if args.cmd == "replay":
        from racinglines.markets.strategies import maker_replay as R
        run_ids = [int(x) for x in args.runs.split(",")]
        with engine.connect() as c:
            data = R.load_event(c, run_ids)
        for mode in ("touch", "through"):
            res = R.replay(data, R.Params(fill=mode))
            print(f"\n=== fill rule: {mode} ===")
            print(R.summary(res).to_string())
        if args.sweep:
            print("\n=== sweep ===")
            print(R.sweep(data).to_string(index=False))
        return
    if args.cmd == "pm-history":
        from datetime import timezone

        from sqlalchemy import text

        from racinglines.markets.polymarket.sync import fetch_history
        start = pd.Timestamp(args.start).tz_localize(timezone.utc).to_pydatetime()
        end = pd.Timestamp(args.end).tz_localize(timezone.utc).to_pydatetime()
        with engine.connect() as c:
            slugs = [s for pat in args.events for s in c.execute(
                text("SELECT DISTINCT event_slug FROM market_links WHERE event_slug LIKE :p"), dict(p=pat)).scalars()]
        with engine.connect() as c, get_session(args.db) as s:
            print(f"{len(slugs)} events, {fetch_history(s, c, slugs, start, end, args.fidelity)} price points stored")
        return

    from racinglines.models.position_sim import pricing as run
    meas = run.Measurements.load(engine)

    if args.half_life:
        run.M.HALF_LIFE_DAYS = args.half_life
    knobs = dict(half_life_days=run.M.HALF_LIFE_DAYS)

    if args.cmd == "compare":
        from racinglines.models.position_sim import evaluate as EV
        with engine.connect() as c:
            (pa, a), (pb, b) = EV.load_run(c, args.baseline), EV.load_run(c, args.challenger)
        print(f"Run {args.baseline} ({pa.get('variant', 'baseline')}) vs run {args.challenger} "
              f"({pb.get('variant', 'baseline')}): challenger − baseline, ± 2 SE over races\n")
        print(EV.format_paired(EV.paired(a, b)))
        if args.reliability:
            for name, rows in ((args.baseline, a), (args.challenger, b)):
                rel = pd.concat([EV.reliability(rows, k) for k in ("win", "podium", "top10")], ignore_index=True)
                if not len(rel):
                    print(f"\nrun {name}: saved without probabilities (re-run the backtest)")
                    continue
                print(f"\n=== Reliability, run {name} ===")
                print(EV.calibration_error(rel).pivot(index="market", columns="mode", values="ece").round(4).to_string())
                print(rel.round(4).to_string(index=False))
        return
    if args.cmd == "matrix":
        from racinglines import paths
        from racinglines.models.position_sim import evaluate as EV
        with engine.connect() as c:
            m = EV.matrix(c, [v.strip() for v in args.variants.split(",")], args.year)
        md = EV.format_matrix(m)
        print(md)
        print("\nRuns: " + "; ".join(f"{v}: " + ", ".join(f"{k} {i}" for k, i in r.items() if i) for v, r in m["runs"].items()))
        dest = Path(args.out) if args.out else paths.runs("f1") / "matrix.md"
        dest.write_text(md + "\n")
        print(f"-> {dest}")
        return
    if args.cmd == "backtest":
        if args.no_track:
            args.track = "off"
        results = []
        for use_track in {"both": [True, False], "on": [True], "off": [False]}[args.track]:
            print(f"progress 0/1 building history (track features {'on' if use_track else 'off'})", flush=True)
            hist = run.history(meas, use_track)
            bt = run.backtest(meas, hist, args.start_year, args.sims, use_track, last_n=args.races,
                              echo=lambda m: print(m, flush=True), keep_probs=True)
            bt["track_features"] = use_track
            results.append(bt)
            print(f"\n=== Track features {'ON' if use_track else 'OFF'}: mean over {bt['event_id'].nunique()} races ===")
            print(run.summarize_backtest(bt).round(4).T.to_string())
        out = pd.concat(results, ignore_index=True)
        from racinglines import paths
        dest = args.out or paths.runs("f1", "backtests") / f"backtest_{pd.Timestamp.now():%Y%m%d_%H%M}.csv"
        out.drop(columns=["pred"], errors="ignore").to_csv(dest, index=False)
        print(f"\nPer-race rows -> {dest}")
        if args.save:
            from racinglines.db.queries import save_model_run
            with get_session(args.db) as s:
                run_id = save_model_run(s, competition="f1_wdc", category="DRV", model="f1_sector_sim", kind="backtest",
                                        params=dict(start_year=args.start_year, sims=args.sims, races=args.races,
                                                    track=args.track, variant=args.variant, **knobs),
                                        metrics=dict(summary={f"{m}|track={t}": run.summarize_backtest(g).iloc[0].to_dict()
                                                              for (m, t), g in out.groupby(["mode", "track_features"])},
                                                     events=records(out)))
            print(f"Saved backtest run {run_id}.")
        return

    use_track = not getattr(args, "no_track", False)
    hist = run.history(meas, use_track)

    if args.cmd == "diagnostic":
        cutoff = pd.Timestamp(args.cutoff)
        event_id, summ, ex, result = run.diagnostic(meas, hist, args.event, cutoff, n_sims=args.sims, use_track=use_track)
        print("Leakage audit:", ex["audit"])
        out = summ.merge(result, on="athlete_id")
        print(out[["driver", "team_key", "win_prob", "podium_prob", "top10_prob", "position", "status"]]
              .head(args.sims and 12).to_string(index=False, formatters=fmt))
        if args.save:
            run_id = run.save_diagnostic(args.db, args.event, cutoff, summ, ex, args.sims, track_features=use_track)
            print(f"Saved diagnostic run {run_id}.")
        return

    if args.cmd == "forecast":
        per_event, standings, extras = run.forecast(meas, hist, args.year, n_sims=args.sims, use_track=use_track)
        fm = extras["model"]
        print(f"Cutoff {extras['cutoff']} UTC · latest data used {extras['latest_data']}")
        print(f"Finishing model coef {dict(zip(run.M.FEATURES, fm.coef.round(3)))} sigma {fm.sigma:.3f}; "
              f"season drift (as-of) {extras['drift']}")
        for ev in per_event[:2]:
            print(f"\n--- R{ev['round']} {ev['name']} ({ev['date']:%d %b}) ---")
            cols = ["driver", "team_key", "win_prob", "podium_prob", "top10_prob", "dnf_prob", "exp_points"]
            print(ev["summary"][cols].head(args.top).to_string(index=False, formatters=fmt, float_format="{:.1f}".format))
        print(f"\n--- {args.year} drivers' championship ---")
        print(standings[["driver", "current_points", "exp_points", "champion_prob", "top3_prob"]]
              .head(args.top).to_string(index=False, formatters=fmt, float_format="{:.0f}".format))
        print(extras["constructors"][["team", "current_points", "exp_points", "champion_prob"]]
              .head(5).to_string(index=False, formatters=fmt, float_format="{:.0f}".format))
        if args.save:
            params = dict(cutoff=extras["cutoff"], half_life_days=run.M.HALF_LIFE_DAYS, sims=args.sims,
                          track_features=use_track, label=args.scenario,
                          features=run.M.FEATURES, coef=[float(c) for c in fm.coef], sigma=fm.sigma,
                          sigma_q=fm.sigma_q, drift=extras["drift"])
            run_id = run.save_forecast(args.db, args.year, per_event, standings, params, metrics=dict(
                latest_data=extras["latest_data"], constructors=records(extras["constructors"]),
                race_constructor_top=extras["race_constructor_top"]), kind="scenario" if args.scenario else "forecast")
            print(f"\nSaved {'scenario' if args.scenario else 'forecast'} run {run_id}.")


if __name__ == "__main__":
    main()
