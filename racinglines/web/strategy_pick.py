"""
/strategy/pick: an account picks the strategy it paper-trades (owner, 2026-10-11 22:04Z: "no default strategy until they
select one ... defaults + sensible toggles/sliders"). Sign-up assigns none, so until a user picks here nothing trades
for them; this page is the user-facing side of what /admin/users/<id> does (admin.admin_user_profile).

    basic        "Your picks" (roles.basic_profile: its own draw of BASIC_PICKS from the taker shortlist), or none
    pro, admin   the taker shortlist (profiles.TAKER_TOP, ranked), the recommended blend (COMBOS) and maker C (only
                 with profiles.MAKERS_OPEN; off for the Alpha Fantasy Launch), with the few settings worth a slider
                 (TUNABLE) on a single strategy; a blend runs as tuned

The page shows every sport and exchange a strategy could point at (admin.profile_slots; owner, 2026-10-11 22:30Z:
"pointing a strat at a particular sport"), to admins only, and only F1 on Polymarket can be picked: it is the one slot the VM's signal
timer runs (deploy/vm/systemd/racinglines-signals.service), and the library's strategies carry F1's stages and kinds,
so on another sport they would fail or change (library/core/2026-10-11-strategies-per-sport.md). The others show as
"coming soon" until Core adds per-sport strategies.

Under the alpha layout (web/layout.alpha; owner, 2026-10-12 19:23-19:54Z; library/process/2026-10-12-alpha-lab-strategies.md)
the page is the five style cards instead (profiles.ALPHA_STYLES, by name, for basic and pro alike; no makers, blend or
other codes, and a save outside the five is refused unless the account is an admin), a sizing choice (Standard, or
Kelly at a fraction), and one closed "tweak" drawer with two sliders (edge needed, market volume) and the dice for pro
and admin; any tweak is untested, scored live from the next race weekend. alpha_picker() is the one switch: with it off
the page is the classic one above, unchanged.

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
from racinglines.web import layout as L
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

# --- the alpha picker (alpha_picker) ---
ALPHA_TWEAKS = ("min_edge", "min_volume_24h")       # the tweak drawer's two sliders, with TUNABLE's caps
TWEAK = "tweak:"                                    # the drawer's field prefix: applied to the card picked
# Sizing for a followed strategy (owner, 2026-10-12 19:53Z): Standard (stakes scaled to the player's F$1,000) or Kelly at
# a fraction. The allowed values and their meaning live in profiles (SIZINGS, KELLY_RANGE); the signal engine reads
# them through profiles.sizing_of (fantasy/sizing.py).
SIZINGS = PF.SIZINGS
KELLY = dict(lo=PF.KELLY_RANGE[0], hi=PF.KELLY_RANGE[1], step=0.05, default=0.25)
KELLY_PICKS = (("Quarter", 0.25), ("Half", 0.50), ("Full", 1.00))
# the label beside the Kelly slider, "nitty to degen", one emoji per tier (owner, 19:53-19:55Z): (highest fraction, label)
KELLY_LABELS = ((0.25, "Nitty ☕"), (0.50, "Shark 🦈"), (0.80, "Spicy 🌡️"), (1.00, "Degen 🤠"))


def alpha_picker():
    """The one switch between the alpha picker and the classic page: the alpha layout (web/layout.alpha)."""
    return L.alpha()


def kelly_label(f):
    return next(lab for top, lab in KELLY_LABELS if f <= top + 1e-9)


def style_name(code, adjusted=False):
    return PF.ALPHA_STYLES[code]["label"] + (" · adjusted" if adjusted else "")


def display_name(profile):
    """What the alpha page calls a running profile: its style's label when it came from one, else its name."""
    if not profile:
        return None
    code = profile.get("base")
    if code in PF.ALPHA_STYLES and not PF.is_combo(profile):
        return style_name(code, bool(profile.get("adjusted")))
    return profile.get("name")


def alpha_options(user):
    """The five style cards, in ALPHA_ORDER: [dict(code, label, blurb, backtest, in_sample, sliders)]; sliders are
    the drawer's two at the style's own values, for pro and admin only (a basic account runs a style as tuned)."""
    out = []
    for code in PF.ALPHA_ORDER:
        st = PF.ALPHA_STYLES[code]
        sl = [x for x in tunables(PF.PROFILES[code])[0] if x["name"] in ALPHA_TWEAKS] if not R.is_basic(user) else []
        out.append(dict(code=code, label=st["label"], blurb=st["blurb"], backtest=st["backtest"],
                        in_sample=bool(st.get("in_sample")), sliders=sl))
    return out


