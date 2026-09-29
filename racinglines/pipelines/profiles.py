"""
Strategy profiles: a Lab candidate (model x strategy x settings) assigned to a user, whose live paper
signals the signal engine computes (racinglines/pipelines/signals.py).

The two recommended by the params-4h cloud search (data/runs/search/params-4h/REPORT.md, section 4):

    A  core taker: the update taker on gridq+pretrain+reset, edges of 10 pts or more (5 on head-to-head),
       no pre-weekend stage.                                                    (candidate #09 + min_edge_h2h)
    C  maker sleeve: the conservative maker on gbm, 25-share quotes, out of markets where the model
       disagrees with the price by more than 5 pts.                              (candidate #24)

    K  Kalshi maker: the conservative maker tuned on Kalshi's own 2025-26 tape (docs/kalshi-history.md,
       sweeps/kalshi-maker-k.toml); the settings below are the sweep's winner under the params-4h
       held-out rule. The candidate carries venue = "kalshi": it is judged on and quotes Kalshi.

    racinglines f1 profiles                      # list, and create A / C / K as Lab candidates if missing
    racinglines f1 profiles --assign-demo        # demo taker -> A, demo maker -> C
    racinglines f1 profiles --assign-demo --venue kalshi   # demo maker -> K, as its Kalshi profile (explicit;
                                                           # nothing reads it until the signal engine runs Kalshi)

A user's profile lives in users.prefs["strategy_profile"] with the full settings, so deleting the
candidate doesn't break the assignment. A Kalshi profile lives beside it in prefs["strategy_profile_kalshi"]
(PREF_KALSHI), so the Polymarket profile and everything reading it are untouched.
"""

import json

from sqlalchemy import text

from racinglines.pipelines import sweep_settings as SS

LIVE_STAGES = ["after FP1", "after FP2", "after FP3", "after SQ", "after Sprint", "after Quali"]
K_SETTINGS = {"variant": "gbm", "half_spread": 0.03, "max_disagree": 0.10, "size": 25}
K_WHY = ("kalshi-maker-k search, conservative maker on Kalshi's tape with its maker fee. Robust in both seasons "
         "(held-out rule, maker noise floor 350): 2026 +450 (Sharpe 0.61, max DD 316; +1,321 vs Kalshi baseline, "
         "+569 vs C on Kalshi), 2025 +707 (1.16, 358; +1,103 vs baseline, +23 vs C). Partial grid: gbm fully, "
         "gridq+pretrain 2026 only.")
PROFILES = {
    "A": dict(name="A · core taker (update)", strategy="update",
              settings={"variant": "gridq+pretrain+reset", "min_edge": 0.10, "min_edge_h2h": 0.05,
                        "taker_stages": LIVE_STAGES},
              why="params-4h #09 + head-to-head at 5 pts. Robust in both seasons: 2026 +1,232 (Sharpe 1.53, "
                  "max DD 249), 2025 +1,237 (1.35, 306), both without the h2h change; noise range "
                  "+1,270 ± 67 / +1,020 ± 149."),
    "C": dict(name="C · maker sleeve (gbm)", strategy="maker",
              settings={"variant": "gbm", "max_disagree": 0.05, "size": 25},
              why="params-4h #24. Profitable in both seasons with the smallest drawdowns: 2026 +653 "
                  "(Sharpe 1.78, max DD 279), 2025 +835 (1.63, 176); noise range +717 ± 72 / +881 ± 63."),
    "K": dict(name="K · Kalshi maker", strategy="maker", venue="kalshi",
              settings=K_SETTINGS,
              why=K_WHY),
}
DEMO = {"taker": "A", "maker": "C"}
DEMO_KALSHI = {"maker": "K"}        # the demo maker's Kalshi profile, assigned only by --assign-demo --venue kalshi
DEMO_FOLLOW = {"taker": 0.33}      # share of recommendations the demo taker follows (code only, not in the UI)
DEMO_BANKROLL = {"maker": 10_000.0, "taker": 1_000.0}   # starting bankroll ($), from BANKROLL_SINCE
BANKROLL_SINCE = "2025-01-01"
# the demo maker's saved Edge Finder: the setups it ran, newest first (M1 = the baseline maker, also the benchmark)
DEMO_EDGE_FINDER = {"maker": [("C", "maker"), ("M3", "maker"), ("M2", "maker"), ("M1", "maker")]}
DEMO_EDGE_YEAR = 2026
PREF = "strategy_profile"
PREF_KALSHI = "strategy_profile_kalshi"


