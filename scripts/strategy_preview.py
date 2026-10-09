"""Read-only hypothetical F1 opening comparison, using cached quotes and tape."""

import argparse
import csv
import json
import math
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

VENUES = ("polymarket", "kalshi")
KINDS = ("race_win", "race_podium", "race_pole", "race_h2h", "race_constructor_top")


def integer_id(value):
    """JSON/DataFrame round trips can turn nullable integer IDs into floats."""
    if isinstance(value, bool):
        raise ValueError("Invalid integer ID")  # noqa: TRY004 - one validation error contract for IDs
    try:
        number = float(value)
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid integer ID: {value!r}") from exc
    if not math.isfinite(number) or number != result:
        raise ValueError(f"Invalid integer ID: {value!r}")
    return str(result)


def validate_links(links, venue):
    if links and venue != "polymarket":
        raise ValueError(f"Unsupported venue with linked markets: {venue}")
    required = {
        "token_id",
        "condition_id",
        "prediction",
        "athlete_id",
        "params",
        "closed",
        "last_bid",
        "last_ask",
        "synced_at",
        "question",
        "outcome",
        "invert",
    }
    seen = set()
    for link in links:
        missing = required - link.keys()
        if missing:
            raise ValueError(f"Missing link fields: {sorted(missing)}")
        if link["prediction"] not in KINDS:
            raise ValueError(f"Unsupported prediction: {link['prediction']}")
        key = link["token_id"]
        if not key or key in seen:
            raise ValueError(f"Missing or duplicate market key: {key}")
        seen.add(key)
        kind, params = link["prediction"], link["params"] or {}
        allowed = {"opponent_id"} if kind == "race_h2h" else {"team"} if kind == "race_constructor_top" else set()
        if set(params) - allowed:
            raise ValueError(f"Unsupported market parameters: {params}")
        if kind == "race_h2h":
            integer_id(params.get("opponent_id"))
        if kind == "race_constructor_top" and not params.get("team"):
            raise ValueError("Constructor market needs a team")


def validate_frozen(frozen, *, commit, source_run, event_key, cutoff, data_key):
    expected = {
        "commit": commit,
        "source_run": source_run,
        "event_key": event_key,
        "cutoff": cutoff,
        "data_key": data_key,
    }
    if frozen.get("schema_version") != 1:
        raise ValueError("Unsupported snapshot schema; create a new preview snapshot")
    for key, value in expected.items():
        if frozen.get(key) != value:
            raise ValueError(f"Frozen {key} changed; stop before comparing simulations")
    if set(frozen.get("snapshot", {})) != set(VENUES):
        raise ValueError("Frozen snapshot must explicitly contain both venues, including empty venues")
    if not frozen.get("asof"):
        raise ValueError("Frozen snapshot needs an asof timestamp")
    for venue, snapshot in frozen["snapshot"].items():
        if set(snapshot) != {"links", "volumes"}:
            raise ValueError("Unsupported frozen venue fields")
        links, volumes = snapshot["links"], snapshot["volumes"]
        validate_links(links, venue)
        if {str(link["condition_id"]) for link in links} != set(volumes):
            raise ValueError("Frozen liquidity must cover exactly the frozen markets")
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in volumes.values()):
            raise ValueError("Invalid frozen liquidity")


def sizing_params(settings, profile, sizing, *, bankroll=1000, max_market=50, max_total=250, fee=None):
    from racinglines.markets.strategies import taker_weekend as rb
    from racinglines.pipelines import sweep_settings as ss

    if profile["strategy"] not in ("update", "early"):
        raise ValueError("Unsupported preview strategy")
    if settings["venue"] not in (None, "polymarket"):
        raise ValueError("Unsupported profile venue")
    if settings["thin_edge_mult"] is not None:
        raise ValueError("Unsupported thin-market exception: preview has no frozen touch depth")
    ignored = [key for key in settings.changed() if settings.BY[key].group == "maker"]
    if ignored:
        raise ValueError(f"Unsupported maker settings in taker preview: {ignored}")
    kelly = {"original": None, "HK": 0.5, "QK": 0.25}[sizing]
    return rb.TakerParams(
        min_edge=settings["min_edge"],
        min_edge_h2h=settings["min_edge_h2h"],
        min_edge_by_kind=tuple(ss.parse_map(settings["min_edge_by_kind"]).items()),
        stake_per_edge=settings["stake_per_edge"],
        max_stake=settings["max_stake"] if kelly is None else max_market,
        cost=settings["cost"],
        mode=profile["strategy"],
        stages=None,
        late_stages=settings["late_stages"],
        kelly=settings["kelly"] if kelly is None else kelly,
        bankroll=settings["bankroll"] if kelly is None else bankroll,
        max_deployed=settings["max_deployed"] if kelly is None else max_total,
        taker_fee=fee or 0.0,
    )


