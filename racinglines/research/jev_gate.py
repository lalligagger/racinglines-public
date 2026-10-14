"""Research: ask TypeSafe's Jev whether a historical taker buy signal is one the model is probably missing something on.

Read-only and offline-first. For each buy signal it builds a leakage-safe state (only what was known at the signal's
stage: the subject driver's finished sessions this weekend, never the race, plus his previous finishes) and asks three
narrow questions. Answers are cached on disk so a rerun with the same state costs nothing; `plan` counts the API calls
a run would make so the caller can confirm before spending. Replaying "take all" vs "skip when Jev objects" is a later
step. `typesafe_sdk` is a research-only dependency, imported lazily inside `make_client`.

Signal -> event: `strategy_signals.race_id` is `races.id`; its `events.source_key` equals the signal's `event_key`
(e.g. '2026-15'). Sessions come from `rounds` (kind fp1..qual) of that race, dated by `rounds.extra['session_date']`
(naive, read as UTC).
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

DEFAULT_PROFILE = "TW2 · grid-aware taker, 10-pt edge"
DEFAULT_MODEL = "jev-latest"
CACHE_DIR = Path("data/runs/jev_gate/cache")

# Sessions finished by each stage. 'race' is in no list, on purpose.
STAGE_SESSIONS = {
    "pre-weekend": (),
    "after FP1": ("fp1",),
    "after FP2": ("fp1", "fp2"),
    "after FP3": ("fp1", "fp2", "fp3"),
    "after SQ": ("fp1", "fp2", "fp3", "sprint_qual"),
    "after Sprint": ("fp1", "fp2", "fp3", "sprint_qual", "sprint"),
    "after Quali": ("fp1", "fp2", "fp3", "sprint_qual", "sprint", "qual"),
}
PREV_RACES = 3

QUESTIONS = {
    "model_missing": {
        "type": "noul",
        "instructions": (
            "A model priced a Formula 1 driver for a race market and we bought `side` at `price` because the model's "
            "`fair` is higher than the price paid for that side. Using only `sessions` (this weekend's finished "
            "sessions for `subject`: `position`, `status`, `field`, `gap_to_p1_ms`) and `recent_races` (his last "
            "finishing positions, most recent first), do those results show something that makes the race outcome "
            "less favourable for the side bought than `fair` implies? If `sessions` is null or empty, answer from "
            "`recent_races` alone and lean no."
        ),
        "criteria": {
            "true": "The session results or recent finishes point against the side bought, for example a poor grid-"
                    "relevant session, a non-OK status, or a gap to P1 that is large for the price paid.",
            "false": "The results are consistent with or better than what `fair` implies, or they are uninformative.",
        },
    },
    "stale_edge": {
        "type": "noul",
        "instructions": (
            "Is the gap between `fair` and `price` more likely a stale or thin exchange quote than real information "
            "the market has priced? Judge from the size of `edge` and from how far `price` sits from `fair` given "
            "`stage`."
        ),
        "criteria": {
            "true": "The gap looks like a stale, thin or lagging quote.",
            "false": "The gap looks like the market reacting to information the model lacks, or a genuine mispricing.",
        },
    },
    "gap_cause": {
        "type": "choice",
        "instructions": "Why does `fair` differ from `price` for this market at this stage?",
        "criteria": {
            "model_sees_more": "The model uses information the market has not priced yet.",
            "market_sees_more": "The market has priced information the model lacks.",
            "thin_book": "The price is a thin or stale quote, not a considered view.",
            "unclear": "The state does not say.",
        },
    },
}


def parse_ts(v):
    if v is None or isinstance(v, datetime):
        d = v
    else:
        d = datetime.fromisoformat(str(v))
    if d is not None and d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def build_state(signal, sessions, prior_races):
    """Pure core of `signal_state`.

    sessions: None when the subject did not match an athlete, else dicts of kind, session_date, position, status,
    field, gap_to_p1_ms for every round of the weekend (the race included; it is filtered out here).
    prior_races: dicts of start_date, position for the driver's earlier races.
    """
    state = {
        "market": {"kind": signal.get("kind"), "subject": signal.get("subject"), "stage": signal.get("stage")},
        "side": signal.get("side"),
        "fair": signal.get("fair"),
        "price": signal.get("price"),
        "edge": signal.get("edge"),
        "sessions": None,
        "recent_races": None,
    }
    if sessions is None:
        return state
    allowed = STAGE_SESSIONS.get(signal.get("stage"), ())
    ts = parse_ts(signal.get("signal_ts"))
    out = {}
    for s in sessions:
        if s["kind"] not in allowed:
            continue
        sd = parse_ts(s.get("session_date"))
        if ts is not None and sd is not None and sd > ts:
            continue
        out[s["kind"]] = {k: s.get(k) for k in ("position", "status", "field", "gap_to_p1_ms")}
    state["sessions"] = {k: out[k] for k in sorted(out)}
    cutoff = parse_ts(signal.get("event_start"))
    prev = [p for p in prior_races if cutoff is None or parse_ts(p["start_date"]) < cutoff]
    prev.sort(key=lambda p: parse_ts(p["start_date"]), reverse=True)
    state["recent_races"] = [{"position": p["position"], "status": p.get("status")} for p in prev[:PREV_RACES]]
    return state


_ATHLETES = text("""
    select id from athletes where display_name = :n
    union select athlete_id from athlete_identifiers where scheme = 'name' and value = :n""")
_SESSIONS = text("""
    select rd.kind, rd.extra->>'session_date' as session_date, r.position, r.status,
           (select count(*) from results x where x.round_id = rd.id) as field,
           case when r.time_ms is not null then r.time_ms -
                (select min(x.time_ms) from results x where x.round_id = rd.id and x.position = 1) end as gap_to_p1_ms
    from rounds rd join results r on r.round_id = rd.id
    where rd.race_id = :race and rd.kind <> 'race' and r.athlete_id = any(:ids)""")
_PRIOR = text("""
    select e.start_date, r.position, r.status
    from rounds rd join races ra on ra.id = rd.race_id join categories c on c.id = ra.category_id
    join events e on e.id = ra.event_id join results r on r.round_id = rd.id
    where rd.kind = 'race' and c.name = 'Drivers' and e.source = 'f1timing' and e.start_date < :start
      and r.athlete_id = any(:ids)
    order by e.start_date desc limit :n""")


def signal_state(signal, engine):
    """The state for one signal row (a dict with the strategy_signals columns), read from the database."""
    with engine.connect() as c:
        ids = [r[0] for r in c.execute(_ATHLETES, {"n": signal.get("subject")})] if signal.get("subject") else []
        start = c.execute(text("select e.start_date from races r join events e on e.id = r.event_id where r.id = :r"),
                          {"r": signal.get("race_id")}).scalar()
        if not ids or start is None:
            return build_state(signal, None, [])
        sessions = [dict(r._mapping) for r in c.execute(_SESSIONS, {"race": signal["race_id"], "ids": ids})]
        prior = [dict(r._mapping) for r in c.execute(_PRIOR, {"ids": ids, "start": start, "n": PREV_RACES})]
    return build_state({**signal, "event_start": str(start)}, sessions, prior)


def load_signals(engine, profile=DEFAULT_PROFILE, kind="race_win", settle="results"):
    """Buy signals of a profile with a settled outcome; returns (signals, number skipped for no outcome).

    settle="results" (race_win only) reads the outcome off the race result by race id and exact driver name, so it
    covers every signal; settle="positions" keeps only markets a simulated user followed (paper_positions)."""
    if settle == "results":
        if kind != "race_win":
            raise ValueError("settle='results' only knows race_win")
        q = text("""
            select s.*, w.won as outcome from strategy_signals s
            left join (select ro.race_id, a.display_name, bool_or(r.position = 1) as won
                       from rounds ro join results r on r.round_id = ro.id
                       join athletes a on a.id = r.athlete_id where ro.kind = 'race'
                       group by 1, 2) w on w.race_id = s.race_id and w.display_name = s.subject
            where s.action = 'buy' and s.profile = :p and s.kind = :k order by s.signal_ts""")
    else:
        q = text("""
            select s.*, p.outcome from strategy_signals s
            left join paper_positions p on p.user_id = s.user_id and p.candidate_id = s.candidate_id
                                       and p.market_key = s.market_key
            where s.action = 'buy' and s.profile = :p and s.kind = :k order by s.signal_ts""")
    with engine.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(q, {"p": profile, "k": kind})]
    settled = [r for r in rows if r["outcome"] is not None]
    return settled, len(rows) - len(settled)


def _key(state, model):
    blob = json.dumps({"state": state, "questions": QUESTIONS, "model": model}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _path(state, model, cache_dir):
    return Path(cache_dir) / f"{_key(state, model)}.json"


def plan(signals, states=None, model=DEFAULT_MODEL, cache_dir=CACHE_DIR):
    """Dry run, no network: unique states, how many are cached and how many API calls a run would make.

    `states` are precomputed states aligned with `signals`; with none given, each signal dict is hashed as is."""
    items = states if states is not None else signals
    keys = {_key(s, model) for s in items}
    cached = sum((Path(cache_dir) / f"{k}.json").exists() for k in keys)
    return {"signals": len(items), "unique_states": len(keys), "cached": cached, "api_calls": len(keys) - cached}


def make_client():
    """The TypeSafe client; the key comes from TYPESAFE_API_KEY only."""
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise RuntimeError("TYPESAFE_API_KEY is not set")
    from typesafe_sdk import RetryPolicy, TypeSafeClient
    return TypeSafeClient(retry=RetryPolicy(max_retries=3, timeout=30.0))


def ask(state, client=None, model=DEFAULT_MODEL, cache_dir=CACHE_DIR):
    """All three answers for a state (full probabilities and confidence kept), from cache when the key is unchanged."""
    path = _path(state, model, cache_dir)
    if path.exists():
        return json.loads(path.read_text())
    client = client or make_client()
    resp = client.system_one(state=state, questions=QUESTIONS, model=model)
    answers = {}
    for name, a in resp.nouls.items():
        answers[name] = {"type": "noul", "noul": a.noul}
    for name, a in resp.choices.items():
        answers[name] = {"type": "choice", "choice": a.choice, "confidence": a.confidence,
                         "probabilities": dict(a.probabilities)}
    rec = {"key": _key(state, model), "model": model, "answered_by": getattr(resp, "model", None),
           "state": state, "answers": answers}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, sort_keys=True, indent=1, default=str))
    return rec