def pref(venue="polymarket"):
    """The users.prefs key a venue's profile lives under (Polymarket: the profile as before)."""
    return PREF if venue == "polymarket" else f"{PREF}_{venue}"

# The demo accounts' track record (pipelines/demo_history.py): backtest replays of real weekends, shown as
# what each account ran. The taker has always followed A. The maker tried three setups in 2025, moving
# toward the model and filter that held up, and has run C since the first race of 2026.
HISTORY_PROFILES = {
    "M1": dict(name="M1 · launch maker (baseline)", strategy="maker", settings={"variant": "baseline"},
               why="2025 rounds 1-8: no market history yet, so the defaults: the conservative maker on the "
                   "baseline model."),
    "M2": dict(name="M2 · grid-aware maker, 10-pt filter", strategy="maker",
               settings={"variant": "gridq+pretrain", "max_disagree": 0.10},
               why="2025 rounds 9-16: the Edge Finder's P&L leader over the season's first 7 weekends "
                   "(+$697): the grid-aware model, out of markets 10+ pts from the model."),
    "M3": dict(name="M3 · gbm maker, tight filter", strategy="maker",
               settings={"variant": "gbm", "max_disagree": 0.07},
               why="2025 rounds 17-24: the Edge Finder's P&L leader over 15 weekends (+$1,134): the "
                   "gradient-boosted model, quoting only where it agrees with the market within 7 pts."),
}
HISTORY = {   # username -> [(profile code, year, first round, last round)]
    "maker": [("M1", 2025, 1, 8), ("M2", 2025, 9, 16), ("M3", 2025, 17, 24), ("C", 2026, 1, 99)],
    "taker": [("A", 2025, 1, 99), ("A", 2026, 1, 99)],
}


def _candidates(conn):
    return conn.execute(text("""SELECT id, params FROM model_runs WHERE kind = 'candidate' ORDER BY id""")).all()


def ensure_candidates(conn, history=False):
    """Create A, C and K (and with history, M1-M3) as Lab candidates unless a candidate of the same name
    exists. {code: candidate id}."""
    from racinglines.pipelines.search import add_candidate
    have = {p.get("name"): i for i, p in _candidates(conn)}
    out = {}
    for code, pr in {**PROFILES, **(HISTORY_PROFILES if history else {})}.items():
        year, source = (2025, "demo-history") if code in HISTORY_PROFILES else \
            (2026, "kalshi-maker-k" if code == "K" else "params-4h")
        out[code] = have.get(pr["name"]) or add_candidate(
            conn, pr["name"], SS.Settings.from_dict(pr["settings"]), year, pr["strategy"], why=pr["why"],
            source=source, venue=pr.get("venue"))
    return out


def load(conn, ref):
    """A profile from a candidate id, a candidate name, or a code (A, C, M1-M3).
    -> dict(candidate_id, name, strategy, settings[, venue]) (venue: a Kalshi candidate's exchange)."""
    ref = str(ref).strip()
    rows = _candidates(conn)
    hit = None
    codes = {**PROFILES, **HISTORY_PROFILES}
    if ref.isdigit():
        hit = next(((i, p) for i, p in rows if i == int(ref)), None)
    else:
        name = codes[ref.upper()]["name"] if ref.upper() in codes else ref
        hit = next(((i, p) for i, p in reversed(rows) if p.get("name") == name), None)
    if hit is None:
        raise ValueError(f"no candidate {ref!r} (racinglines f1 profiles creates A and C)")
    i, p = hit
    return dict(candidate_id=i, name=p["name"], strategy=p["strategy"],
                settings=SS.Settings.from_dict(p["settings"], strict=False).to_json(),
                **({"venue": p["venue"]} if p.get("venue") else {}))


