"""
racinglines motogp <command>: MotoGP race results (from the free public results API at
api.motogp.pulselive.com).

    fetch        Download season events, categories, sessions and race classifications to
                 data/raw/motogp/pulselive/<year>/ (paced, safe to re-run; --dry-run counts the requests first).
    ingest       Load the stored classifications into the database (events, results, rider identity).
    compare      Backtest the baseline and recent-form challenger, and print model-promotion buy signals.
    replay       Taker replay of Grands Prix against Kalshi's or Polymarket's recorded prices (read-only unless
                 --save; racinglines/pipelines/position_replay.py).
    sweep        The season sweep of Grands Prix: the F1 sweep's taker modes and maker variants through each race's
                 stages on one exchange (--venue polymarket | kalshi), for the search's tuned and
                 held-out seasons (read-only unless --save; racinglines/pipelines/season_sweep.py).
    season-replay  The riders' champion markets replayed through the season (Kalshi's KXMOTOGP, Polymarket's
                 championship winner): an as-of season forecast after every Grand Prix (models/motogp_season.py),
                 the championship sleeve's strategy at the recorded prices. Read-only; off by default
                 (RACINGLINES_SEASON_REPLAY=1).
    (exchange data: racinglines markets sync | history | trades | record | archive --sport motogp)

Nothing here runs by default. Terms of use: sports/motogp.toml [results].terms — the owner has reviewed
them for the intended non-commercial fantasy use (2026-09-29); revisit before any wider use.
"""

import argparse

import numpy as np
import pandas as pd


def _years(spec):
    if "," in spec:
        return [int(y) for y in spec.split(",")]
    a, _, b = spec.partition("-")
    return list(range(int(a), int(b or a) + 1))


def _promotion_candidates(model, data, settings, seasons=None, promo_threshold=0.05):
    from racinglines.markets import kinds as K
    rng = np.random.default_rng(settings.rng_seed)
    hist = model.history(data, settings)
    prev = {}
    rows = []
    for ev in model.events(data, settings, seasons):
        sims = model.price(hist, ev, settings, rng)
        if sims is None:
            continue
        fair = K.summary(sims)["race_win"]
        for athlete_id, score in zip(sims.entrants, fair):
            prior = prev.get(athlete_id, 0.0)
            delta = score - prior if prior else 0.0
            if prior and score >= 0.05 and delta >= promo_threshold:
                rows.append(dict(season=ev.season, event=ev.name, athlete_id=athlete_id,
                                 fair=float(score), prior=float(prior), delta=float(delta),
                                 possible_buy=True))
            prev[athlete_id] = float(score)
    return pd.DataFrame(rows)


