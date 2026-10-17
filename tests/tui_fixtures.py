"""TUI test payloads in the shapes the hosted MCP server returned on 2026-10-16 (trimmed), and a fake backend that
serves them: the TUI tests need no network and no database."""
from __future__ import annotations

from typing import Any

OVERVIEW = {
    "sports": {"f1_wdc": "f1", "motogp_wc": "motogp", "nascar_cup": "nascar", "uci_dhi_wc": "mtb_dh"},
    "seasons": [{"competition": "f1_wdc", "season": 2026, "events": 23, "completed": 17,
                 "first": "2026-03-08", "last": "2026-12-06"}],
    "forecasts": [
        {"id": 9929, "created_at": "2026-10-11T21:43:58+00:00", "data_through": "2026-10-11",
         "code_version": "2b7b410", "cutoff": None, "competition": "f1_wdc",
         "competition_name": "Formula 1 World Championship (Drivers)", "category": "DRV",
         "category_name": "Drivers", "season": 2026},
    ],
    "model_runs": [{"kind": "diagnostic", "runs": 9362, "latest": "2026-10-14T06:55:05+00:00"}],
    "market_links": [{"exchange": "polymarket", "links": 10560, "open": 1179, "races": 68}],
    "venues": [{"code": "polymarket", "name": "Polymarket", "status": "live", "kind": "exchange"}],
    "users": [{"username": "maker", "role": "maker", "profile": "C · maker sleeve (gbm)"},
              {"username": "taker", "role": "taker", "profile": "A · core taker (update)"}],
    "upcoming": [{"event_id": 91, "competition": "f1_wdc", "name": "UNITED STATES GRAND PRIX 2026",
                  "start_date": "2026-10-25"}],
    "row_counts": {"events": 818, "results": 80346, "athletes": 1403},
    "hint": "Start with list_events",
}

FORECAST = {"forecasts": [{
    "run": OVERVIEW["forecasts"][0],
    "next_races": [{"target": "event:2026-18", "event": "UNITED STATES GRAND PRIX 2026", "start_date": "2026-10-25",
                    "top": [{"athlete_id": 1143, "athlete": "Max Verstappen", "nation": "", "win_prob": 0.1413,
                             "podium_prob": 0.3681, "top10_prob": 0.7991, "make_final_prob": None,
                             "exp_points": 10.4909},
                            {"athlete_id": 1147, "athlete": "Charles Leclerc", "nation": "", "win_prob": 0.1263,
                             "podium_prob": 0.3399, "top10_prob": 0.7816, "make_final_prob": None,
                             "exp_points": 9.9162}]},
                   {"target": "event:2026-19", "event": "MEXICO 2026", "start_date": "2026-11-01",
                    "top": [{"athlete_id": 1157, "athlete": "George Russell", "win_prob": 0.1339,
                             "podium_prob": 0.3573, "top10_prob": 0.79, "exp_points": 10.1}]}],
    "standings": [{"athlete_id": 1169, "athlete": "Kimi Antonelli", "current_points": 335.0, "exp_points": 391.78,
                   "points_p10": 364.0, "points_p90": 421.0, "champion_prob": 0.9997, "top3_prob": 1.0,
                   "top10_prob": 1.0, "exp_rank": 1.0003}],
    "targets": 6,
    "sources": {"text": "Sources: results: F1 live timing via FastF1 · fair values: racinglines model (run #9929)"},
}]}

