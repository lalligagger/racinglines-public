"""
/strategy/pick: an account picks the strategy it paper-trades (owner, 2026-10-11 22:04Z: "no default strategy until they
select one ... defaults + sensible toggles/sliders"). Sign-up assigns none, so until a user picks here nothing trades
for them; this page is the user-facing side of what /admin/users/<id> does (admin.admin_user_profile).

    basic        "Your picks" (roles.basic_profile: its own draw of BASIC_PICKS from the taker shortlist), or none
    pro, admin   the taker shortlist (profiles.TAKER_TOP, ranked), the recommended blend (COMBOS) and maker C, with
                 the few settings worth a slider (TUNABLE) on a single strategy; a blend runs as tuned

Saving goes through profiles.assign (F1 on Polymarket, the slot the signal engine runs). The demo accounts keep the
profiles assign_demo gives them: they see the page but can't save. The dice (owner, 2026-10-11 22:20Z: "let the user input
RNG'ed values ... high temperature / lots of variation once we have a few dozen users") roll the sliders in the browser
(app.js), as far from the strategy's own settings as the spread allows; a rolled save is marked `rolled` on the profile. Split out of web/app.py, which imports this module.
"""

from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from racinglines.pipelines import profiles as PF
from racinglines.pipelines import sweep_settings as SS
from racinglines.web import demo
from racinglines.web import roles as R
from racinglines.web.app import ANY, allow, app, audit, check_csrf, get_engine, render

PRO_CODES = (*PF.TAKER_TOP, "TB", "C")     # what a pro account picks from, in this order (TAKER_TOP is ranked)
DEFAULT = PF.TAKER_TOP[0]                   # preselected when the account runs nothing yet: the shortlist's first
PRE = "pre-weekend"
# The settings a user may move, per kind of strategy: (setting, label, low, high, step, unit). Probabilities show as
# points (x100). Each range sits inside its sweep_settings.Setting bounds; anything else stays as the strategy has it.
TUNABLE = {
    "taker": (("min_edge", "Minimum edge to take a price", 0.03, 0.20, 0.01, "pts"),
              ("min_edge_h2h", "Minimum edge on head-to-head markets", 0.03, 0.20, 0.01, "pts"),
              ("min_volume_24h", "Only markets with this much traded in the last 24 h", 0, 1000, 50, "$")),
    "maker": (("max_disagree", "Stop quoting where the model and the market differ by more than", 0.03, 0.20, 0.01, "pts"),
              ("size", "Shares per quote", 10, 100, 5, "shares")),
}


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
    return render(request, "strategy_pick.html", opts=opts, profile=profile, now=now,
                  chosen=now or (opts[0]["code"] if R.is_basic(me) else DEFAULT), locked=demo.is_demo(me), msg=msg,
                  basic=R.is_basic(me))


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
    return RedirectResponse("/strategy?msg=" + f"Now running {new['name']}. Its calls start with the next pricing "
                            "update.", status_code=303)
