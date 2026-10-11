"""
/strategy/pick: an account picks the strategy it paper-trades (owner, 2026-10-11 22:04Z: "no default strategy until they
select one ... defaults + sensible toggles/sliders"). Sign-up assigns none, so until a user picks here nothing trades
for them; this page is the user-facing side of what /admin/users/<id> does (admin.admin_user_profile).

    basic        "Your picks" (roles.basic_profile: its own draw of BASIC_PICKS from the taker shortlist), or none
    pro, admin   the taker shortlist (profiles.TAKER_TOP, ranked), the recommended blend (COMBOS) and maker C (only
                 with profiles.MAKERS_OPEN; off for the Alpha Fantasy Launch), with the few settings worth a slider
                 (TUNABLE) on a single strategy; a blend runs as tuned

The page shows every sport and exchange a strategy could point at (admin.profile_slots; owner, 2026-10-11 22:30Z:
"pointing a strat at a particular sport"), but only F1 on Polymarket can be picked: it is the one slot the VM's signal
timer runs (deploy/vm/systemd/racinglines-signals.service), and the library's strategies carry F1's stages and kinds,
so on another sport they would fail or change (library/core/2026-10-11-strategies-per-sport.md). The others show as
"coming soon" until Core adds per-sport strategies.

Saving goes through profiles.assign (F1 on Polymarket, the slot the signal engine runs). The demo accounts keep the
profiles assign_demo gives them: they see the page but can't save. The dice (owner, 2026-10-11 22:20Z: "let the user input
RNG'ed values ... high temperature / lots of variation once we have a few dozen users") roll the sliders in the browser
(app.js), as far from the strategy's own settings as the spread allows; a rolled save is marked `rolled` on the profile. Split out of web/app.py, which imports this module.
"""

import time

import pandas as pd
from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from racinglines.pipelines import profiles as PF
from racinglines.pipelines import sweep_settings as SS
from racinglines.web import demo
from racinglines.web import roles as R
from racinglines.web.app import ANY, allow, app, audit, check_csrf, get_engine, render
from racinglines.web.ranges import UI_RANGES

# what a pro account picks from, in this order (TAKER_TOP is ranked); no makers while profiles.MAKERS_OPEN is off
PRO_CODES = PF.open_codes((*PF.TAKER_TOP, "TB", "C"))
DEFAULT = PF.TAKER_TOP[0]                   # preselected when the account runs nothing yet: the shortlist's first
PRE = "pre-weekend"
# The settings a user may move, per kind of strategy: (setting, label, low, high, step, unit), the range from the web
# forms' caps (web/ranges.py: what has been backtested). Probabilities show as points (x100). Anything else stays as
# the strategy has it.
_T = {"taker": (("min_edge", "Minimum edge to take a price", 0.01, "pts"),
                ("min_edge_h2h", "Minimum edge on head-to-head markets", 0.01, "pts"),
                ("min_volume_24h", "Only markets with this much traded in the last 24 h", 50, "$")),
      "maker": (("max_disagree", "Stop quoting where the model and the market differ by more than", 0.01, "pts"),
                ("size", "Shares per quote", 5, "shares"))}
TUNABLE = {k: tuple((n, label, *UI_RANGES[n], step, unit) for n, label, step, unit in v) for k, v in _T.items()}
F1_SLOT = "f1:polymarket"


def slots():
    """Every sport and exchange a strategy could point at, F1 on Polymarket first: [dict(key, label, open)]; only F1 on
    Polymarket is open (see the docstring)."""
    from racinglines.web.admin import profile_slots
    return [dict(s, open=s["key"] == F1_SLOT) for s in profile_slots()]


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


def lock_note(w):
    from racinglines.pipelines import signals as SG
    return (f"Strategy changes are paused during {w['name']}: they open again about a day after the race "
            f"({w['race_start'] + SG.WEEKEND_TAIL:%a %d %b, %H:%M} UTC), so a change never rewrites this weekend's calls.")


def kind(profile):
    from racinglines.pipelines import weekend_sweep as WS
    return "taker" if profile.get("strategy", "update") in WS.TAKER_MODES else "maker"


