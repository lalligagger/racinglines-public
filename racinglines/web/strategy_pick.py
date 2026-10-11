"""
/strategy/pick: an account picks the strategy it paper-trades (owner, 2026-10-11 22:04Z: "no default strategy until they
select one ... defaults + sensible toggles/sliders"). Sign-up assigns none, so until a user picks here nothing trades
for them; this page is the user-facing side of what /admin/users/<id> does (admin.admin_user_profile).

    basic        "Your picks" (roles.basic_profile: its own draw of BASIC_PICKS from the taker shortlist), or none
    pro, admin   the taker shortlist (profiles.TAKER_TOP, ranked), the recommended blend (COMBOS) and maker C (only
                 with profiles.MAKERS_OPEN; off for the Alpha Fantasy Launch), with the few settings worth a slider
                 (TUNABLE) on a single strategy; a blend runs as tuned

One strategy per sport and exchange (`slot`, admin.profile_slots; owner, 2026-10-11 22:30Z: "pointing a strat at a
particular sport"). F1 offers the library above. Another sport has no library strategies of its own yet, so it offers
each taker rule (weekend_sweep.TAKER_MODES) on that sport's default settings, plus the sport's own taker Lab candidates.
Only F1 on Polymarket has a signal timer on the VM today (deploy/vm/systemd/racinglines-signals.service runs
`racinglines strategy signals f1`); the page says so on every other slot.

Saving goes through profiles.assign(…, venue, sport). The demo accounts keep the
profiles assign_demo gives them: they see the page but can't save. The dice (owner, 2026-10-11 22:20Z: "let the user input
RNG'ed values ... high temperature / lots of variation once we have a few dozen users") roll the sliders in the browser
(app.js), as far from the strategy's own settings as the spread allows; a rolled save is marked `rolled` on the profile. Split out of web/app.py, which imports this module.
"""

import time

import pandas as pd
from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from racinglines.pipelines import profiles as PF
from racinglines.pipelines import sweep_settings as SS
from racinglines.web import demo
from racinglines.web import roles as R
from racinglines.web.app import ANY, allow, app, audit, check_csrf, get_engine, render
from racinglines.web.ranges import UI_RANGES

PRO_CODES = PF.open_codes((*PF.TAKER_TOP, "TB", "C"))   # a pro account's F1 list, in order (TAKER_TOP is ranked); no makers while profiles.MAKERS_OPEN is off
DEFAULT = PF.TAKER_TOP[0]                   # preselected when the account runs nothing yet: the shortlist's first
PRE = "pre-weekend"
F1_SLOT = "f1:polymarket"
TIMED_SLOTS = {F1_SLOT}
# The taker rules (weekend_sweep.TAKER_MODES) in words that fit any sport's stages (evaluate.STRATEGIES says F1's).
SPORT_RULES = {"update": ("re-check at every stage", "Takes any price far enough from our fair value, and re-checks at "
                                                     "every pricing stage of the race weekend."),
               "hold": ("enter and hold", "Takes a price once it is far enough from our fair value, then holds it."),
               "last": ("last stage only", "Waits for the last pricing stage before the race, then takes what is "
                                           "far enough from our fair value."),
               "early": ("stage-aware", "Like re-check at every stage, but stops before the late stages.")}                     # slots the VM's signal timer runs (see the docstring)
# The settings a user may move, per kind of strategy: (setting, label, step, unit), in the web forms' capped range
# (web/ranges.py). Probabilities show as points (x100). Anything else stays as the strategy has it.
_T = {"taker": (("min_edge", "Minimum edge to take a price", 0.01, "pts"),
                ("min_edge_h2h", "Minimum edge on head-to-head markets", 0.01, "pts"),
                ("min_volume_24h", "Only markets with this much traded in the last 24 h", 50, "$")),
      "maker": (("max_disagree", "Stop quoting where the model and the market differ by more than", 0.01, "pts"),
                ("size", "Shares per quote", 5, "shares"))}
TUNABLE = {k: tuple((n, label, *UI_RANGES[n], step, unit) for n, label, step, unit in v) for k, v in _T.items()}


_SCHED = {}                                 # year -> (loaded at, schedule): the page reads it, so cache it an hour


def _schedule(year):
    from racinglines.pipelines import weekend_sweep as WS
    hit = _SCHED.get(year)
    if hit is None or time.time() - hit[0] > 3600:
        hit = _SCHED[year] = (time.time(), WS.schedule(year))
    return hit[1]


