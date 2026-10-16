"""Research: Jev as a fantasy player in the 2026 season demo. Spec: reports/2026-10-15-jev-player/PREREG.md (v1).

Each round Jev answers one System One request: a `style` Choice over the five alpha cards, a `sizing` Choice over
standard / quarter / half Kelly, and four `basis_*` Nouls recorded as a pre-registered self-report (they never change
the pick). The state is built from copied data only (`snapshot`), checked by a mutation test and a canary guard.

Pure apart from the disk cache in `ask` and the lock-file writer's caller. No database access here: the per-style
series comes from `season_demo --export-styles` (a JSON file) and the players from a read-only CSV export.
`typesafe_sdk` is imported lazily inside `jev_gate.make_client`, never at import time.

Interpretations of the PREREG (each also listed in SOURCES.md by the CLI):
  * "players_so_far per style and per sizing" is two summaries, by style and by sizing, of each player's total settled
    F$ P&L over rounds < r (players, mean, min, max), not a style x sizing cross table (17 players would leave most
    cells empty). A player's style and sizing in a round are those of that round's rows in the export.
  * A style with no series value in a round counts 0 in the accounting and is tallied as `missing`.
  * B2 starts on B1 and switches before round r to the style with the most 2026 P&L over rounds < r when that beats
    the current style's by more than SWITCH_MARGIN (scripts/probes/walk_forward.py); ties keep ALPHA_ORDER.
  * "rounds raced so far" = calendar rounds before r.
  * Jev's F$ placement needs Jev's own rows in the demo database (season_demo --picks, the owner's step); until then
    it is reported as pending.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from racinglines.pipelines import profiles as PF
from racinglines.research.jev_desk import boot_mean
from racinglines.research.jev_gate import DEFAULT_MODEL, make_client

YEAR = 2026
PREV = 2025
CODES = tuple(PF.ALPHA_ORDER)
SIZING_OPTIONS = ("standard", "kelly_0.25", "kelly_0.5")
SIZING_KELLY = {"standard": None, "kelly_0.25": 0.25, "kelly_0.5": 0.5}
PKG_CAP = 6_000
MIN_CANARY_LEN = 6
SWITCH_MARGIN = 100.0                     # pipelines/story.SWITCH_MARGIN (checked in tests)
N_BOOT = 5000
GRANT = 1000.0                            # the F$ signup grant the card's return is on (web/strategy_pick)
CACHE_DIR = Path("data/runs/jev_player/cache")
OUT_DIR = Path("reports/2026-10-15-jev-player")
SELF_REPORT = "a pre-registered self-report, not Jev's reasoning"
CAVEAT = ("the five styles were chosen with 2026 in view, so rounds 1-17 prove the mechanism and placement, not "
          "out-of-sample skill; rounds 18-23 are the clean test.")
BASELINES = ("B1", "B2", "B3")
BASELINE_NAMES = {"B1": "B1 best 2025 card", "B2": "B2 trailing best ($100 margin)", "B3": "B3 equal weight",
                  "H1": "hindsight best each round", "H2": "hindsight best season"}

# ---------------------------------------------------------------- the questions (fixed by the PREREG)

STATE_FIELDS = (
    "The state fields are: `event`, the coming race weekend (name, round, race date, format, rounds already raced "
    "this season); `cards`, the five strategy styles as the player sees them (code, label, description, backtest "
    "total in dollars and as a return on the F$1,000 grant, whether it was tuned on the seasons it is scored on, "
    "mode and settings in words); `season_2026_so_far`, each style's weekly P&L in dollars at its default sizing for "
    "the rounds already raced this season, with summaries; `players_so_far`, the fantasy players' settled F$ P&L so "
    "far this season, summarised by style and by sizing; `notes`, what each package holds and any cut.")
STYLE_TEXT = ("A fantasy player's account trades Formula 1 prediction markets in fantasy dollars (F$) by following one "
              "strategy style for each race weekend. Choose the style this account follows for the coming weekend "
              "in `event`. " + STATE_FIELDS)
SIZING_TEXT = ("For the same account and weekend, choose how its stakes are sized: standard sizing (stakes scale with "
               "the account's F$), or a Kelly fraction of 0.25 or 0.5. " + STATE_FIELDS)
BASIS_TEXT = {
    "basis_2026": "For the coming weekend in `event`: is the best choice of style the style with the strongest 2026 "
                  "record so far?",
    "basis_2025": "For the coming weekend in `event`: is the best choice of style the style with the strongest 2025 "
                  "backtest total on its card?",
    "basis_players": "For the coming weekend in `event`: is the best choice of style the style with the best "
                     "real-player F$ results so far?",
    "basis_steady": "For the coming weekend in `event`: is the best choice of style the style with the steadiest "
                    "record so far (fewest losing weekends, smallest drawdown)?",
}
BASIS_WORDS = {"basis_2026": "the 2026 record", "basis_2025": "the 2025 backtest", "basis_players": "the players' results",
               "basis_steady": "steadiness"}
SIZING_WORDS = {"standard": "standard sizing", "kelly_0.25": "a quarter Kelly (0.25)", "kelly_0.5": "a half Kelly (0.5)"}


def questions():
    qs = {"style": {"type": "choice", "instructions": STYLE_TEXT,
                    "criteria": {c: f"style {c} ({PF.ALPHA_STYLES[c]['label']})" for c in CODES}},
          "sizing": {"type": "choice", "instructions": SIZING_TEXT,
                     "criteria": {o: SIZING_WORDS[o] for o in SIZING_OPTIONS}}}
    for k, t in BASIS_TEXT.items():
        qs[k] = {"type": "noul", "instructions": t + " " + STATE_FIELDS,
                 "criteria": {"true": "Yes, that is the best basis for this weekend's choice.",
                              "false": "No, it is not."}}
    return qs


# ---------------------------------------------------------------- loading (files only)

def load_styles(path):
    """{code: {round: dict(pnl, ...)}} and meta from a season_demo --export-styles file (or the stand-in)."""
    d = json.loads(Path(path).read_text())
    styles = d.get("styles", d)
    out = {c: {int(r): dict(v) for r, v in (styles.get(c) or {}).items()} for c in CODES}
    return out, d.get("meta", {})


def load_players(path):
    """[dict(user_id, round, style, sizing, pnl, settled)] from the read-only players export (no handles)."""
    rows = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            rows.append(dict(user_id=int(r["user_id"]), round=int(r["round"]), style=r["style"], sizing=r["sizing"],
                             pnl=float(r["pnl"]), settled=int(r.get("settled") or 0)))
    return rows


def calendar_from_styles(styles):
    """{round: dict(name, format, date)} from the export's per-round metadata (calendar facts only)."""
    cal = {}
    for c in CODES:
        for r, v in styles.get(c, {}).items():
            cal.setdefault(r, dict(name=v.get("name"), format=v.get("format"),
                                   date=str(v.get("race_start") or "")[:10] or None))
    return cal


