"""
Every setting of a season sweep, in one schema: the model, entry timing, taker and maker strategy
parameters, and which markets to trade. The same schema drives the `racinglines f1 sweep` flags, the
Lab's Edge Finder sweep form, the search queue (sweeps/*.toml) and each saved sweep's params, so any
model x strategy combo found anywhere can be recreated exactly (the simulations are seeded).

Defaults are today's baseline. A combo's identity is `settings_key` (all settings); the stage-pricing
cache is keyed by `model_key` (only the settings that change prices), plus the data each stage saw.
Optional settings (default None, "not set") added later are left out of both keys while unset, so
every key saved before they existed stays the same.

    s = Settings.from_dict({"variant": "gridq+pretrain", "half_life_days": 90})
    with s.applied():            # model globals set for the duration (restored afterwards)
        ...
"""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass

STAGES = ("pre-weekend", "after FP1", "after FP2", "after FP3", "after SQ", "after Sprint", "after Quali")
KINDS = ("race_win", "race_podium", "race_h2h", "race_constructor_top", "race_pole")
DEFAULT_SEED = 42                # pricing.diagnostic's and the signal engine's seed
VENUES = ("polymarket", "kalshi")    # exchanges a sweep / the signal engine can trade (markets/venue_replay.py)
DEFAULT_VENUE = "polymarket"


@dataclass(frozen=True)
class Setting:
    name: str
    group: str                   # model | timing | taker | maker | markets
    label: str
    type: str                    # float | int | bool | choice | multi | text
    default: object
    min: float | None = None
    max: float | None = None
    choices: tuple = ()
    help: str = ""
    target: str = ""             # "module.ATTR" set while applied (model settings)
    unset: object = None         # a value that means "not set" (stored as None, so it stays out of the keys)


