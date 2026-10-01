"""A synthetic third sport for the live core's tests (tests/test_live_toy.py): a toy sprint race whose "feed" is
each runner's split times, generated from the spec's seed. It implements the adapter interface (markets,
step, outcomes, view) with the shared core and nothing else, which is the point: a new sport needs a [live]
section, a launch spec, an adapter and a body partial, and no change to pipelines/live.py, markets/crowd.py,
markets/quoting.py or the Live tab's shell."""

import json
from datetime import datetime, timedelta, timezone

import numpy as np

from racinglines.markets import crowd as C
from racinglines.markets import quoting as Q
from racinglines.pipelines import live as LV

RUNNERS = ["Ada", "Bo", "Cy", "Di"]


def feed(spec, poll):
    """The race after `poll` polls: each runner's distance covered (0-100), and done once all have finished."""
    rng = np.random.default_rng(spec["feed"]["seed"])
    speed = rng.uniform(9, 11, len(RUNNERS))
    dist = np.minimum(100.0, speed * (poll + 1))
    return dict(dist=dist.tolist(), done=bool((dist >= 100).all()))


def markets(spec, state):
    """Win markets, fair from the gap to the leader (a softmax); certain once the race is over."""
    d = np.array(state["dist"])
    if state["done"]:
        return [dict(key=f"race_win:{r}", kind="race_win", subject=r, fair=float(i == int(d.argmax()))) for i, r in enumerate(RUNNERS)]
    w = np.exp((d - d.max()) / 3.0)
    p = w / w.sum()
    return [dict(key=f"race_win:{r}", kind="race_win", subject=r, fair=float(x)) for r, x in zip(RUNNERS, p)]


def outcomes(spec, state):
    return {m["key"]: bool(m["fair"]) for m in markets(spec, state)} if state["done"] else {}


def step(spec, now=None, echo=print, **_):
    """One poll: feed -> markets -> quotes -> one crowd poll -> snapshot."""
    live = spec["live"]
    out = LV.folder(spec["run"])
    polls = LV.read_jsonl(out / "crowd.jsonl")
    if polls and polls[-1].get("done"):
        return None
    state = feed(spec, len(polls))
    cp, qp = C.Params.from_dict(live["crowd"]), Q.Params.from_dict(live["quoting"])
    book = C.load_book(out, cp)
    mk = markets(spec, state)
    oc = outcomes(spec, state)
    quotes = [dict(key=m["key"], fair=m["fair"], inv=book["markets"].get(m["key"], {}).get("inv", 0.0),
                   **dict(zip(("bid", "ask"), (None, None) if oc else Q.quote(m["fair"], qp.half_spread,
                                                                           book["markets"].get(m["key"], {}).get("inv", 0.0),
                                                                           qp.max_pos, qp.skew))))
              for m in mk]
    ts = (datetime(2026, 11, 1, 12, tzinfo=timezone.utc) + timedelta(seconds=live["poll"]["interval_s"] * len(polls)))
    fills = [] if oc else C.fills(quotes, book, np.random.default_rng(len(polls)), cp)
    (out / "book.json").write_text(json.dumps(book))
    LV.append(out, "crowd.jsonl", dict(ts=ts.isoformat(), seed=len(polls), fills=fills, done=bool(oc)))
    fair = {m["key"]: m["fair"] for m in mk}
    LV.write_meta(out, dict(sport="toy_sprint", event_key=spec["event"], title=spec["title"]), ts.strftime("%Y%m%dT%H%M%S"))
    snap = dict(ts=ts.isoformat(), sport="toy_sprint", done=bool(oc), dist=state["dist"], quotes=quotes,
                maker_pnl=C.book_pnl(book, fair, oc), outcomes=[dict(key=k, yes=v) for k, v in oc.items()])
    LV.write_snapshot(out, snap, ts.strftime("%Y%m%dT%H%M%S"))
    LV.append(out, "history.jsonl", dict(ts=snap["ts"], fair=fair))
    echo(f"{snap['ts']} toy: {len(fills)} fills" + (" · over" if oc else ""))
    return snap


def view(run, snap, picks, hist, mode, maker):
    mk, polls = LV.book_at(run, snap["ts"] if mode == "replay" else None)
    return dict(rows=[dict(q, dist=d) for q, d in zip(snap["quotes"], snap["dist"])], fills=sum(len(p["fills"]) for p in polls))