# ---------------------------------------------------------------- the copied snapshot and the packages

def snapshot(styles, players, calendar, rnd, exclude_users=()):
    """Copied data for round `rnd`: style P&L and player rows for rounds < rnd only, the calendar's non-outcome fields.
    Nothing at round >= rnd is copied, so nothing downstream can read it."""
    return {"round": rnd,
            "event": copy.deepcopy(calendar.get(rnd) or {}),
            "raced": sorted(r for r in calendar if r < rnd),
            "series": {c: {r: float(v["pnl"]) for r, v in styles.get(c, {}).items() if r < rnd and v.get("pnl") is not None}
                       for c in CODES},
            "players": [dict(p) for p in players if p["round"] < rnd and p["user_id"] not in set(exclude_users)]}


def _r2(x):
    return None if x is None else round(float(x), 2)


def summary(vals):
    """Weekly dollars in time order -> total, weeks up, total without the best two weeks, worst drawdown, last four."""
    if not vals:
        return dict(total=0.0, weeks=0, weeks_up=0, total_without_best_two=0.0, worst_drawdown=0.0, last_four=[])
    best2 = sorted(range(len(vals)), key=lambda i: (-vals[i], i))[:2]
    peak = cum = dd = 0.0
    for v in vals:
        cum += v
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dict(total=_r2(sum(vals)), weeks=len(vals), weeks_up=sum(v > 0 for v in vals),
                total_without_best_two=_r2(sum(v for i, v in enumerate(vals) if i not in best2)),
                worst_drawdown=_r2(dd), last_four=[_r2(v) for v in vals[-4:]])