MARKETS = {
    "race_id": 136, "event_id": 91, "title": "Austin GP", "competition": "f1_wdc", "season": 2026,
    "status": "scheduled", "start_date": "2026-10-25", "race_start": "2026-10-25T20:00:00",
    "pricing": {"run_id": 9955, "source": "live stage", "cadence": "updated every 5 min during sessions"},
    "freshness": {"stale_hours": 3.0, "any_stale": True, "venues": [
        {"venue": "polymarket", "links": 266, "synced_at": "2026-10-16T00:23:12+00:00", "age_hours": 0.045,
         "stale": False, "reason": None},
        {"venue": "kalshi", "links": 0, "synced_at": None, "age_hours": None, "stale": True,
         "reason": "no linked markets"}]},
    "outcomes": {"columns": ["kind", "subject", "detail", "athlete_id", "team", "opponent_id", "fair", "result",
                             "polymarket_mid", "polymarket_bid", "polymarket_ask", "polymarket_volume",
                             "polymarket_token", "polymarket_closed", "gap_polymarket"],
                 "rows": [
                     {"kind": "race_win", "subject": "Max Verstappen", "detail": "", "athlete_id": 1143,
                      "team": None, "opponent_id": None, "fair": 0.1517, "result": None, "polymarket_mid": 0.435,
                      "polymarket_bid": 0.43, "polymarket_ask": 0.44, "polymarket_volume": 426.04,
                      "polymarket_token": "6206", "polymarket_closed": False, "gap_polymarket": -0.2833},
                     {"kind": "race_win", "subject": "Charles Leclerc", "detail": "", "athlete_id": 1147,
                      "team": None, "opponent_id": None, "fair": 0.1215, "result": None, "polymarket_mid": 0.065,
                      "polymarket_bid": 0.05, "polymarket_ask": 0.08, "polymarket_volume": 20.0,
                      "polymarket_token": "2785", "polymarket_closed": False, "gap_polymarket": 0.0565}],
                 "total": 23, "offset": 0, "limit": 2, "truncated": True, "next_offset": 2, "note": ""},
}

FANTASY_MARKETS = {"markets": {"columns": ["market_link_id", "exchange", "kind", "question", "subject", "event",
                                           "start_date", "bid", "ask", "book_ts"],
                               "rows": [{"market_link_id": 40423, "exchange": "polymarket", "kind": "race_podium",
                                         "question": "Will Alexander Albon finish on the podium?",
                                         "subject": "Alexander Albon", "event": "United States Grand Prix",
                                         "start_date": "2026-10-25", "bid": None, "ask": 0.5,
                                         "book_ts": "2026-10-15T03:03:07+00:00"}],
                               "total": 229, "offset": 0, "limit": 50, "truncated": True, "next_offset": 50},
                   "max_stake": 100.0, "max_age_min": 15.0}

BOOK = {"market_link_id": 40423, "exchange": "polymarket", "kind": "race_podium",
        "ts": "2026-10-15 03:03:07.372000+00:00", "yes_bids": [],
        "yes_asks": [[0.5, 500.0], [0.95, 12.79]], "no_bids": [[0.5, 500.0], [0.05, 12.79]], "no_asks": []}

BALANCE = {"user": "admin", "grant": 1000.0, "cash": 1000.0, "held": 0, "open": 0, "unpriced": 0,
           "manual_pnl": 0.0, "strategy_pnl": 0.0, "strategy_positions": 0, "total": 1000.0}

JOB_TYPES = {"job_types": [
    {"job_type": "f1_scenario", "sport": "f1", "label": "Forward forecast (scenario)", "what": "Price every race.",
     "takes": "~1-2 min", "knobs": [
         {"name": "label", "type": "text", "default": "my scenario", "min": None, "max": None, "choices": None,
          "help": ""},
         {"name": "sims", "type": "int", "default": 10000, "min": 1000, "max": 50000, "choices": None, "help": ""},
         {"name": "track", "type": "choice", "default": "on", "choices": ["on", "off"], "help": "Sector model."}]},
    {"job_type": "f1_sweep", "sport": "f1", "label": "Edge Finder sweep", "what": "Every weekend.",
     "takes": "minutes", "knobs": [
         {"name": "year", "type": "choice", "default": "2026", "choices": ["2026", "2025"], "help": ""},
         {"name": "settings", "type": "object", "help": "any sweep setting"}]}],
    "sweep_settings": [
        {"name": "sims", "group": "model", "type": "int", "default": 4000, "min": 1000, "max": 50000,
         "choices": None, "help": ""},
        {"name": "track_features", "group": "model", "type": "bool", "default": True, "choices": None, "help": ""},
        {"name": "taker_stages", "group": "timing", "type": "multi", "default": ["pre-weekend", "after FP1"],
         "choices": ["pre-weekend", "after FP1", "after FP2"], "help": ""},
        {"name": "min_edge_by_kind", "group": "taker", "type": "map", "default": None, "min": 0.005, "max": 0.5,
         "choices": ["race_win"], "help": "kind=edge"},
        {"name": "fill", "group": "maker", "type": "choice", "default": "through",
         "choices": ["through", "touch", "queue"], "help": ""},
        {"name": "variant", "group": "model", "type": "text", "default": "baseline", "choices": None, "help": ""},
        {"name": "min_edge", "group": "taker", "type": "float", "default": 0.05, "min": 0.005, "max": 0.5,
         "choices": None, "help": ""},
        {"name": "venue", "group": "markets", "type": "choice", "default": None,
         "choices": ["polymarket", "kalshi", "og"], "help": ""}],
    "sport_sweep_settings": {}}