SETTINGS = [
    # --- model: these change prices (model_key) ---------------------------------------------------
    Setting("variant", "model", "Model variant", "text", "baseline",
            help="Switch combination joined with +, e.g. gridq+pretrain+reset (see Formula 1 > Model variants)."),
    Setting("sims", "model", "Simulations per stage", "int", 4000, 1000, 50000),
    Setting("half_life_days", "model", "Recency half-life (days)", "float", 120.0, 20, 720,
            help="How fast old results stop counting in the pace models.", target="model.HALF_LIFE_DAYS"),
    Setting("track_features", "model", "Track/sector features", "bool", True,
            help="Car's fast-vs-slow sector profile matched to each track."),
    Setting("practice_prior", "model", "Practice pace prior", "bool", True,
            help="Use this weekend's practice laps once they exist.", target="practice.USE_PRACTICE"),
    Setting("ridge_team", "model", "Team pace shrinkage (events)", "float", 2.0, 0, 20,
            help="Prior weight pulling each team's base pace to the field.", target="model.RIDGE_A"),
    Setting("ridge_slope", "model", "Track-slope shrinkage (events)", "float", 6.0, 0, 50,
            help="Prior weight pulling each team's fast/slow-sector slope to 0.", target="model.RIDGE_B"),
    Setting("driver_prior_n", "model", "Driver offset shrinkage", "float", 3.0, 0, 30,
            help="How many races before a driver's gap to the teammate is trusted.", target="model.DRIVER_PRIOR_N"),
    Setting("teammate_corr", "model", "Teammates share noise", "bool", True, target="model.TEAMMATE_CORR"),
    Setting("finish_rho_scale", "model", "Teammate finish correlation scale", "float", 1.0, 0, 2,
            target="model.FINISH_RHO_SCALE"),
    Setting("reset_weight", "model", "Regulation-reset carry-over", "float", 0.25, 0, 1,
            help="With the reset switch: weight of earlier seasons' car data.", target="model.REG_RESET_WEIGHT"),
    Setting("seed", "model", "Monte Carlo seed", "int", None, 0, 2**31 - 1,
            help="Empty = today's fixed seed (42). Set different seeds for independent noise draws in a search."),
    # --- entry timing ---------------------------------------------------------------------------------
    Setting("taker_stages", "timing", "Stages takers may trade", "multi", STAGES, choices=STAGES,
            help="Applies to every taker strategy (update, hold, after quali, stage-aware)."),
    Setting("late_stages", "timing", "Stage-aware taker: stop at", "multi", ("after FP3", "after Quali"), choices=STAGES,
            help="Stages the stage-aware taker skips."),
    # --- taker ----------------------------------------------------------------------------------------
    Setting("min_edge", "taker", "Min edge to act (prob.)", "float", 0.05, 0.005, 0.5),
    Setting("min_edge_h2h", "taker", "Min edge for head-to-head markets", "float", None, 0.005, 0.5,
            help="Empty = same as min edge."),
    Setting("min_edge_by_kind", "taker", "Min edge per market kind", "map", None, 0.005, 0.5, choices=KINDS,
            help="kind=edge pairs, e.g. race_h2h=0.05,race_podium=0.08; each overrides min edge (and the "
                 "head-to-head one) for its kind. Empty = none."),
    Setting("stake_per_edge", "taker", "Stake per unit edge ($)", "float", 250.0, 10, 5000,
            help="Target cost = this x edge, e.g. 250 x 0.10 = $25."),
    Setting("max_stake", "taker", "Max stake per market ($)", "float", 50.0, 1, 5000),
    Setting("cost", "taker", "Cost per share per trade ($)", "float", 0.01, 0, 0.1),
    Setting("bankroll", "taker", "Starting bankroll ($)", "float", None, 10, 1e7,
            help="Bankroll-aware sizing: stakes scale with the balance after earlier weekends. Empty = fixed sizing."),
    Setting("max_deployed", "taker", "Max capital deployed per weekend ($)", "float", None, 1, 1e7,
            help="Across all markets; buys over the cap are cut to fit. Empty = no cap."),
    # --- maker ----------------------------------------------------------------------------------------
    Setting("half_spread", "maker", "Quote half-spread ($)", "float", 0.02, 0.005, 0.2),
    Setting("size", "maker", "Shares per quote", "float", 50.0, 1, 1000),
    Setting("max_pos", "maker", "Max inventory per market (shares)", "float", 250.0, 10, 5000),
    Setting("skew", "maker", "Inventory skew", "float", 1.0, 0, 5),
    Setting("max_disagree", "maker", "Don't quote beyond |fair - market|", "float", 0.15, 0.01, 1),
    Setting("maker_min_volume_24h", "maker", "Maker: min $ traded in prior 24 h", "float", None, 0, 100000,
            help="Per market, before quoting it. Empty = the replay's own $100 (the Markets filter is the takers')."),
    Setting("fill", "maker", "Fill rule", "choice", "through", choices=("through", "touch", "queue"),
            help="through = a trade must cross our price (conservative); touch = at our price; "
                 "queue = at our price once the recorded book's queue ahead of us is served."),
    Setting("info_skew", "maker", "Info-timed skew (maker_skew / maker_all)", "float", 2.0, 0, 10),
    Setting("widen", "maker", "Widen factor on bad markouts (maker_widen / maker_all)", "float", 1.5, 1, 5),
    # --- markets --------------------------------------------------------------------------------------
    Setting("market_kinds", "markets", "Market kinds traded", "multi", KINDS, choices=KINDS),
    Setting("min_volume_24h", "markets", "Min $ traded in prior 24 h", "float", 50.0, 0, 100000),
    Setting("venue", "markets", "Venue", "choice", None, choices=VENUES, unset=DEFAULT_VENUE,
            help="Whose markets and recorded tape the strategies trade: polymarket (the default) or kalshi "
                 "(its links, its tape read per market ticker, its maker fee). Unset = polymarket."),
]
BY_NAME = {s.name: s for s in SETTINGS}
# The split (docs/backtest-core.md): the pricing model's own group, and the groups any sport's backtest shares
# (entry timing, taker, maker, markets and their guards). Another model family's settings are its own model
# group plus these once it trades a venue (models/timed_runs/settings.py is model-only so far).
MODEL_SETTINGS = [s for s in SETTINGS if s.group == "model"]
SHARED_SETTINGS = [s for s in SETTINGS if s.group != "model"]
GROUPS = (("model", "Model"), ("timing", "Entry timing"), ("taker", "Taker strategies"),
          ("maker", "Maker strategies"), ("markets", "Markets"))