def settings_words(code):
    p = PF.PROFILES[code]
    parts = [f"mode {p['strategy']}"]
    for k in sorted(p["settings"]):
        v = p["settings"][k]
        v = ", ".join(v) if isinstance(v, (list, tuple)) else v
        parts.append(f"{k.replace('_', ' ')} {v}")
    return "; ".join(parts)


def _cap(records, notes, name):
    cut = 0
    while records and len(json.dumps(records)) > PKG_CAP:
        records.pop()
        cut += 1
    if cut:
        notes[f"{name}_cut"] = f"{cut} tail records cut to the {PKG_CAP:,}-character cap"
    return records


def packages(snap, live=False):
    """The state for one request, from a snapshot only."""
    rnd, notes = snap["round"], {}
    ev = snap["event"]
    event = {"name": ev.get("name"), "round": rnd, "date": ev.get("date"), "format": ev.get("format"),
             "rounds_raced": len(snap["raced"])}
    cards = []
    for c in CODES:
        st = PF.ALPHA_STYLES[c]
        card = {"code": c, "label": st["label"], "description": st["blurb"],
                "backtest_2025_dollars": st["backtest"][1],
                "backtest_2025_return_on_grant_pct": round(100.0 * st["backtest"][1] / GRANT, 1),
                "tuned_on_scored_seasons": bool(st.get("in_sample")), "mode_and_settings": settings_words(c)}
        if live:
            card["backtest_2026_dollars"] = st["backtest"][0]
            card["backtest_2026_return_on_grant_pct"] = round(100.0 * st["backtest"][0] / GRANT, 1)
        cards.append(card)
    cards = _cap(cards, notes, "cards")
    season = []
    for c in CODES:
        s = snap["series"][c]
        weeks = [[r, _r2(s[r])] for r in sorted(s)]
        rec = {"code": c, "weekly_pnl": weeks, **summary([s[r] for r in sorted(s)])}
        if not s:
            rec["note"] = "no 2026 weekend yet" if not snap["raced"] else "no series for this style"
        season.append(rec)
    season = _cap(season, notes, "season_2026_so_far")
    players = {"by_style": _cap(_group(snap["players"], "style", CODES), notes, "players_by_style"),
               "by_sizing": _cap(_group(snap["players"], "sizing", ("standard", "kelly 0.25", "kelly 0.5")), notes,
                                 "players_by_sizing"),
               "player_weeks": len(snap["players"])}
    notes.update({
        "cards": "the 2025 backtest is the card's own number, fixed before 2026" +
                 ("; the 2026 card total is shown from round 18 on" if live else "; the card's 2026 total is not shown"),
        "season_2026_so_far": "weekly P&L in dollars at each style's default sizing, rounds before this one",
        "players_so_far": "each player's total settled F$ P&L over rounds before this one: players, mean, min, max",
        "size_cap_chars": PKG_CAP})
    return {"event": event, "cards": cards, "season_2026_so_far": season, "players_so_far": players, "notes": notes}


def _group(rows, key, order):
    tot = {}
    for p in rows:
        tot.setdefault(p[key], {}).setdefault(p["user_id"], 0.0)
        tot[p[key]][p["user_id"]] += p["pnl"]
    out = []
    for g in order:
        v = list(tot.get(g, {}).values())
        out.append({key: g, "players": len(v), "mean": _r2(sum(v) / len(v)) if v else None,
                    "min": _r2(min(v)) if v else None, "max": _r2(max(v)) if v else None})
    return out


def state_for(styles, players, calendar, rnd, exclude_users=(), live=False):
    return packages(snapshot(styles, players, calendar, rnd, exclude_users), live=live)