TABLE = {"columns": ["id", "name", "status", "pnl"],
         "rows": [{"id": 1, "name": "alpha", "status": "done", "pnl": 12.5},
                  {"id": 2, "name": "beta", "status": "running", "pnl": -3.25}],
         "total": 2, "offset": 0, "next_offset": None}

PAYLOADS: dict[str, Any] = {
    "overview": OVERVIEW,
    "get_forecast": FORECAST,
    "list_markets": MARKETS,
    "list_events": {"events": {"columns": ["id", "source_key", "competition", "season", "name", "start_date",
                                           "status"],
                               "rows": [{"id": 91, "source_key": "2026-18", "competition": "f1_wdc", "season": 2026,
                                         "name": "UNITED STATES GRAND PRIX 2026", "start_date": "2026-10-25",
                                         "status": "scheduled"}], "total": 1}},
    "get_event": {"event": {"id": 91, "name": "UNITED STATES GRAND PRIX 2026", "competition": "f1_wdc",
                            "season": 2026, "status": "scheduled", "source_key": "2026-18"},
                  "races": [{"race_id": 136, "title": "Austin GP", "race_start": "2026-10-25T20:00:00"}]},
    "search_athletes": [{"id": 1143, "name": "Max Verstappen", "results": 230, "wins": 70}],
    "get_athlete": {"athlete": {"id": 1143, "name": "Max Verstappen"}, "results": TABLE},
    "fantasy_balance": BALANCE,
    "fantasy_markets": FANTASY_MARKETS,
    "fantasy_book": BOOK,
    "fantasy_positions": {"positions": TABLE},
    "fantasy_orders": {"orders": TABLE},
    "fantasy_leaderboard": {"leaderboard": TABLE},
    "fantasy_order": {"status": "filled", "filled": 10, "avg_price": 0.5, "fee": 0.0},
    "list_job_types": JOB_TYPES,
    "list_jobs": {"jobs": TABLE},
    "get_job": {"job": {"id": 1, "status": "done", "job_type": "f1_scenario", "result_run_id": 9929},
                "log": ["start", "priced 6 targets", "saved run 9929"]},
    "run_job": {"job_id": 7, "status": "queued"},
    "get_market_history": {"tokens": [], "series": "prices",
                           "rows": {"columns": ["ts", "token", "price"],
                                    "rows": [{"ts": f"2026-10-1{i // 10}T{i % 10:02d}:00", "token": "6206",
                                              "price": 0.4 + i * 0.002} for i in range(40)]}},
}


class FakeBackend:
    label = "fake://racinglines"
    server_name = "racinglines (fake)"
    connected = True

    def __init__(self, book_age_min: float = 1.0) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.book_age_min = book_age_min

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def call(self, tool: str, **args: Any) -> Any:
        self.calls.append((tool, {k: v for k, v in args.items() if v is not None}))
        if tool == "fantasy_book":
            from datetime import datetime, timedelta, timezone
            ts = datetime.now(timezone.utc) - timedelta(minutes=self.book_age_min)
            return {**BOOK, "ts": ts.isoformat()}
        return PAYLOADS.get(tool, {"note": f"{tool} sample", "rows": TABLE})


# ---- Shapes captured from the live server on 2026-10-16 (trimmed) --------------------------------

def _t(columns, rows, total=None, offset=0, next_offset=None, note=""):
    return {"columns": columns, "rows": rows, "total": total if total is not None else len(rows),
            "offset": offset, "next_offset": next_offset, "note": note}