MODEL_NAMES = [s.name for s in SETTINGS if s.group == "model"]
ALIASES = {"n_sims": "sims"}            # older saved params


def _coerce(s, v):
    if v is None or (s.default is None and isinstance(v, str) and not v.strip()):
        return s.default
    if s.unset is not None and v == s.unset:
        return s.default
    if s.type == "float":
        return float(v)
    if s.type == "int":
        return int(float(v))
    if s.type == "bool":
        return v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
    if s.type == "multi":
        items = [x.strip() for x in v.split(",")] if isinstance(v, str) else list(v)
        bad = [x for x in items if x and x not in s.choices]
        if bad:
            raise ValueError(f"{s.label}: unknown {bad}; choose from {list(s.choices)}")
        return tuple(x for x in s.choices if x in items)         # canonical order
    if s.type == "map":                                      # "kind=value,..." -> canonical text (sorted, floats)
        pairs = {}
        for item in (v.split(",") if isinstance(v, str) else [f"{k}={x}" for k, x in dict(v).items()]):
            if not item.strip():
                continue
            k, _, x = item.partition("=")
            k = k.strip()
            if k not in s.choices:
                raise ValueError(f"{s.label}: unknown {k!r}; choose from {list(s.choices)}")
            x = float(x)
            if not s.min <= x <= s.max:
                raise ValueError(f"{s.label}: {k}={x} is outside {s.min}-{s.max}")
            pairs[k] = x
        return ",".join(f"{k}={pairs[k]:g}" for k in sorted(pairs)) or s.default
    if s.type == "choice":
        if v not in s.choices:
            raise ValueError(f"{s.label}: pick one of {list(s.choices)}")
        return v
    return str(v).strip()