# ---------------------------------------------------------------- leak guards

def canaries(styles, players, rnd):
    """Strings that must not appear in a round's state: every future raw value as repr, plus its 2-decimal and _r2
    forms and the per-style / per-sizing aggregates a future-inclusive sum, mean, min or max would produce. A rounded
    form that the state legitimately shows (a past value or past aggregate that happens to match) is not a canary."""
    raw, future, legit = set(), set(), set()

    def forms(v, into):
        if isinstance(v, (int, float)) and math.isfinite(v):
            into.update(t for t in (f"{v:.2f}", f"{_r2(v)}") if len(t) >= 4)

    def aggregates(upto, into):
        for c in CODES:
            full = [v["pnl"] for r, v in sorted(styles.get(c, {}).items()) if r < upto and v.get("pnl") is not None]
            sm = summary(full)
            for k in ("total", "total_without_best_two", "worst_drawdown"):
                forms(sm[k], into)
            for v in sm["last_four"]:
                forms(v, into)
        rows = [p for p in players if p["round"] < upto]
        for key, order in (("style", CODES), ("sizing", ("standard", "kelly 0.25", "kelly 0.5"))):
            for g in _group(rows, key, order):
                for k in ("mean", "min", "max"):
                    forms(g[k], into)

    for c in CODES:
        for r, v in styles.get(c, {}).items():
            for k in ("pnl", "bought"):
                x = v.get(k)
                if r >= rnd:
                    if isinstance(x, (int, float)) and math.isfinite(x) and len(repr(float(x))) >= MIN_CANARY_LEN:
                        raw.add(repr(float(x)))
                    forms(x, future)
                elif k == "pnl":
                    forms(x, legit)
    for p in players:
        x = p["pnl"]
        if p["round"] >= rnd:
            if isinstance(x, (int, float)) and math.isfinite(x) and len(repr(float(x))) >= MIN_CANARY_LEN:
                raw.add(repr(float(x)))
            forms(x, future)
        else:
            forms(x, legit)
    aggregates(float("inf"), future)        # what a future-inclusive sum / mean / min / max would produce
    aggregates(rnd, legit)                  # what the state legitimately shows
    return raw | (future - legit)


def guard(state, cans):
    blob = json.dumps(state, default=str)
    for c in cans:                 # a whole number, not a fragment of a longer one (-6.9 is not inside -16.95)
        if re.search(r"(?<![\d.\-])" + re.escape(c) + r"(?![\d])", blob):
            raise RuntimeError(f"leak guard: canary {c!r} found in the request state")


def request_blob(state, model=DEFAULT_MODEL):
    return json.dumps({"state": state, "questions": questions(), "model": model}, sort_keys=True, default=str)


def state_hash(state, model=DEFAULT_MODEL):
    return hashlib.sha256(request_blob(state, model).encode()).hexdigest()


# ---------------------------------------------------------------- the TypeSafe call (cached)

def _cache_path(state, model, cache_dir):
    return Path(cache_dir) / f"{state_hash(state, model)}.json"


def cached_answer(state, model=DEFAULT_MODEL, cache_dir=CACHE_DIR):
    p = _cache_path(state, model, cache_dir)
    if p.exists():
        rec = json.loads(p.read_text())
        rec["cached"] = True
        return rec
    return None


def ask(state, client=None, model=DEFAULT_MODEL, cache_dir=CACHE_DIR):
    """All six answers for a round's state, from disk cache when state, questions and model are unchanged."""
    hit = cached_answer(state, model, cache_dir)
    if hit is not None:
        return hit
    client = client or make_client()
    resp = client.system_one(state=state, questions=questions(), model=model)
    rec = {"model": model, "answered_by": getattr(resp, "model", None)}
    for k in ("style", "sizing"):
        a = resp.choices[k]
        rec[k] = {"choice": a.choice, "confidence": getattr(a, "confidence", None),
                  "probabilities": dict(a.probabilities)}
    rec["basis"] = {k: float(resp.nouls[k].noul) for k in BASIS_TEXT}
    u = getattr(resp, "usage", None)
    rec["usage"] = {"input_tokens": getattr(u, "input_tokens", 0), "output_tokens": getattr(u, "output_tokens", 0)} if u else None
    p = _cache_path(state, model, cache_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, sort_keys=True, indent=1, default=str))
    rec["cached"] = False
    return rec