LIVE = {
    "list_events": _t(["id", "season", "start_date", "name", "venue", "country", "series_round", "status",
                       "source_key", "competition", "races"],
                      [{"id": 90, "season": 2026, "start_date": "2026-10-11", "name": "SINGAPORE GRAND PRIX 2026",
                        "venue": "Marina Bay", "country": None, "series_round": 17, "status": "completed",
                        "source_key": "2026-17", "competition": "f1_wdc", "races": 1}], total=148, next_offset=50),
    "get_event": {
        "event": {"id": 90, "source_key": "2026-17", "name": "SINGAPORE GRAND PRIX 2026", "start_date": "2026-10-11",
                  "series_round": 17, "status": "completed", "season": 2026, "venue": "Marina Bay",
                  "competition": "f1_wdc"},
        "races": [{"race_id": 135, "category": "DRV", "format": {"kind": "f1", "sprint": True}}],
        "results": _t(["race_id", "round", "position", "athlete_id", "athlete", "team", "status", "time_s"],
                      [{"race_id": 135, "round": "race", "position": 1.0, "athlete_id": 1143,
                        "athlete": "Max Verstappen", "team": "Red Bull Racing", "status": "OK", "time_s": 6120.785},
                       {"race_id": 135, "round": "race", "position": 20.0, "athlete_id": 1149,
                        "athlete": "Lance Stroll", "team": "Aston Martin", "status": "DNF", "time_s": None}]),
        "rounds": {"qual": 22, "race": 22},
        "predictions": _t(["run", "kind", "athlete_id", "athlete", "win_prob"],
                          [{"run": 9909, "kind": "diagnostic", "athlete_id": 1144, "athlete": "Lando Norris",
                            "win_prob": 0.2157}], total=902, next_offset=60),
    },
    "list_jobs": _t(["id", "kind", "sport", "status", "progress", "created_at", "started_at", "finished_at",
                     "result_run_id", "params", "user"],
                    [{"id": 5, "kind": "f1_combo", "sport": "f1", "status": "done", "progress": "finished",
                      "created_at": "2026-10-13T14:11:33+00:00", "finished_at": "2026-10-13T14:11:48+00:00",
                      "result_run_id": 9950.0, "params": {"_keys": ["legs"]}, "user": "admin"},
                     {"id": 4, "kind": "walk_forward", "sport": "f1", "status": "failed", "progress": "exit code 1",
                      "created_at": "2026-10-11T21:37:48+00:00", "result_run_id": None,
                      "params": {"model": "own"}, "user": "admin"}], total=5),
    "get_job": {"id": 4, "kind": "walk_forward", "sport": "f1", "status": "failed", "progress": "exit code 1",
                "argv": ["-m", "racinglines", "backtest", "walk-forward", "f1", "--venue", "kalshi"],
                "result_run_id": None, "log_lines": 28,
                "log_tail": ["  File \"argparse.py\", line 1667", "argparse.ArgumentError: argument --venue: "
                             "conflicting option string: --venue"]},
    "track_record": {"user": "taker", "venue": "polymarket", "sport": None, "weekends": 91, "pnl": 2823.56, "up": 33,
                     "rows": _t(["event_key", "profile", "strategy", "signals", "taken", "pnl", "event_name",
                                 "sport", "start_date"],
                                [{"event_key": "2025-01", "profile": "TW1", "strategy": "update", "signals": 32,
                                  "taken": 8, "pnl": -22.33, "event_name": "Australian GP", "sport": "f1",
                                  "start_date": "2025-03-16"},
                                 {"event_key": "2025-05", "profile": "TW1", "strategy": "update", "signals": 27,
                                  "taken": 12, "pnl": 333.69, "event_name": "Saudi Arabian GP", "sport": "f1",
                                  "start_date": "2025-04-20"}], total=91, next_offset=68)},
    "list_positions": {"user": "taker",
                       "totals": [{"venue": "kalshi", "sum": 2307.70, "count": 256},
                                  {"venue": "private", "sum": -30.5, "count": 35}],
                       "positions": _t(["event_key", "venue", "kind", "subject", "yes_shares", "no_shares", "cash",
                                        "mark", "outcome", "pnl"],
                                       [{"event_key": "2026-SPA", "venue": "kalshi", "kind": "race_win",
                                         "subject": "Marco Bezzecchi", "yes_shares": 454.5, "no_shares": 0.0,
                                         "cash": -52.87, "mark": 0.1, "outcome": False, "pnl": -52.87}],
                                       total=426, next_offset=100)},
    "list_signals": _t(["id", "event_key", "kind", "subject", "stage", "action", "side", "shares", "limit_price",
                        "fair", "price", "edge", "status", "signal_ts"],
                       [{"id": 200613, "event_key": "2026-17", "kind": "race_win", "subject": "Max Verstappen",
                         "stage": "after Quali", "action": "buy", "side": "NO", "shares": 4624.9,
                         "limit_price": 0.0105, "fair": 0.3688, "price": 0.9995, "edge": -0.6308,
                         "status": "alerted", "signal_ts": "2026-10-11T14:35:02+00:00"}], total=1810, next_offset=100),
    "fantasy_orders": {"user": "admin", "orders": _t([], [])},
    "fantasy_leaderboard": {"min_trades": 5, "rows": _t(["rank", "username", "score", "roi", "trades", "pnl"],
                                                        [{"rank": None, "username": "admin", "score": None,
                                                          "roi": None, "trades": 0, "pnl": 0.0}], total=19)},
    "edge_finder": {"year": 2026, "venue": None, "configurations": 40,
                    "changed_settings": {"05f1f5bd32bc": {"variant": "gridq+pretrain+reset", "sims": 16000,
                                                          "min_edge": 0.1, "taker_stages": ["after FP1", "after FP2"],
                                                          "venue": "kalshi"}},
                    "rows": _t(["config", "settings_key", "run_id", "venue", "strategy", "strategy_label", "pnl",
                                "volume", "roi", "weekends", "up", "drawdown"],
                               [{"config": "gridq+pretrain+reset · sims=16000", "settings_key": "05f1f5bd32bc",
                                 "run_id": 9641, "venue": "kalshi", "strategy": "last",
                                 "strategy_label": "Taker: after quali only", "pnl": 56011.63, "volume": 26919.54,
                                 "roi": 2.0807, "weekends": 16, "up": 8, "drawdown": -5000.0}],
                               total=360, next_offset=100)},
    "list_diagnostics": _t(["event_key", "runs", "first_run", "last_run", "first_cutoff", "last_cutoff",
                            "from_sweep"],
                           [{"event_key": "2026-19", "runs": 30, "first_run": 9142, "last_run": 9956,
                             "first_cutoff": "2026-10-05 07:01:20", "last_cutoff": "2026-10-14 06:54:20",
                             "from_sweep": True}], total=647, next_offset=100),
    "list_candidates": _t(["id", "name", "strategy", "strategy_label", "year", "why", "run_id"],
                          [{"id": 9951, "name": "T8 · stage-aware", "strategy": "early",
                            "strategy_label": "stage-aware (stop after FP2)", "year": 2026, "why": "defaults-2026-10",
                            "run_id": None}], total=19),
    "list_model_runs": _t(["id", "kind", "competition", "season", "category", "model", "created_at", "variant",
                           "label"],
                          [{"id": 9641, "kind": "sweep", "competition": "f1_wdc", "season": 2026, "category": "DRV",
                            "model": "f1_sector_sim", "created_at": "2026-10-06T01:18:35+00:00",
                            "variant": "gridq+pretrain+reset", "label": "gridq · sims=16000"}], total=244,
                          next_offset=50),
    "get_model_run": {"run": {"id": 9641, "kind": "sweep", "competition": "f1_wdc", "season": 2026},
                      "params": {"year": 2026, "settings": {"sims": 16000, "venue": "kalshi"}}, "targets": [],
                      "metrics": {"_size": 37469, "keys": {"scores": 2534, "totals": 932, "weekends": 33152},
                                  "note": "pass path='metrics.<key>' for one part"}},
    "describe_schema": {"tables": [{"table": "events", "what": "a race weekend / round"},
                                   {"table": "results", "what": "one row per athlete per round"}]},
    "sql": {"columns": ["id", "name"], "rows": [{"id": 96, "name": "ABU DHABI GP"}, {"id": 95, "name": "QATAR GP"}],
            "total": None, "offset": 0, "limit": 2, "truncated": True, "next_offset": 2,
            "note": "2 rows shown, more exist"},
    "data_changes": _t(["id", "at", "sport", "kind", "summary", "by", "detail"],
                       [{"id": 501, "at": "2026-10-16T00:32:11+00:00", "sport": "nascar", "kind": "forecast",
                         "summary": "nascar forecast run 10011", "by": "racinglines@vm",
                         "detail": {"run": 10011, "races": ["2026-5633"]}}], total=501, next_offset=100),
    "list_live_events": {"state": "replay",
                         "settled": _t(["run", "sport", "event_key", "maker_pnl"], []),
                         "run_folders": [{"run": "2026-17", "sport": "f1", "event_key": "2026-17",
                                          "title": "Singapore GP", "updated": "2026-10-11T22:59:46+00:00"}]},
}
PAYLOADS.update(LIVE)