def assign(conn, user_id, profile, venue="polymarket"):
    """Set (profile dict from load) or clear (None) a user's strategy profile; venue="kalshi" sets the
    user's Kalshi profile (pref("kalshi")) and leaves the Polymarket one alone."""
    key = pref(venue)
    conn.execute(text(f"""UPDATE users SET prefs = CASE WHEN CAST(:v AS jsonb) IS NULL
                            THEN coalesce(prefs, '{{}}'::jsonb) - '{key}'
                            ELSE coalesce(prefs, '{{}}'::jsonb) || jsonb_build_object('{key}', CAST(:v AS jsonb)) END
                          WHERE id = :u"""), dict(u=user_id, v=None if profile is None else json.dumps(profile)))


def of_user(conn, user_id, venue="polymarket"):
    p = conn.execute(text(f"SELECT prefs->'{pref(venue)}' FROM users WHERE id = :u"), dict(u=user_id)).scalar()
    return p or None


def assigned(conn, venue="polymarket"):
    """[(user_id, username, role, profile)] for every active user with a profile (on that venue)."""
    key = pref(venue)
    rows = conn.execute(text(f"""SELECT id, username, role, prefs->'{key}' FROM users
                                WHERE active AND prefs ? '{key}' ORDER BY id""")).all()
    return [(i, u, r, p) for i, u, r, p in rows]


def assign_demo(conn, venue="polymarket"):
    """Demo taker -> A, demo maker -> C (their Polymarket profiles, with the demo bankrolls and saved views).
    venue="kalshi": demo maker -> K as its Kalshi profile only; the Polymarket assignments don't move."""
    ids = ensure_candidates(conn)
    done = {}
    if venue != "polymarket":
        for username, code in DEMO_KALSHI.items():
            uid = conn.execute(text("SELECT id FROM users WHERE username = :u"), dict(u=username)).scalar()
            if uid is not None:
                assign(conn, uid, dict(load(conn, ids[code]), venue=venue), venue=venue)
                done[username] = PROFILES[code]["name"]
        return done
    for username, code in DEMO.items():
        uid = conn.execute(text("SELECT id FROM users WHERE username = :u"), dict(u=username)).scalar()
        if uid is not None:
            prof = load(conn, ids[code])
            if username in DEMO_FOLLOW:
                prof["follow_rate"] = DEMO_FOLLOW[username]
            if username in DEMO_BANKROLL:
                prof["bankroll"] = dict(start=DEMO_BANKROLL[username], since=BANKROLL_SINCE)
            assign(conn, uid, prof)
            if username in DEMO_EDGE_FINDER:                      # the account's saved baseline view
                codes = {**PROFILES, **HISTORY_PROFILES}
                refs = []
                for ef_code, strategy in DEMO_EDGE_FINDER[username]:
                    st = SS.Settings.from_dict(codes[ef_code]["settings"])
                    refs.append([st["variant"] if not st.changed().keys() - {"variant"} else "cfg:" + st.key, strategy])
                conn.execute(text("""UPDATE users SET prefs = coalesce(prefs, '{}'::jsonb)
                                        || jsonb_build_object('edge_finder', CAST(:e AS jsonb), 'edge_year', CAST(:y AS int))
                                      WHERE id = :u"""), dict(e=json.dumps(refs), y=DEMO_EDGE_YEAR, u=uid))
            done[username] = PROFILES[code]["name"]
    return done