class MissingCache(Exception):
    pass


def cache_only_ask(model=DEFAULT_MODEL, cache_dir=CACHE_DIR):
    def _ask(state):
        hit = cached_answer(state, model, cache_dir)
        if hit is None:
            raise MissingCache
        return hit
    return _ask


def stand_in_ask(state):
    """A deterministic stand-in decider for --dry-run (no client, no network): probabilities from the state's hash.
    Its picks mean nothing and are written under dry-run/ only."""
    h = hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).digest()

    def probs(opts, off):
        w = [h[off + i] + 1 for i in range(len(opts))]
        return {o: x / sum(w) for o, x in zip(opts, w)}
    return {"model": "STAND-IN", "answered_by": "STAND-IN", "cached": None, "usage": None,
            "style": {"choice": None, "probabilities": probs(CODES, 0)},
            "sizing": {"choice": None, "probabilities": probs(SIZING_OPTIONS, 8)},
            "basis": {k: round(h[16 + i] / 255, 4) for i, k in enumerate(BASIS_TEXT)}}


# ---------------------------------------------------------------- the pick and the note

def argmax(options, probs, choice=None):
    """Highest probability, ties to the earlier option; `choice` when no probabilities came back."""
    if not probs:
        if choice not in options:
            raise ValueError(f"answer {choice!r} is not one of the options")
        return choice
    best, bp = None, -1.0
    for o in options:
        p = float(probs.get(o, 0.0))
        if p > bp:
            best, bp = o, p
    return best


def decide(rec):
    """The pick from an answer record: argmax of `style` and of `sizing` only (the basis answers are never read)."""
    sp = rec["style"].get("probabilities") or {}
    code = argmax(CODES, sp, rec["style"].get("choice"))
    rest = [c for c in CODES if c != code]
    runner = argmax(rest, {c: sp[c] for c in rest if c in sp}) if sp else None
    zp = rec["sizing"].get("probabilities") or {}
    sizing = argmax(SIZING_OPTIONS, zp, rec["sizing"].get("choice"))
    k = SIZING_KELLY[sizing]
    return {"code": code, "label": PF.ALPHA_STYLES[code]["label"], "sizing": "standard" if k is None else "kelly",
            "kelly": k, "sizing_option": sizing, "p_style": _p(sp.get(code)), "runner_up": runner,
            "p_runner_up": _p(sp.get(runner)) if runner else None, "p_sizing": _p(zp.get(sizing))}


def _p(x):
    return None if x is None else round(float(x), 2)


def _pp(x):
    return "n/a" if x is None else f"{x:.2f}"


def note(pick, basis, state):
    """The per-decision note: a fixed template over the pick, the basis probabilities and the evidence Jev saw."""
    b = sorted(basis.items(), key=lambda kv: (-kv[1], list(BASIS_TEXT).index(kv[0])))
    words = f"leans on {BASIS_WORDS[b[0][0]]} ({b[0][1]:.2f})" + "".join(
        f"{' more than' if i == 1 else ','} {BASIS_WORDS[k]} ({v:.2f})" for i, (k, v) in enumerate(b[1:], 1))
    s = next(x for x in state["season_2026_so_far"] if x["code"] == pick["code"])
    pl = next((x for x in state["players_so_far"]["by_style"] if x["style"] == pick["code"]), None)
    pm = "none yet" if not pl or pl["mean"] is None else f"F${pl['mean']:+,.2f} over {pl['players']} players"
    ru = f"; runner-up {pick['runner_up']} ({_pp(pick['p_runner_up'])})" if pick.get("runner_up") else ""
    return (f"[{SELF_REPORT}] picked {pick['code']} {pick['label']} ({_pp(pick['p_style'])}){ru}; sizing "
            f"{SIZING_WORDS[pick['sizing_option']]} ({_pp(pick['p_sizing'])}); {words}. Evidence for {pick['code']}: "
            f"2026 to date ${s['total']:+,.2f}, {s['weeks_up']} of {s['weeks']} weeks up; players' mean {pm}.")