class Settings(dict):
    """A full, validated set of sweep settings (missing ones take their defaults).

    The schema is a class attribute, so another model family defines its own settings by subclassing
    (e.g. racinglines/models/timed_runs/settings.py) and keeps the same keys, labels and flags."""

    SPEC = SETTINGS
    BY = BY_NAME
    MODEL = MODEL_NAMES
    ALIASES = ALIASES
    DEFAULT_SEED = DEFAULT_SEED

    @classmethod
    def from_dict(cls, d=None, strict=True):
        d = {cls.ALIASES.get(k, k): v for k, v in (d or {}).items()}
        unknown = [k for k in d if k not in cls.BY]
        if unknown and strict:
            raise ValueError(f"unknown settings {unknown}")
        out = cls()
        for s in cls.SPEC:
            v = _coerce(s, d.get(s.name))
            if s.type in ("float", "int") and v is not None and s.min is not None and not s.min <= v <= s.max:
                raise ValueError(f"{s.label}: {v} is outside {s.min}-{s.max}")
            out[s.name] = v
        out._validate()
        return out

    def _validate(self):
        from racinglines.models.position_sim import variants as V
        V.switches(self["variant"])                                  # raises on an unknown switch

    @classmethod
    def from_run_params(cls, params):
        """Settings of a saved sweep, including ones saved before this schema existed."""
        p = dict(params or {})
        if isinstance(p.get("settings"), dict):
            return cls.from_dict(p["settings"], strict=False)
        return cls.from_dict({k: v for k, v in p.items() if cls.ALIASES.get(k, k) in cls.BY}, strict=False)

    def changed(self):
        """{name: value} of the settings that differ from the defaults."""
        return {k: v for k, v in self.items() if v != self.BY[k].default}

    def _key(self, names):
        names = [k for k in names if not (self.BY[k].default is None and self[k] is None)]   # unset optionals
        blob = json.dumps({k: self[k] for k in names}, sort_keys=True, default=list)
        return hashlib.sha1(blob.encode()).hexdigest()[:12]

    @property
    def key(self):
        """Identity of the whole combo (every setting)."""
        return self._key(sorted(self))

    @property
    def rng_seed(self):
        """The Monte Carlo seed: the `seed` setting, or today's fixed one when it's unset."""
        return self.DEFAULT_SEED if self["seed"] is None else self["seed"]

    @property
    def model_key(self):
        """Identity of the pricing: only the settings that change the model's prices."""
        return self._key(self.MODEL)

    def label(self):
        ch = {k: v for k, v in self.changed().items() if k != "variant"}
        extra = ", ".join(f"{k}={','.join(v) if isinstance(v, tuple) else v}" for k, v in ch.items())
        return self["variant"] + (f" · {extra}" if extra else "")

    def to_json(self):
        return {k: list(v) if isinstance(v, tuple) else v for k, v in self.items()}

    def argv(self):
        """`racinglines f1 ... sweep` flags for the non-default settings (the variant is a global flag)."""
        out = []
        for k, v in self.changed().items():
            if k == "variant":
                continue
            flag = "--" + k.replace("_", "-")
            out += [flag, ",".join(v) if isinstance(v, tuple) else str(v).lower() if isinstance(v, bool) else str(v)]
        return out

    @contextmanager
    def applied(self):
        """Model settings (and the variant's switches) in force for the duration."""
        from racinglines.models.position_sim import model as M
        from racinglines.models.position_sim import practice as PR
        from racinglines.models.position_sim import variants as V
        mods = {"model": M, "practice": PR}
        old = []
        try:
            for s in SETTINGS:
                if s.target:
                    mod, attr = s.target.split(".")
                    old.append((mods[mod], attr, getattr(mods[mod], attr)))
                    setattr(mods[mod], attr, self[s.name])
            with V.use(self["variant"]):
                yield self
        finally:
            for mod, attr, v in reversed(old):
                setattr(mod, attr, v)


def venue_of(settings):
    """The exchange a settings set trades: its `venue`, or polymarket while unset."""
    return settings.get("venue") or DEFAULT_VENUE


def parse_map(v):
    """A map setting's canonical text -> {key: float} ({} when unset)."""
    return {k: float(x) for k, _, x in (i.partition("=") for i in v.split(","))} if v else {}


def add_arguments(parser, cls=None):
    """One flag per setting (the variant is the f1 group's global --variant)."""
    for s in (cls or Settings).SPEC:
        if s.name == "variant":
            continue
        dflt = ",".join(s.default) if s.type == "multi" else "not set" if s.default is None else s.default
        kw = dict(default=None, help=f"{s.label} (default {dflt})."
                                     + (f" {s.help}" if s.help else ""))
        parser.add_argument("--" + s.name.replace("_", "-"), **kw)


def from_args(args, cls=None):
    cls = cls or Settings
    d = {s.name: getattr(args, s.name) for s in cls.SPEC if s.name != "variant" and getattr(args, s.name, None) is not None}
    if "variant" in cls.BY:
        d["variant"] = getattr(args, "variant", "baseline") or "baseline"
    return cls.from_dict(d)


def data_key(view):
    """Fingerprint of the data a stage was priced from: row counts and column sums of the as-of view,
    leaving out database ids (they differ between databases built from the same data), so a cached
    stage is reused only when it saw exactly the same data, on any machine."""
    parts = []
    for name in ("res", "prof", "drivers", "sectors", "practice", "races"):
        df = getattr(view, name, None)
        if df is None:
            parts.append(f"{name}:-")
            continue
        num = df.select_dtypes("number")
        num = num[[c for c in num.columns if not (c == "id" or str(c).endswith("_id"))]]
        parts.append(f"{name}:{len(df)}:{float(num.fillna(0).to_numpy().sum()) if len(num.columns) else 0:.8g}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]