def decision_rows(details, reasons, links, passing, watched, sizing):
    passed = {row["key"]: row for row in passing.to_dict("records")}
    watch = {row["key"]: row for row in watched.to_dict("records")}
    rows = []
    for key, detail in details.items():
        trade = passed.get(key)
        candidate = trade or watch.get(key)
        why = [reasons[key]] if reasons[key] else []
        fair, bid, ask = detail["fair_yes"], detail["bid"], detail["ask"]
        if (
            fair is not None
            and bid is not None
            and ask is not None
            and max(fair - ask, bid - fair) < detail["edge_threshold"]
        ):
            why.append("neither side clears the entry edge threshold")
        if trade is None and not why:
            why.append("no allocation after execution costs, $2 minimum trade or portfolio cap")
        side = candidate["side"] if candidate else ""
        if side and links[key]["prediction"] == "race_h2h":
            side = links[key]["outcome"] if side == "YES" else f"NOT {links[key]['outcome']}"
        rows.append(
            dict(
                detail,
                sizing=sizing,
                status="picked" if trade else "not picked",
                side=side,
                cost=trade["shares"] * trade["price"] if trade else 0.0,
                shares=trade["shares"] if trade else 0.0,
                standalone_watchlist_cost=candidate["shares"] * candidate["price"] if candidate and not trade else 0.0,
                standalone_watchlist_shares=candidate["shares"] if candidate and not trade else 0.0,
                reasons="; ".join(why),
            )
        )
    return rows