# ---------------------------------------------------------------- the round loop

def run(styles, players, calendar, rounds, ask_fn, exclude_users=(), live=False):
    """One request per round. -> (picks {round: pick+note+basis}, transcript [dict])"""
    picks, transcript = {}, []
    for r in rounds:
        state = state_for(styles, players, calendar, r, exclude_users, live)
        guard(state, canaries(styles, players, r))
        rec = ask_fn(state)
        pick = decide(rec)
        pick["basis"] = {k: round(float(v), 4) for k, v in rec["basis"].items()}
        pick["note"] = note(pick, rec["basis"], state)
        picks[r] = pick
        transcript.append({"round": r, "state_hash": state_hash(state), "state_chars": len(json.dumps(state)),
                           "style": rec["style"], "sizing": rec["sizing"], "basis": rec["basis"], "pick": pick,
                           "usage": rec.get("usage"), "answered_by": rec.get("answered_by"), "cached": rec.get("cached")})
    return picks, transcript


def plan(styles, players, calendar, rounds, model=DEFAULT_MODEL, cache_dir=CACHE_DIR, exclude_users=()):
    hashes = [state_hash(state_for(styles, players, calendar, r, exclude_users), model) for r in rounds]
    cached = sum((Path(cache_dir) / f"{h}.json").exists() for h in set(hashes))
    return {"rounds": len(rounds), "requests": len(rounds), "unique_states": len(set(hashes)), "cached": cached,
            "api_calls": len(set(hashes)) - cached, "questions_per_request": len(questions())}


def picks_file(picks, meta):
    return {"meta": meta, "self_report": SELF_REPORT,
            "rounds": {str(r): {k: p[k] for k in ("code", "label", "sizing", "kelly", "p_style", "runner_up",
                                                   "p_runner_up", "p_sizing", "basis", "note")}
                       for r, p in sorted(picks.items())}}


# ---------------------------------------------------------------- baselines and analysis

def pnl_of(styles, code, r):
    v = styles.get(code, {}).get(r)
    return None if v is None or v.get("pnl") is None else float(v["pnl"])


def baseline_picks(styles, rounds, margin=SWITCH_MARGIN):
    """{B1, B2, H1, H2: {round: code}} (B3 is the equal-weight mean, see weekly)."""
    b1 = max(CODES, key=lambda c: (PF.ALPHA_STYLES[c]["backtest"][1], -CODES.index(c)))
    out = {"B1": {r: b1 for r in rounds}}
    cur, b2 = b1, {}
    for i, r in enumerate(rounds):
        if i:
            so_far = {c: sum(pnl_of(styles, c, x) or 0.0 for x in rounds[:i]) for c in CODES}
            best = max(CODES, key=lambda c: (so_far[c], -CODES.index(c)))
            if so_far[best] > so_far[cur] + margin:
                cur = best
        b2[r] = cur
    out["B2"] = b2
    out["H1"] = {r: max(CODES, key=lambda c: ((pnl_of(styles, c, r) if pnl_of(styles, c, r) is not None else -math.inf),
                                               -CODES.index(c))) for r in rounds}
    tot = {c: sum(pnl_of(styles, c, r) or 0.0 for r in rounds) for c in CODES}
    h2 = max(CODES, key=lambda c: (tot[c], -CODES.index(c)))
    out["H2"] = {r: h2 for r in rounds}
    return out


def weekly(styles, choice, rounds):
    """[pnl] per round for a {round: code} choice; missing values count 0."""
    return [pnl_of(styles, choice[r], r) or 0.0 for r in rounds]


def equal_weight(styles, rounds):
    return [sum(pnl_of(styles, c, r) or 0.0 for c in CODES) / len(CODES) for r in rounds]


def _desc(vals):
    s = summary(vals)
    return dict(total=s["total"], weeks_up=s["weeks_up"], weeks=s["weeks"], ex_best_two=s["total_without_best_two"],
                worst_drawdown=s["worst_drawdown"])