def _csv_values(value):
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="racinglines motogp", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="Database URL (default: $DATABASE_URL / docker-compose).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch", help="Download season events, sessions and race classifications.")
    p.add_argument("--years", default="2016-2026", help="e.g. 2026, 2016-2026 (default) or 2024,2026. "
                                                        "2016 is when Michelin became the sole tyre supplier; "
                                                        "earlier (Bridgestone-era) seasons are a follow-up.")
    p.add_argument("--force", action="store_true", help="Ask again for files already stored.")
    p.add_argument("--dry-run", action="store_true", help="Count the requests a run would make; ask for nothing.")
    p = sub.add_parser("ingest", help="Load the stored classifications into the database.")
    p.add_argument("--years", default="2016-2026")
    p.add_argument("--force", action="store_true", help="Rebuild events whose files have not changed.")
    p = sub.add_parser("compare", help="Backtest the baseline versus the recent-form challenger and print its buy signals.")
    p.add_argument("--years", default="2026")
    p.add_argument("--promo-threshold", type=float, default=0.05, help="Promotion trigger for a possible buy signal.")
    p = sub.add_parser("search", help="Sweep a small set of MotoGP recent-form settings and rank by mean log loss.")
    p.add_argument("--years", default="2026")
    p.add_argument("--sims", default="200,400", help="Comma-separated sims, e.g. 200,400")
    p.add_argument("--recent-races", default="4,6,8", help="Comma-separated recent-race windows, e.g. 4,6,8")
    p.add_argument("--history-races", default="0,12", help="Comma-separated history windows, e.g. 0,12")
    p.add_argument("--recency-decay", default="1.5,2.5,4.0", help="Comma-separated recency decays, e.g. 1.5,2.5")
    p.add_argument("--team-bias", default="0.2,0.35,0.5", help="Comma-separated team-bias priors, e.g. 0.2,0.35")
    p.add_argument("--noise", default="0.75,1.25", help="Comma-separated race-day noise levels, e.g. 0.75,1.25")
    p.add_argument("--limit", type=int, default=10, help="How many candidate settings to print.")
    from racinglines.cli import replay_cmd
    replay_cmd.add_parser(sub, "motogp")
    replay_cmd.add_season_parser(sub, "motogp")
    replay_cmd.add_demo_parser(sub, "motogp")
    replay_cmd.add_forecast_parser(sub, "motogp")
    replay_cmd.add_sweep_parser(sub, "motogp")
    replay_cmd.add_signals_parser(sub, "motogp")
    args = ap.parse_args(argv)

    if args.cmd == "signals":
        return replay_cmd.run_signals(args, "motogp")

    if args.cmd == "demo-history":
        return replay_cmd.run_demo(args, "motogp")
    if args.cmd == "forecast":
        return replay_cmd.run_forecast(args, "motogp")
    if args.cmd == "sweep":
        return replay_cmd.run_sweep(args, "motogp")
    if args.cmd == "replay":
        return replay_cmd.run(args, "motogp", _years(args.years))
    if args.cmd == "season-replay":
        return replay_cmd.run_season(args, "motogp")

    if args.cmd == "fetch":
        from racinglines.sources.motogp import fetch
        counts = fetch.fetch(_years(args.years), force=args.force, dry_run=args.dry_run)
        print("Would ask for" if args.dry_run else "Done:", counts)
        return 1 if counts["errors"] else 0
    if args.cmd == "compare":
        from racinglines.core import walk_forward as WF
        from racinglines.models import race_model as RM
        from racinglines.models.motogp_model import MotoGPRace, MotoGPRaceChallenger
        seasons = _years(args.years)
        data = MotoGPRace().load(args.db)
        rows = []
        for label, model in (("baseline", MotoGPRace()), ("challenger", MotoGPRaceChallenger())):
            settings = model.Settings.from_dict({"sims": 400, "shrink": 3.0, "noise": 1.25,
                                                "recent_races": 6, "recency_decay": 2.5,
                                                "team_bias": 0.35, "seed": 7})
            out = WF.run(model, data, settings, seasons=seasons, kinds=["race_win", "race_podium", "race_h2h"])
            cal = out["calibration"].query("season == 'all'").set_index("kind")
            rows.append(dict(model=label, race_win=round(float(cal.loc["race_win", "logloss"]), 4),
                             race_podium=round(float(cal.loc["race_podium", "logloss"]), 4),
                             race_h2h=round(float(cal.loc["race_h2h", "logloss"]), 4)))
            buys = _promotion_candidates(model, data, settings, seasons=seasons, promo_threshold=args.promo_threshold)
            print(f"\n=== {label} ===")
            print(buys.head(8).to_string(index=False))
            print(f"possible buys: {len(buys)}")
        print("\n=== summary ===")
        print(pd.DataFrame(rows).to_string(index=False))
        return 0
    if args.cmd == "search":
        from itertools import product
        from racinglines.models.motogp_model import MotoGPRace, MotoGPRaceChallenger
        data = MotoGPRace().load(args.db)
        model = MotoGPRaceChallenger()
        params = [
            [float(v) if "." in v else int(v) for v in _csv_values(getattr(args, "sims"))],
            [int(v) for v in _csv_values(args.recent_races)],
            [int(v) for v in _csv_values(args.history_races)],
            [float(v) for v in _csv_values(args.recency_decay)],
            [float(v) for v in _csv_values(args.team_bias)],
            [float(v) for v in _csv_values(args.noise)],
        ]
        candidates = []
        for idx, (sims, recent_races, history_races, decay, team_bias, noise) in enumerate(product(*params), 1):
            candidates.append({
                "sims": sims,
                "recent_races": recent_races,
                "history_races": history_races,
                "recency_decay": decay,
                "team_bias": team_bias,
                "noise": noise,
                "seed": idx,
            })
        rows = model.search_grid(data, seasons=_years(args.years), settings_list=candidates, kinds=["race_win", "race_podium", "race_h2h"])
        print(rows.head(args.limit)[["candidate", "score", "race_win", "race_podium", "race_h2h"]].to_string(index=False))
        return 0
    from racinglines.db.config import get_session
    from racinglines.sources.motogp import ingest
    with get_session(args.db) as s:
        report = ingest.ingest(s, _years(args.years), force=args.force)
    done = sum(1 for v in report.values() if v.endswith("results"))
    print(f"Done: {done} events ingested of {len(report)} seen.")
    return 0
