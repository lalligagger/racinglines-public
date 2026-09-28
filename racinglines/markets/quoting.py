"""
The maker's quotes on a private book, shared by every live sport: fair +- a half-spread, leaning against
inventory, capped per market, with no quote on a decided market or outside 1-99 cents. The half-spread
itself (and any widening) is the sport's: downhill widens while a rider is on course, F1 tightens stage by
stage (sports/<code>.toml [live.quoting]).

    quote(0.40, 0.03, inv=-500)      -> (bid, ask), either None when not offered
"""

import math
from dataclasses import asdict, dataclass

LO, HI = 0.005, 0.995           # no quote on a market this close to decided


@dataclass(frozen=True)
class Params:
    half_spread: float = 0.03
    max_pos: float = 2500.0     # the maker's shares per market, either way
    skew: float = 1.0           # quotes lean against inventory: shift = -skew x half-spread x inventory / max_pos

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})

    def to_dict(self):
        return asdict(self)


def quote(fair, hs, inv=0.0, max_pos=2500.0, skew=1.0, tidy=True):
    """The maker's YES quote on one market: (bid, ask) in cents-rounded dollars, or (None, None). Leans
    against inventory; stops adding to a position at max_pos. tidy rounds away float noise before the
    floor / ceiling (0.40 + 0.03 quotes 0.43, not 0.44); downhill quotes without it, as it always has."""
    if fair is None or fair <= LO or fair >= HI:
        return None, None
    shift = -skew * hs * inv / max_pos
    lo, hi = (fair - hs + shift) * 100, (fair + hs + shift) * 100
    if tidy:
        lo, hi = round(lo, 6), round(hi, 6)
    bid = math.floor(lo) / 100
    ask = math.ceil(hi) / 100
    bid = bid if bid >= 0.01 and inv < max_pos else None
    ask = ask if ask <= 0.99 and inv > -max_pos else None
    return bid, ask


def half_spread(by_stage, stage, default=0.03):
    """The half-spread for a stage: a number, or {stage label: half-spread} (the last known stage's for a
    label not listed)."""
    if not isinstance(by_stage, dict):
        return float(by_stage)
    return float(by_stage.get(stage, default))