def render(data, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fields = [
        "venue",
        "profile",
        "sizing",
        "market_key",
        "question",
        "side",
        "fair",
        "touch",
        "cost",
        "shares",
        "status",
        "blocked_by",
    ]
    decision_fields = [
        "venue",
        "profile",
        "sizing",
        "market_key",
        "question",
        "status",
        "side",
        "fair_yes",
        "bid",
        "ask",
        "edge_threshold",
        "recorded_volume_24h",
        "cost",
        "shares",
        "standalone_watchlist_cost",
        "standalone_watchlist_shares",
        "reasons",
    ]

    def table(path, rows, columns):
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows({key: row.get(key) for key in columns} for row in rows)

    table(folder / "comparison.csv", data["rows"], fields)
    for code in data["profiles"]:
        directory = folder / code
        directory.mkdir(exist_ok=True)
        for picked, filename in (
            (True, "picked.csv"),
            (False, "considered-not-picked.csv"),
        ):
            table(
                directory / filename,
                [r for r in data["decisions"] if r["profile"] == code and (r["status"] == "picked") == picked],
                decision_fields,
            )
    for picked, filename in (
        (True, "picked-all.csv"),
        (False, "considered-not-picked-all.csv"),
    ):
        table(
            folder / filename,
            [r for r in data["decisions"] if (r["status"] == "picked") == picked],
            decision_fields,
        )
    grouped = {}
    for row in data["rows"]:
        key = row["venue"], row["market_key"], row["side"]
        group = grouped.setdefault(key, {"question": row["question"], "picks": {}, "reasons": set()})
        group["picks"][(row["profile"], row["sizing"])] = row
        if row["blocked_by"]:
            group["reasons"].add(row["blocked_by"])
    size = data["sizing"]
    lines = [
        f"# {data['event_key']}: hypothetical enter-now comparison",
        "",
        f"Quote snapshot: {data['asof']} UTC. Forecast cutoff: {data['cutoff']} UTC.",
        f"Simulations: {data['sims']}. Source diagnostic: #{data['source_run']}. Code: {data['commit']}.",
        "",
        "No fetch, stage save, signal save, profile change or order. All database sessions are read-only.",
        "Timing gates alone are bypassed, with empty starting positions. Model settings and market filters remain.",
        "Other model variants are priced in memory at the source forecast cutoff, with each profile's seed (default 42).",
        (
            f"Original sizing uses the defined profile; HK/QK use a fresh ${size['bankroll']:,.0f} balance, "
            f"${size['max_market']:g} per-market cap and ${size['max_total']:g} aggregate cap."
        ),
        "These are opening allocations, not rolling season bankrolls.",
        "TB blends T1/T8 50:50; its opening allocation is the weighted sum of their independent previews.",
        "Buys use cached asks (NO uses 1 - bid) plus the existing strategy's slippage and venue fees.",
        "This touch-based Polymarket preview differs from the historical sweep's midpoint execution.",
        "Recorded 24-hour tape determines liquidity; missing tape is zero recorded volume, not proof of no live trades.",
        "Touch depth and venue-specific live fees have not been verified. Not executable recommendations.",
        "Pass saved JSON as --snapshot to freeze quotes, liquidity, input data and forecast cutoff.",
        "Each profile folder partitions all modeled markets into picked and considered-not-picked (HK/QK).",
        "",
        "## Coverage",
        "",
    ]
    for venue, coverage in data["coverage"].items():
        lines.append(f"- {venue}: {coverage['markets']} distinct modeled markets.")
    lines.extend(
        [
            "",
            "## Candidate board",
            "",
            "| Venue / outcome | Original-sizing supporters | Passing supporters | Blockers |",
            "|---|---|---|---|",
        ]
    )
    for (venue, _, side), group in grouped.items():
        supporters = [p for p, s in group["picks"] if s == "original"]
        passing = [
            p for (p, s), row in group["picks"].items() if s == "original" and row["status"] == "passes preview filters"
        ]
        question = group["question"].replace("|", "/")
        lines.append(
            f"| {venue}: {side} — {question} | {', '.join(supporters)} | "
            f"{', '.join(passing) or 'None'} | {'; '.join(sorted(group['reasons'])) or 'None'} |"
        )
    lines.extend(
        [
            "",
            "## Per-profile opening sizes",
            "",
            "| Venue / outcome | Profile | Model probability | Touch | Original | HK | QK |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for (venue, _, side), group in grouped.items():
        for profile in sorted({p for p, _ in group["picks"]}):
            values = [group["picks"].get((profile, s)) for s in ("original", "HK", "QK")]
            sample = next(row for row in values if row is not None)
            money = [f"${row['cost']:.2f}" if row else "—" for row in values]
            question = group["question"].replace("|", "/")
            lines.append(
                f"| {venue}: {side} — {question} | {profile} | "
                f"{sample['fair']:.2%} | {sample['touch']:.2%} | {' | '.join(money)} |"
            )
    lines.extend(
        [
            "",
            "Amounts on blocked rows are standalone hypothetical targets, without the aggregate cap.",
            "They are not approved allocations.",
            "Models absent from a candidate row did not produce an entry at their own threshold.",
            "",
            "## Profile checks",
            "",
            "| Venue | Profile | Sizing | Passing entries | Watchlist entries |",
            "|---|---|---|---:|---:|",
        ]
    )
    for check in data["checks"]:
        lines.append(
            f"| {check['venue']} | {check['profile']} | {check['sizing']} | {check['passing']} | {check['watchlist']} |"
        )
    (folder / "report.md").write_text("\n".join(lines) + "\n")


def compute(args):
    from datetime import timedelta

    import numpy as np
    import pandas as pd
    from sqlalchemy import create_engine, text

    from racinglines import progress
    from racinglines.db import config, reads
    from racinglines.markets import venue_replay
    from racinglines.markets.strategies import taker_weekend as rb
    from racinglines.models.position_sim import model as position_model
    from racinglines.models.position_sim import pricing
    from racinglines.pipelines import profiles, signals
    from racinglines.pipelines import sweep_settings as ss
    from racinglines.pipelines import weekend_sweep as ws

    engine = create_engine(
        config.database_url(),
        isolation_level="REPEATABLE READ",
        connect_args={"options": "-c default_transaction_read_only=on"},
    )
    frozen = json.loads(Path(args.snapshot).read_text()) if args.snapshot else None
    now = pd.Timestamp(frozen["asof"]) if frozen else pd.Timestamp.now(tz="UTC").tz_localize(None)
    forecasts = {}
    out = {
        "schema_version": 1,
        "asof": str(now),
        "sims": args.sims,
        "source_run": args.source_run,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=Path(__file__).resolve().parents[1],
        ).strip(),
        "rows": [],
        "checks": [],
        "coverage": {},
        "snapshot": {},
        "models": {},
        "decisions": [],
        "sizing": {
            "bankroll": args.bankroll,
            "max_market": args.max_market,
            "max_total": args.max_total,
        },
    }
    selected = {f"T{i}": profiles.PROFILES[f"T{i}"] for i in range(1, 11)}
    out["profiles"] = [*selected, "TB"]

    class CachedQuotes(venue_replay.Polymarket):
        def price(self, token, t):
            link = self.cached[token]
            stamp, bid, ask = (
                link.get("synced_at"),
                link.get("last_bid"),
                link.get("last_ask"),
            )
            if stamp is None or pd.isna(stamp):
                return None
            stamp = pd.Timestamp(stamp)
            if stamp.tzinfo is not None:
                stamp = stamp.tz_convert("UTC").tz_localize(None)
            if not timedelta(0) <= t - stamp <= timedelta(minutes=10):
                return None
            if bid is None or ask is None or pd.isna(bid) or pd.isna(ask) or not 0 < bid <= ask < 1:
                return None
            return float((bid + ask) / 2)

    try:
        with engine.connect() as conn:
            if conn.execute(text("SHOW transaction_read_only")).scalar() != "on":
                raise RuntimeError("Refusing a writable database session")
            source = reads.model_run(conn, args.source_run)
            if source is None:
                raise ValueError("Source diagnostic is missing")
            cutoff = pd.Timestamp(source["params"]["cutoff"])
            event_key = source["params"]["event_key"]
            if event_key != args.event:
                raise ValueError("Source diagnostic does not match --event")
            out.update(cutoff=str(cutoff), event_key=event_key)
            event = (
                conn.execute(
                    text("""
                SELECT e.id, ra.id AS race_id, v.slug AS venue
                FROM events e JOIN races ra ON ra.event_id=e.id
                LEFT JOIN venues v ON v.id=e.venue_id WHERE e.source_key=:key
            """),
                    {"key": event_key},
                )
                .mappings()
                .one()
            )
            # Load measurements through this same repeatable-read, read-only transaction.
            meas = pricing.Measurements.from_frames(
                pd.read_sql(text(position_model.RESULTS_SQL), conn),
                pd.read_sql(text(position_model.LAPS_SQL), conn),
                pd.read_sql(text(position_model.PROFILE_SQL), conn),
            )
            out["data_key"] = ss.data_key(meas.view(cutoff))
            source_settings = ss.Settings.from_dict(source["params"]["model_settings"])
            if out["data_key"] != source["params"]["data_key"]:
                raise ValueError("Source forecast input data changed")
            if frozen:
                validate_frozen(
                    frozen,
                    commit=out["commit"],
                    source_run=args.source_run,
                    event_key=event_key,
                    cutoff=str(cutoff),
                    data_key=out["data_key"],
                )
                if frozen.get("sizing") != out["sizing"]:
                    raise ValueError("Frozen sizing changed; compare simulations with identical sizing")
            snapshots = {}
            for code in VENUES:
                if frozen:
                    records = frozen["snapshot"][code]["links"]
                else:
                    # Do not let the sweep helper's default kind filter hide unsupported links.
                    links = pd.read_sql(
                        text("""
                        SELECT * FROM market_links
                        WHERE race_id=:race AND exchange=:venue AND NOT closed ORDER BY id
                    """),
                        conn,
                        params={"race": event["race_id"], "venue": code},
                    )
                    if code == "polymarket" and not links.empty:
                        links = links.drop_duplicates("condition_id", keep="first")
                    records = links.to_dict("records")
                validate_links(records, code)
                records = [dict(link, params=dict(link["params"] or {})) for link in records]
                for link in records:
                    if link["prediction"] == "race_h2h":
                        link["params"]["opponent_id"] = int(integer_id(link["params"]["opponent_id"]))
                links = pd.DataFrame([link for link in records if not link["closed"]])
                out["coverage"][code] = {"markets": len(links)}
                if links.empty:
                    out["snapshot"][code] = {"links": [], "volumes": {}}
                    continue
                if frozen:
                    # Coherence uses cached quotes; frozen volumes need no fresh tape/archive reads.
                    view = CachedQuotes.__new__(CachedQuotes)
                    view.links = links
                    view.group_target = ws.GROUP_TARGET
                    view.coherence_tol = ws.COHERENCE_TOL
                else:
                    view = CachedQuotes(
                        conn,
                        links,
                        now - timedelta(hours=6),
                        now,
                        ws.GROUP_TARGET,
                        ws.COHERENCE_TOL,
                    )
                view.cached = {r["token_id"]: r for r in links.to_dict("records")}
                volumes = (
                    frozen["snapshot"][code]["volumes"]
                    if frozen
                    else {str(c): view.volume_24h(c, now) for c in links["condition_id"].unique()}
                )
                out["snapshot"][code] = {
                    "links": json.loads(links.to_json(orient="records", date_format="iso")),
                    "volumes": volumes,
                }
                snapshots[code] = links, view
            if source_settings["sims"] == args.sims:
                stored = {}
                for links, _ in snapshots.values():
                    cache = {}
                    for link in links.to_dict("records"):
                        stored[link["token_id"]] = reads.model_prob(conn, link, cache, args.source_run)[0]
                forecasts[source_settings.model_key] = "stored", stored
                out["models"][source_settings["variant"]] = {
                    "origin": f"stored diagnostic #{args.source_run}",
                    "model_key": source_settings.model_key,
                }
            for profile in progress.track(
                list(selected.values()),
                unit="profile",
                name=lambda p: p["settings"]["variant"],
            ):
                settings = ss.Settings.from_dict(dict(profile["settings"], sims=args.sims))
                if set(settings["market_kinds"]) - set(KINDS):
                    raise ValueError("Unsupported profile market kinds")
                if settings.model_key in forecasts:
                    continue
                with settings.applied():
                    hist = pricing.history(meas, settings["track_features"])
                    summary, extras = pricing.price_race(
                        meas,
                        hist,
                        cutoff,
                        event["id"],
                        n_sims=args.sims,
                        rng=np.random.default_rng(settings.rng_seed),
                        use_track=settings["track_features"],
                        entrants=signals._entrants(meas, event["id"], cutoff),
                        venue=event["venue"],
                    )
                forecasts[settings.model_key] = (
                    "memory",
                    (summary.set_index("athlete_id"), extras),
                )
                out["models"][settings["variant"]] = {
                    "origin": "in-memory",
                    "model_key": settings.model_key,
                    "audit": extras["audit"],
                }

            def fair_for(settings, link):
                origin, forecast = forecasts[settings.model_key]
                if origin == "stored":
                    return forecast.get(link["token_id"])
                summary, extras = forecast
                kind, params = link["prediction"], link.get("params") or {}
                if kind == "race_constructor_top":
                    probability = extras["constructor_top"].get(params.get("team"))
                elif link["athlete_id"] in summary.index:
                    row = summary.loc[link["athlete_id"]]
                    if kind == "race_h2h":
                        probability = row["h2h"].get(integer_id(params.get("opponent_id")))
                    else:
                        column = {
                            "race_win": "win_prob",
                            "race_podium": "podium_prob",
                            "race_pole": "pole_prob",
                        }[kind]
                        probability = float(row[column])
                else:
                    return None
                return 1 - probability if probability is not None and link.get("invert") else probability

            for code, (links, view) in snapshots.items():
                for name, profile in selected.items():
                    settings = ss.Settings.from_dict(dict(profile["settings"], sims=args.sims))
                    view.tol_by_kind = ss.parse_map(settings["coherence_tol_by_kind"])
                    markets, reasons, by_key, details = [], {}, {}, {}
                    for link in links.to_dict("records"):
                        kind, key = link["prediction"], link["token_id"]
                        fair, midpoint = fair_for(settings, link), view.price(key, now)
                        volume = out["snapshot"][code]["volumes"][str(link["condition_id"])]
                        blocked = []
                        if kind not in settings["market_kinds"]:
                            blocked.append("market kind excluded by profile")
                        if fair is None:
                            blocked.append("no model probability")
                        if midpoint is None:
                            blocked.append("missing, stale (>10 min), or invalid two-sided quote")
                        if volume < settings["min_volume_24h"]:
                            blocked.append(f"recorded 24h volume ${volume:.2f} < ${settings['min_volume_24h']:.0f}")
                        if not view.coherent(kind, now):
                            blocked.append("quote group incoherent")
                        reasons[key] = "; ".join(blocked)
                        by_key[key] = link
                        edge = ss.parse_map(settings["min_edge_by_kind"]).get(
                            kind,
                            settings["min_edge_h2h"]
                            if kind == "race_h2h" and settings["min_edge_h2h"] is not None
                            else settings["min_edge"],
                        )
                        details[key] = {
                            "venue": code,
                            "profile": name,
                            "market_key": key,
                            "question": link["question"],
                            "fair_yes": fair,
                            "bid": None if pd.isna(link.get("last_bid")) else link["last_bid"],
                            "ask": None if pd.isna(link.get("last_ask")) else link["last_ask"],
                            "edge_threshold": edge,
                            "recorded_volume_24h": volume,
                        }
                        markets.append(
                            {
                                "key": key,
                                "kind": kind,
                                "subject": link["question"],
                                "outcome": None,
                                "stages": [
                                    {
                                        "label": "preview now",
                                        "t": now,
                                        "fair": fair,
                                        "price": midpoint,
                                        "bid": link["last_bid"],
                                        "ask": link["last_ask"],
                                        "tradeable": not blocked,
                                    }
                                ],
                            }
                        )
                    for sizing in ("original", "HK", "QK"):
                        params = sizing_params(
                            settings,
                            profile,
                            sizing,
                            fee=ws.taker_fee(code),
                            **out["sizing"],
                        )
                        passing, _ = rb.run_weekend(markets, params)
                        watch = [
                            dict(m, stages=[dict(m["stages"][0], tradeable=True)])
                            for m in markets
                            if reasons[m["key"]] and m["kind"] in settings["market_kinds"]
                        ]
                        watched, _ = rb.run_weekend(watch, replace(params, max_deployed=None))
                        if sizing != "original":
                            out["decisions"].extend(decision_rows(details, reasons, by_key, passing, watched, sizing))
                        out["checks"].append(
                            {
                                "venue": code,
                                "profile": name,
                                "sizing": sizing,
                                "passing": len(passing),
                                "watchlist": len(watched),
                            }
                        )
                        for trades, status in (
                            (passing, "passes preview filters"),
                            (watched, "watchlist only"),
                        ):
                            for trade in trades.to_dict("records"):
                                link, side = by_key[trade["key"]], trade["side"]
                                out["rows"].append(
                                    {
                                        "venue": code,
                                        "profile": name,
                                        "sizing": sizing,
                                        "market_key": trade["key"],
                                        "question": link["question"],
                                        "side": (link["outcome"] if side == "YES" else f"NOT {link['outcome']}")
                                        if trade["kind"] == "race_h2h"
                                        else side,
                                        "fair": trade["fair"] if side == "YES" else 1 - trade["fair"],
                                        "touch": link["last_ask"] if side == "YES" else 1 - link["last_bid"],
                                        "cost": trade["shares"] * trade["price"],
                                        "shares": trade["shares"],
                                        "status": status,
                                        "blocked_by": reasons[trade["key"]],
                                    }
                                )
            blend(out)
            for code in snapshots:
                for sizing in ("original", "HK", "QK"):
                    if not any(
                        c["venue"] == code and c["profile"] == "TB" and c["sizing"] == sizing for c in out["checks"]
                    ):
                        out["checks"].append(
                            {
                                "venue": code,
                                "profile": "TB",
                                "sizing": sizing,
                                "passing": 0,
                                "watchlist": 0,
                            }
                        )
            for code in out["coverage"]:
                if code not in snapshots:
                    for profile in out["profiles"]:
                        for sizing in ("original", "HK", "QK"):
                            out["checks"].append(
                                {
                                    "venue": code,
                                    "profile": profile,
                                    "sizing": sizing,
                                    "passing": 0,
                                    "watchlist": 0,
                                }
                            )
            for code in out["profiles"]:
                for sizing in ("HK", "QK"):
                    picked = [
                        r
                        for r in out["decisions"]
                        if r["profile"] == code and r["sizing"] == sizing and r["status"] == "picked"
                    ]
                    if any(r["cost"] > args.max_market + 1e-6 for r in picked):
                        raise RuntimeError("Per-market sizing cap exceeded")
                    if sum(r["cost"] for r in picked) > args.max_total + 1e-6:
                        raise RuntimeError("Aggregate sizing cap exceeded")
        return out
    finally:
        engine.dispose()


def blend(out):
    for sizing in ("original", "HK", "QK"):
        blended = {}
        for row in out["rows"]:
            if row["profile"] not in ("T1", "T8") or row["sizing"] != sizing:
                continue
            key = row["venue"], row["market_key"], row["side"], row["status"]
            if key not in blended:
                blended[key] = dict(row, profile="TB", cost=0.0, shares=0.0)
            blended[key]["cost"] += row["cost"] * 0.5
            blended[key]["shares"] += row["shares"] * 0.5
        out["rows"].extend(blended.values())
        for venue in {r["venue"] for r in blended.values()}:
            rows = [r for r in blended.values() if r["venue"] == venue]
            out["checks"].append(
                {
                    "venue": venue,
                    "profile": "TB",
                    "sizing": sizing,
                    "passing": sum(r["status"] == "passes preview filters" for r in rows),
                    "watchlist": sum(r["status"] == "watchlist only" for r in rows),
                }
            )
    for sizing in ("HK", "QK"):
        blended = {}
        for row in out["decisions"]:
            if row["profile"] not in ("T1", "T8") or row["sizing"] != sizing:
                continue
            key = row["venue"], row["market_key"]
            if key not in blended:
                blended[key] = dict(
                    row,
                    profile="TB",
                    cost=0.0,
                    shares=0.0,
                    standalone_watchlist_cost=0.0,
                    standalone_watchlist_shares=0.0,
                )
            for column in (
                "cost",
                "shares",
                "standalone_watchlist_cost",
                "standalone_watchlist_shares",
            ):
                blended[key][column] += row[column] * 0.5
            if row["status"] == "picked":
                blended[key]["status"] = "picked"
                blended[key]["reasons"] = ""
        out["decisions"].extend(blended.values())


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--sims", type=int, choices=(4000, 16000), default=4000)
    result.add_argument("--event", help="F1 event source key (must match the source run)")
    result.add_argument("--source-run", type=int, help="Existing diagnostic model run ID")
    result.add_argument("--snapshot", help="Freeze inputs using a prior preview JSON")
    result.add_argument("--bankroll", type=float, default=1000)
    result.add_argument("--max-market", type=float, default=50)
    result.add_argument("--max-total", type=float, default=250)
    result.add_argument("--render", help="Render saved JSON without opening a database")
    result.add_argument("--output-dir", help="Report/CSV directory, required for --render")
    return result


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.render:
        if not args.output_dir:
            cli.error("--render requires --output-dir")
        if args.snapshot or args.event or args.source_run:
            cli.error("--render cannot be combined with computation inputs")
        render(json.loads(Path(args.render).read_text()), args.output_dir)
        return
    if not args.event or args.source_run is None:
        cli.error("computation requires --event and --source-run")
    if args.output_dir:
        cli.error("--output-dir is only used with --render")
    if any(not math.isfinite(value) or value <= 0 for value in (args.bankroll, args.max_market, args.max_total)):
        cli.error("bankroll and caps must be positive finite amounts")
    from racinglines import progress

    progress.start("strategy preview", every=300)
    try:
        data = compute(args)
        json.dump(data, sys.stdout, allow_nan=False, indent=2)
        print()
    finally:
        progress.stop()


if __name__ == "__main__":
    main()