def open_weekend(now=None):
    """The F1 weekend whose signal window is open at `now` (naive UTC; default now), else None. The signal engine
    replays a weekend's stages so far with the profile's current settings (pipelines/signals.compute), so a change
    inside the window would rewrite that weekend's earlier entries with hindsight: saves wait until it closes
    (Core review, 2026-10-11). Same window as the engine: signals.in_weekend (race start - WEEKEND_LEAD to + WEEKEND_TAIL).
    No schedule (FastF1 unreachable and nothing saved): None, logged; the engine can't run then either."""
    from racinglines.pipelines import signals as SG
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    try:
        _, w = SG.pick_event(_schedule(now.year), now)
    except Exception as ex:                         # noqa: BLE001
        print(f"strategy_pick: no F1 schedule for {now.year}: {ex}", flush=True)
        return None
    return w if w is not None and SG.in_weekend(w, now) else None


def open_window(slot, conn, now=None):
    """The race whose signal window is open at `now` on a slot, else None: F1 open_weekend; another sport its
    sport_signals.window (race day - WEEKEND_LEAD to a day after + WEEKEND_TAIL). -> dict(name, until)."""
    if slot == F1_SLOT or slot.startswith("f1:"):
        from racinglines.pipelines import signals as SG
        w = open_weekend(now)
        return w and dict(w, until=w["race_start"] + SG.WEEKEND_TAIL)
    from racinglines.pipelines import position_replay as P
    from racinglines.pipelines import sport_signals as SPS
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    try:
        sp = P.spec(slot.split(":", 1)[0])
        for r in SPS.races(conn, sp).itertuples():
            a, b = SPS.window(r, sp)
            if a <= now < b:
                return dict(name=r.name, until=b)
    except Exception as ex:                         # noqa: BLE001
        print(f"strategy_pick: no race list for {slot}: {ex}", flush=True)
    return None


def lock_note(w):
    from racinglines.pipelines import signals as SG
    until = w.get("until", w["race_start"] + SG.WEEKEND_TAIL if "race_start" in w else None)
    return (f"Strategy changes are paused during {w['name']}: they open again about a day after the race "
            f"({until:%a %d %b, %H:%M} UTC), so a change never rewrites this weekend's calls.")


def kind(profile):
    from racinglines.pipelines import weekend_sweep as WS
    return "taker" if profile.get("strategy", "update") in WS.TAKER_MODES else "maker"


def settings_cls(sport):
    from racinglines.pipelines import season_sweep as SW
    return SS.Settings if sport == "f1" else SW.settings_class(sport)


def tunables(pr, sport="f1"):
    """The sliders and the pre-weekend toggle (F1 only: its stage) for one strategy (a PROFILES entry, or any dict
    with strategy and settings), at its own values."""
    if PF.is_combo(pr):
        return [], None
    st = settings_cls(sport).from_dict(pr["settings"], strict=False)
    k = kind(pr)
    sl = []
    for name, label, lo, hi, step, unit in TUNABLE[k]:
        v = st[name] if st[name] is not None else st["min_edge"] if name == "min_edge_h2h" else lo
        v = min(max(float(v), lo), hi)
        sl.append(dict(name=name, label=label, lo=lo, hi=hi, step=step, unit=unit, value=v, base=v))
    pre = (PRE in (st["taker_stages"] or ())) if k == "taker" and sport == "f1" else None
    return sl, pre


def slots(user):
    """Where this account may hold a strategy: [dict(sport, venue, key, label, timed)]. Basic: F1 on Polymarket (its
    own draw is an F1 blend); pro and admin: every modeled sport on every exchange that lists it."""
    from racinglines.web.admin import profile_slots
    out = [dict(s, timed=s["key"] in TIMED_SLOTS) for s in profile_slots()]
    return [s for s in out if s["key"] == F1_SLOT] if R.is_basic(user) else out