def tunables(pr):
    """The sliders and the pre-weekend toggle for one strategy (a PROFILES entry), at its own values."""
    if PF.is_combo(pr):
        return [], None
    st = SS.Settings.from_dict(pr["settings"], strict=False)
    k = kind(pr)
    sl = []
    for name, label, lo, hi, step, unit in TUNABLE[k]:
        v = st[name] if st[name] is not None else st["min_edge"] if name == "min_edge_h2h" else lo
        v = min(max(float(v), lo), hi)
        sl.append(dict(name=name, label=label, lo=lo, hi=hi, step=step, unit=unit, value=v, base=v))
    pre = (PRE in (st["taker_stages"] or ())) if k == "taker" else None
    return sl, pre


def options(user):
    """The strategies this account may pick: [dict(code, name, kind, why, sliders, pre)]."""
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
def pick_page(request: Request, msg: str = ""):
    me = request.state.user
    opts = options(me)
    with get_engine().connect() as c:
        profile = PF.of_user(c, me["id"])
    now = current_code(profile, opts)
    for o in opts:                                 # an adjusted profile: its sliders start where the user left them
        if o["code"] == now and profile.get("adjusted"):
            st = SS.Settings.from_dict(profile["settings"], strict=False)
            for sl in o["sliders"]:
                if st[sl["name"]] is not None:
                    sl["value"] = min(max(float(st[sl["name"]]), sl["lo"]), sl["hi"])
            if o["pre"] is not None:
                o["pre"] = PRE in (st["taker_stages"] or ())
    w = open_weekend()
    return render(request, "strategy_pick.html", opts=opts, profile=profile, now=now,
                  chosen=now or (opts[0]["code"] if R.is_basic(me) else DEFAULT), locked=demo.is_demo(me) or bool(w),
                  demo_locked=demo.is_demo(me), weekend_note=lock_note(w) if w else "", msg=msg, basic=R.is_basic(me),
                  slots=slots())


def _adjusted(code, form):
    """A strategy's settings with the form's sliders and pre-weekend toggle for it (fields named "<code>:<setting>"),
    clamped to TUNABLE; -> (settings, {what moved}), {} when nothing moved."""
    base = PF.PROFILES[code]
    st = dict(base["settings"])
    sl, pre = tunables(base)
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
    SS.Settings.from_dict(st)                          # strict: a value the engine wouldn't take fails here, not later
    return st, moved


@app.post("/strategy/pick", dependencies=[Depends(check_csrf), allow(*ANY)])
async def pick_save(request: Request, code: str = Form(""), rolled: str = Form("")):
    me = request.state.user
    if demo.is_demo(me):
        return RedirectResponse("/strategy/pick?msg=The demo accounts keep their strategy.", status_code=303)
    w = open_weekend()
    if w is not None:                               # a pick, a slider, a dice roll or a stop: all wait for the window
        return RedirectResponse("/strategy/pick?msg=Error: " + lock_note(w), status_code=303)
    form = await request.form()
    allowed = {o["code"] for o in options(me)}
    with get_engine().begin() as c:
        old = PF.of_user(c, me["id"])
        if code == "none":
            new = None
        elif code not in allowed:
            return RedirectResponse("/strategy/pick?msg=Error: pick one of the strategies listed.", status_code=303)
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
            return RedirectResponse("/strategy/pick?msg=Error: that strategy isn't open to this account.", status_code=303)
        PF.assign(c, me["id"], new)
    audit(request, "strategy_pick", old=(old or {}).get("name"), new=(new or {}).get("name"),
          adjusted=(new or {}).get("adjusted"), rolled=bool((new or {}).get("rolled")))
    if new is None:
        return RedirectResponse("/strategy/pick?msg=Stopped: nothing trades for this account until you pick again.",
                                status_code=303)
    return RedirectResponse("/strategy?msg=" + f"Now running {new['name']}. Its calls start when the next race "
                            "weekend's signals open, four days before the race.", status_code=303)