def sizing_of(form):
    """(sizing, kelly) from the form, validated: sizing in SIZINGS, kelly a fraction in [0.10, 1.00], kept on its 5%
    step. Raises ValueError with a message for the page."""
    sizing = form.get("sizing") or "standard"
    if sizing not in SIZINGS:
        raise ValueError("pick Standard or Kelly sizing")
    raw = form.get("kelly")
    try:
        k = KELLY["default"] if raw in (None, "") else float(raw)
    except ValueError:
        raise ValueError("the Kelly fraction must be a number") from None
    if not (KELLY["lo"] - 1e-9 <= k <= KELLY["hi"] + 1e-9):
        raise ValueError("the Kelly fraction must be between 10% and 100%")
    return sizing, round(round(k / KELLY["step"]) * KELLY["step"], 2)


def slots(user):
    """The sport tabs: admins see every sport and exchange a strategy could point at (F1 on Polymarket first, the only
    one open; see the docstring); everyone else sees none, as F1 on Polymarket is all they can pick in the Alpha (the
    owner hid MotoGP for it, 2026-10-11 22:59Z). -> [dict(key, label, open)]."""
    from racinglines.web.admin import profile_slots
    if R.canonical(user["role"]) != "admin":
        return []
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
    if alpha_picker():
        return _alpha_page(request, me, profile, w, msg)
    return render(request, "strategy_pick.html", opts=opts, profile=profile, now=now,
                  chosen=now or (opts[0]["code"] if R.is_basic(me) else DEFAULT), locked=demo.is_demo(me) or bool(w),
                  demo_locked=demo.is_demo(me), weekend_note=lock_note(w) if w else "", msg=msg, basic=R.is_basic(me),
                  slots=slots(me))


def _alpha_page(request, me, profile, w, msg):
    opts = alpha_options(me)
    now = profile.get("base") if profile and profile.get("base") in PF.ALPHA_STYLES and not PF.is_combo(profile) else None
    chosen = now or PF.ALPHA_ORDER[0]
    drawer = next(o for o in opts if o["code"] == chosen)["sliders"]
    if now and profile.get("adjusted"):            # the drawer starts where the user left it
        st = SS.Settings.from_dict(profile["settings"], strict=False)
        drawer = [dict(x, value=min(max(float(st[x["name"]]), x["lo"]), x["hi"])) if st[x["name"]] is not None else x
                  for x in drawer]
    k = float((profile or {}).get("kelly") or KELLY["default"])
    return render(request, "strategy_pick_alpha.html", opts=opts, profile=profile, running=display_name(profile),
                  now=now, chosen=chosen, drawer=drawer, sizing=(profile or {}).get("sizing") or "standard", kelly=k,
                  kelly_cfg=KELLY, kelly_picks=KELLY_PICKS, kelly_labels=KELLY_LABELS, kelly_label=kelly_label(k),
                  locked=demo.is_demo(me) or bool(w), demo_locked=demo.is_demo(me),
                  weekend_note=lock_note(w) if w else "", msg=msg, basic=R.is_basic(me))


def _alpha_form(code, form, user):
    """The drawer's fields ("tweak:<setting>", moved from "tweak_from:<setting>") as the classic per-code fields for
    _adjusted; a basic account's tweaks are ignored (it runs a style as tuned)."""
    if R.is_basic(user):
        return {}
    out = {}
    for n in ALPHA_TWEAKS:
        v, was = form.get(TWEAK + n), form.get("tweak_from:" + n)
        try:
            if v not in (None, "") and (was in (None, "") or abs(float(v) - float(was)) > 1e-9):
                out[f"{code}:{n}"] = v
        except ValueError:
            continue
    return out


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
async def pick_save(request: Request, code: str = Form(""), rolled: str = Form(""), slot: str = Form(F1_SLOT)):
    me = request.state.user
    if demo.is_demo(me):
        return RedirectResponse("/strategy/pick?msg=The demo accounts keep their strategy.", status_code=303)
    if slot != F1_SLOT:                             # only F1 on Polymarket can be picked in the Alpha
        return RedirectResponse("/strategy/pick?msg=Error: only Formula 1 on Polymarket can be picked for now.",
                                status_code=303)
    w = open_weekend()
    if w is not None:                               # a pick, a slider, a dice roll or a stop: all wait for the window
        return RedirectResponse("/strategy/pick?msg=Error: " + lock_note(w), status_code=303)
    form = await request.form()
    sizing = None
    if alpha_picker():                              # the five styles; an admin may still save any code it could before
        allowed = set(PF.ALPHA_ORDER) | ({o["code"] for o in options(me)} if R.canonical(me["role"]) == "admin" else set())
        if code in PF.ALPHA_STYLES:
            try:
                sizing = sizing_of(form)
            except ValueError as ex:
                return RedirectResponse(f"/strategy/pick?msg=Error: {ex}.", status_code=303)
            form = _alpha_form(code, form, me)
    else:
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
        if new is not None and sizing is not None:  # an alpha style: its name and the player's sizing
            new = dict(new, name=style_name(code, bool(new.get("adjusted"))), sizing=sizing[0], kelly=sizing[1])
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