def placement(players, jev_user_id=None, rounds=None):
    """Totals per player over `rounds`; Jev's rank (1 = best) among them when its user id is in the export."""
    tot = {}
    for p in players:
        if rounds is None or p["round"] in rounds:
            tot[p["user_id"]] = tot.get(p["user_id"], 0.0) + p["pnl"]
    if jev_user_id is None or jev_user_id not in tot:
        return {"players": len(tot), "rank": None, "status": "pending: Jev's rows are not in the demo database yet",
                "totals": sorted((round(v, 2) for v in tot.values()), reverse=True)}
    j = tot[jev_user_id]
    others = [v for u, v in tot.items() if u != jev_user_id]
    return {"players": len(others), "rank": 1 + sum(v > j for v in others), "of": len(others) + 1, "jev": round(j, 2),
            "status": "ranked", "totals": sorted((round(v, 2) for v in others), reverse=True)}


def analyse(styles, picks, rounds, players=(), jev_user_id=None, transcript=(), n_boot=N_BOOT):
    rounds = list(rounds)
    jev_choice = {r: picks[r]["code"] for r in rounds}
    jev = weekly(styles, jev_choice, rounds)
    bp = baseline_picks(styles, rounds)
    base = {"B1": weekly(styles, bp["B1"], rounds), "B2": weekly(styles, bp["B2"], rounds),
            "B3": equal_weight(styles, rounds), "H1": weekly(styles, bp["H1"], rounds),
            "H2": weekly(styles, bp["H2"], rounds)}
    res = {"rounds": rounds, "jev": jev, "base": base, "baseline_picks": bp, "picks": picks, "diff": {}, "beats": {},
           "missing": sum(pnl_of(styles, jev_choice[r], r) is None for r in rounds)}
    for k in BASELINES:
        d = [a - b for a, b in zip(jev, base[k])]
        res["diff"][k] = boot_mean(d, n=n_boot)
        lo = res["diff"][k][1][0]
        res["beats"][k] = "YES" if not math.isnan(lo) and lo > 0 else "NOT SHOWN"
    res["desc"] = {"Jev": _desc(jev), **{k: _desc(v) for k, v in base.items()}}
    res["placement"] = placement(list(players), jev_user_id, set(rounds))
    res["totals"] = {"requests": len(transcript), "api_calls": sum(1 for t in transcript if t.get("cached") is False),
                     "cached": sum(1 for t in transcript if t.get("cached")),
                     "input_tokens": sum((t.get("usage") or {}).get("input_tokens", 0) for t in transcript),
                     "output_tokens": sum((t.get("usage") or {}).get("output_tokens", 0) for t in transcript)}
    return res


def _f(x, nd=2):
    return "nan" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{nd}f}"


