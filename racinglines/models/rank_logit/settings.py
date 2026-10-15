"""rank_logit's settings (docs/f1-roadmap.md F1-6, decision log 2026-10-14): a Setting schema, so the CLI flags, the
MCP run_job settings and the Lab form take them on their own. Every default reproduces the 6-7 Oct Plackett-Luce fits:
race rankings only, no ties, no teams, no truncation, no kind offsets, no covariance. None is tuned."""

from dataclasses import replace

from racinglines.models.inputs import results as RES
from racinglines.pipelines import sweep_settings as SS

_SHARED = {s.name: s for s in RES.SETTINGS}       # the results core's: sims, seed, the retirement draw

SETTINGS = [
    _SHARED["sims"],
    _SHARED["half_life_days"],
    SS.Setting("sd_athlete", "model", "Athlete prior SD (log-worth)", "float", 1.5, 0.05, 20,
               help="Normal prior on each athlete's log-worth: shrinkage and identifiability."),
    SS.Setting("sd_team", "model", "Team prior SD (log-worth)", "float", 0.75, 0.05, 20,
               help="Normal prior on each team effect (with team effects on)."),
    SS.Setting("delta_prior_mean", "model", "Tie prior mean (log delta)", "float", -2.0, -10, 5,
               help="Normal prior mean on log delta_t, t >= 2 (Davidson-Luce tie parameters)."),
    SS.Setting("delta_prior_sd", "model", "Tie prior SD (log delta)", "float", 2.0, 0.1, 20),
    SS.Setting("max_tie", "model", "Largest tie size", "int", 0, 0, 10,
               help="D, the largest tie the likelihood allows. 0 = the largest tie in the data."),
    SS.Setting("tie_on", "model", "Ties from", "choice", "", choices=("", "time_ms"),
               help="Empty: no ties (order by position). time_ms: classified entrants with identical times tie."),
    SS.Setting("top_k", "model", "Places that count (top k)", "int", 0, 0, 200,
               help="Only the first k places are chosen; the rest are an unordered tail. 0 = every place counts."),
    SS.Setting("team_effects", "model", "Team effects", "bool", False,
               help="A shared log-worth effect per team (needs [model] group in the schema)."),
    SS.Setting("kind_sd", "model", "Round-kind offset SD", "float", 0.0, 0, 5,
               help="0 = one strength for every round kind; > 0 adds an athlete x round-kind offset with this prior SD."),
    SS.Setting("ranking_weights", "model", "Ranking weights by round kind", "map", None, 0, 10,
               help="kind=weight pairs, e.g. race=1,qual=1, overriding the schema's [model.rank_logit.rankings] "
                    "defaults. Empty = the schema's."),
    SS.Setting("cov", "model", "Laplace covariance", "bool", False,
               help="Also compute the parameter covariance (numerical Hessian; slower)."),
    SS.Setting("sd_scale", "model", "Parameter-uncertainty scale", "float", 0.0, 0, 5,
               help="> 0 draws each simulation's strengths from the Laplace covariance times this (needs cov)."),
    _SHARED["dnf"],
    _SHARED["seed"],
]


class RankLogitSettings(SS.Settings):
    SPEC = SETTINGS
    BY = {s.name: s for s in SETTINGS}
    MODEL = [s.name for s in SETTINGS]
    ALIASES = {}

    def _validate(self):
        if self["sd_scale"] > 0 and not self["cov"]:
            raise ValueError("sd_scale > 0 needs cov (the Laplace covariance)")

    def label(self):
        return ", ".join(f"{k}={v}" for k, v in self.changed().items()) or "baseline"


def settings_class(kinds, defaults=None, where="[model.rank_logit.defaults]"):
    """RankLogitSettings for a sport: ranking_weights takes the kinds of its [model.rank_logit.rankings] table, and
    its [model.rank_logit.defaults] (if any) are the defaults."""
    spec = [replace(s, choices=tuple(kinds)) if s.name == "ranking_weights" else s for s in SETTINGS]
    cls = type("RankLogitSettings", (RankLogitSettings,), dict(SPEC=spec, BY={s.name: s for s in spec},
                                                               MODEL=[s.name for s in spec]))
    return SS.with_defaults(cls, defaults, where)