def sport_strategies(conn, sport, venue):
    """Another sport's choices: each taker rule on the sport's defaults (for this exchange), then its taker Lab
    candidates. {code: dict(name, strategy, settings, why, candidate_id)}."""
    from racinglines.pipelines import weekend_sweep as WS
    from racinglines.web.jobs import sport_name
    cls, label = settings_cls(sport), SPORT_RULES
    base = cls.from_dict({"venue": venue}).to_json()
    out = {f"d-{m}": dict(name=f"{sport_name(sport)}: {label[m][0]}", strategy=m, settings=base, candidate_id=None,
                          why=f"{label[m][1]} On {sport_name(sport)}'s default settings: not tuned for this sport yet, "
                              "and the sport's model is still being validated.")
           for m in WS.TAKER_MODES}
    rows = conn.execute(text("""SELECT id, params FROM model_runs WHERE kind = 'candidate' AND params->>'sport' = :s
                                ORDER BY id DESC LIMIT 20"""), dict(s=sport)).all()
    for cid, p in rows:
        if p.get("strategy") not in WS.TAKER_MODES:
            continue
        try:
            st = cls.from_dict(dict(p.get("settings") or {}, venue=venue)).to_json()
        except ValueError:
            continue
        out[f"c-{cid}"] = dict(name=p.get("name") or f"Lab candidate {cid}", strategy=p["strategy"], settings=st,
                               candidate_id=int(cid), why=(p.get("why") or "") + " (a Lab candidate)")
    return out


def options(user, slot=F1_SLOT, conn=None):
    """The strategies this account may pick on a slot: [dict(code, name, kind, why, sliders, pre)]."""
    if slot != F1_SLOT:
        sport, venue = slot.split(":", 1)
        out = []
        for code, pr in sport_strategies(conn, sport, venue).items():
            sl, pre = tunables(pr, sport)
            out.append(dict(code=code, name=pr["name"], kind="taker", why=pr["why"], sliders=sl, pre=pre, rank=None))
        return out
    if R.is_basic(user):
        return [dict(code="basic", name=R.BASIC_NAME, kind="taker", sliders=[], pre=None,
                     why=f"{R.BASIC_PICKS} taker strategies from our ranked shortlist, drawn for your account and blended "
                         "evenly. You see each pick and how strong it is.")]
    out = []
    for code in PRO_CODES:
        pr = PF.PROFILES[code]
        sl, pre = tunables(pr)
        out.append(dict(code=code, name=pr["name"], kind="taker" if PF.is_combo(pr) else kind(pr), why=pr["why"],
                        sliders=sl, pre=pre, rank=PF.TAKER_TOP.index(code) + 1 if code in PF.TAKER_TOP else None))
    return out


def current_code(profile, opts):
    """The option the account runs now, by name (an adjusted profile keeps its base code), or None."""
    if not profile:
        return None
    return next((o["code"] for o in opts if profile.get("base") == o["code"] or profile.get("name") == o["name"]), None)


@app.get("/strategy/pick", response_class=HTMLResponse, dependencies=[allow(*ANY)])
def pick_page(request: Request, msg: str = "", slot: str = F1_SLOT):
    me = request.state.user
    places = slots(me)
    here = next((x for x in places if x["key"] == slot), places[0])
    sport, venue = here["sport"], here["venue"]
    with get_engine().connect() as c:
        opts = options(me, here["key"], c)
        profile = PF.of_user(c, me["id"], venue, sport)
        running = {x["key"]: (PF.of_user(c, me["id"], x["venue"], x["sport"]) or {}).get("name") for x in places}
        w = open_window(here["key"], c)
    now = current_code(profile, opts)
    for o in opts:                                 # an adjusted profile: its sliders start where the user left them
        if o["code"] == now and profile.get("adjusted"):
            st = settings_cls(sport).from_dict(profile["settings"], strict=False)
            for sl in o["sliders"]:
                if st[sl["name"]] is not None:
                    sl["value"] = min(max(float(st[sl["name"]]), sl["lo"]), sl["hi"])
            if o["pre"] is not None:
                o["pre"] = PRE in (st["taker_stages"] or ())
    default = opts[0]["code"] if R.is_basic(me) or here["key"] != F1_SLOT else DEFAULT
    return render(request, "strategy_pick.html", opts=opts, profile=profile, now=now, chosen=now or default,
                  locked=demo.is_demo(me) or bool(w), demo_locked=demo.is_demo(me), weekend_note=lock_note(w) if w else "",
                  msg=msg, basic=R.is_basic(me), slots=places, slot=here, running=running)