def format_report(res, label=""):
    L = [f"JEV AS A FANTASY PLAYER: 2026 season demo (reports/2026-10-15-jev-player/PREREG.md v1){label}", "=" * 70,
         f"Caveat: {CAVEAT}", "",
         f"rounds {res['rounds'][0]}-{res['rounds'][-1]} ({len(res['rounds'])}); missing style values counted as 0 for "
         f"Jev: {res['missing']}", "",
         "PRIMARY: Jev weekly P&L minus baseline ($, default sizing), mean over rounds, 95% CI from resampling whole "
         "rounds (5,000, seed 1)"]
    for k in BASELINES:
        m, (lo, hi) = res["diff"][k]
        L.append(f"  Jev - {BASELINE_NAMES[k]:32}{_f(m):>10}  CI ({_f(lo)}, {_f(hi)})")
    L.append("")
    L += [f"beats {k}: {res['beats'][k]}" for k in BASELINES]
    L += ["", "SEASON (descriptive; H1 and H2 are hindsight upper bounds)",
          f"  {'rule':34}{'total':>10}{'weeks up':>10}{'ex best 2':>11}{'worst DD':>10}"]
    for name, d in res["desc"].items():
        lab = name if name == "Jev" else BASELINE_NAMES[name]
        L.append(f"  {lab:34}{_f(d['total']):>10}{d['weeks_up']:>6}/{d['weeks']:<3}{_f(d['ex_best_two']):>11}"
                 f"{_f(d['worst_drawdown']):>10}")
    pl = res["placement"]
    L += ["", "PLACEMENT among the real demo players (F$, settled)"]
    if pl["rank"] is None:
        L.append(f"  {pl['status']} ({pl['players']} players in the export)")
    else:
        L.append(f"  Jev F${pl['jev']:+,.2f}: rank {pl['rank']} of {pl['of']}")
    L += ["", f"ROUND BY ROUND (each note is {SELF_REPORT})"]
    bp = res["baseline_picks"]
    for i, r in enumerate(res["rounds"]):
        p = res["picks"][r]
        L.append(f"  rnd {r:>2}  Jev {p['code']:3} {p['sizing']:8} {'' if p['kelly'] is None else p['kelly']:<5}"
                 f" pnl {_f(res['jev'][i]):>9}   B1 {bp['B1'][r]} B2 {bp['B2'][r]} H1 {bp['H1'][r]}")
        L.append(f"          note: {p['note']}")
    t = res["totals"]
    L += ["", f"requests {t['requests']} (API {t['api_calls']}, cached {t['cached']}); tokens in {t['input_tokens']:,} "
              f"out {t['output_tokens']:,}", "", "Not shown by this design:",
          f"  Out-of-sample skill on rounds 1-17: {CAVEAT}",
          "  Whether the sizing choice helps: the decision rule is sizing-neutral; sizing shows only in F$ placement.",
          "  Markets, prices, news: Jev sees style records and player results only."]
    return "\n".join(L)


# ---------------------------------------------------------------- live: deadline and the lock file

def check_deadline(now, race_start, fp1, lead_days=4, tail_hours=24):
    """Refuse (ValueError) inside the weekend lock window (race start - 4 days ... race + 24 h) or after FP1.
    Times are naive UTC (or aware, converted)."""
    import pandas as pd
    n, rs, f = (pd.Timestamp(x) for x in (now, race_start, fp1))
    n, rs, f = (t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t for t in (n, rs, f))
    lo, hi = rs - pd.Timedelta(days=lead_days), rs + pd.Timedelta(hours=tail_hours)
    if lo <= n <= hi:
        raise ValueError(f"too late to lock: {n} is inside the weekend lock window ({lo} to {hi} UTC)")
    if n >= f:
        raise ValueError(f"too late to lock: {n} is after FP1 ({f} UTC)")


def _set(text, key, value):
    pat = re.compile(rf'^({re.escape(key)}\s*=\s*)("[^"]*"|\[[^\]]*\]|[-0-9.]+)', re.M)
    if not pat.search(text):
        raise ValueError(f"template has no {key!r} line")
    return pat.sub(lambda m: m.group(1) + value, text, count=1)


def lock_text(template, *, year, rnd, name, first_session_utc, code, settings_key, code_commit, bankroll, stake_rule,
              note_text, locked_at_utc):
    """paper/locks/<year>-<round>.toml text from TEMPLATE.toml: header and [strategy] filled, [[line]] left empty."""
    q = lambda s: json.dumps(str(s))                  # noqa: E731 — a TOML basic string
    t = template
    for key, val in (("event", q(f"{year}-{rnd}")), ("name", q(name)), ("first_session_utc", q(first_session_utc)),
                     ("locked_at_utc", q(locked_at_utc)), ("locked_by", q("jev")), ("profile", q(code)),
                     ("settings_key", q(settings_key)), ("code_commit", q(code_commit)),
                     ("venues", '["polymarket"]'), ("bankroll", f"{float(bankroll):.2f}"),
                     ("stake_rule", q(stake_rule))):
        t = _set(t, key, val)
    one_line = " ".join(str(note_text).split())
    head = re.compile(r"^\[strategy\][^\n]*\n", re.M)
    if not head.search(t):
        raise ValueError("template has no [strategy] table")
    return head.sub(lambda m: m.group(0) + f"# note: {one_line}\n", t, count=1)


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)