def _adjusted(code, form, base=None, sport="f1"):
    """A strategy's settings (base: a PROFILES entry by default) with the form's sliders and pre-weekend toggle for
    it (fields named "<code>:<setting>"), clamped to TUNABLE; -> (settings, {what moved}), {} when nothing moved."""
    base = base or PF.PROFILES[code]
    st = dict(base["settings"])
    sl, pre = tunables(base, sport)
    moved = {}
    for s in sl:
        raw = form.get(f"{code}:{s['name']}")
        if raw in (None, ""):
            continue
        v = min(max(float(raw), s["lo"]), s["hi"])
        v = round(v / s["step"]) * s["step"]
        v = round(v, 4) if s["unit"] == "pts" else float(v)
        if abs(v - s["value"]) > 1e-9:
            st[s["name"]] = v
            moved[s["name"]] = v
    if pre is not None:
        want = form.get(f"{code}:pre_weekend") == "1"
        if want != pre:
            stages = list(SS.Settings.from_dict(base["settings"], strict=False)["taker_stages"] or SS.STAGES)
            stages = [PRE, *[x for x in stages if x != PRE]] if want else [x for x in stages if x != PRE]
            st["taker_stages"] = [x for x in SS.STAGES if x in stages]
            moved["pre_weekend"] = want
    settings_cls(sport).from_dict(st)                  # strict: a value the engine wouldn't take fails here, not later
    return st, moved


@app.post("/strategy/pick", dependencies=[Depends(check_csrf), allow(*ANY)])
async def pick_save(request: Request, code: str = Form(""), rolled: str = Form(""), slot: str = Form(F1_SLOT)):
    me = request.state.user
    back = "/strategy/pick?" + (f"slot={slot}&" if slot != F1_SLOT else "") + "msg="
    if demo.is_demo(me):
        return RedirectResponse(back + "The demo accounts keep their strategy.", status_code=303)
    here = next((x for x in slots(me) if x["key"] == slot), None)
    if here is None:
        return RedirectResponse("/strategy/pick?msg=Error: pick one of the sports listed.", status_code=303)
    sport, venue = here["sport"], here["venue"]
    with get_engine().connect() as c:
        w = open_window(slot, c)
    if w is not None:                               # a pick, a slider, a dice roll or a stop: all wait for the window
        return RedirectResponse(back + "Error: " + lock_note(w), status_code=303)
    form = await request.form()
    with get_engine().begin() as c:
        allowed = {o["code"] for o in options(me, slot, c)}
        old = PF.of_user(c, me["id"], venue, sport)
        if code == "none":
            new = None
        elif code not in allowed:
            return RedirectResponse(back + "Error: pick one of the strategies listed.", status_code=303)
        elif slot != F1_SLOT:                       # another sport: a taker rule or a candidate on its own settings
            pr = sport_strategies(c, sport, venue)[code]
            settings, moved = _adjusted(code, form, pr, sport)
            new = dict(candidate_id=pr["candidate_id"], name=pr["name"], strategy=pr["strategy"], venue=venue,
                       settings=settings_cls(sport).from_dict(settings, strict=False).to_json())
            if moved:
                new = dict(new, name=f"{pr['name']} · adjusted", adjusted=moved, **({"rolled": True} if rolled == "1" else {}))
        elif code == "basic":
            new = R.basic_profile(c, me["id"])
        elif PF.is_combo(PF.PROFILES[code]):
            new = PF.load(c, code)
        else:
            new = PF.load(c, PF.ensure_candidates(c)[code])
            settings, moved = _adjusted(code, form)
            if moved:
                new = dict(new, name=f"{PF.PROFILES[code]['name']} · adjusted", settings=SS.Settings.from_dict(
                    settings, strict=False).to_json(), adjusted=moved, **({"rolled": True} if rolled == "1" else {}))
        if new is not None:
            new = dict(new, base=code)
        if not R.allowed_profile(me["role"], new, user_id=me["id"]):
            return RedirectResponse(back + "Error: that strategy isn't open to this account.", status_code=303)
        PF.assign(c, me["id"], new, venue, sport)
    audit(request, "strategy_pick", old=(old or {}).get("name"), new=(new or {}).get("name"),
          adjusted=(new or {}).get("adjusted"), rolled=bool((new or {}).get("rolled")),
          **({} if slot == F1_SLOT else dict(venue=venue, sport=sport)))
    if new is None:
        return RedirectResponse(back + "Stopped: nothing trades for this account here until you pick again.",
                                status_code=303)
    if slot not in TIMED_SLOTS:
        return RedirectResponse(back + f"Saved {new['name']} for {here['label']}. Live calls there start once that "
                                "sport's signal pass is switched on (today only F1 on Polymarket runs).", status_code=303)
    return RedirectResponse("/strategy?msg=" + f"Now running {new['name']}. Its calls start when the next race "
                            "weekend's signals open, four days before the race.", status_code=303)
