"""Why a replay finds nothing tradeable (read-only): for each race of a sport on one venue, per stage, how many of its
markets are priced, liquid (24 h volume >= the floor), open, and in the race's field, and the group's price sum against
its coherence target. The checks are position_replay.race_markets' own, minus the model's fair.

    .venv/bin/python scripts/vm/why_untradeable.py nascar polymarket 2026 [event_key ...]

PROBE_HOURS="-6,6,12,15" probes those hours from 00:00 UTC on race day instead of the schema's stages.
"""
import os
import sys

from racinglines.db.config import get_engine
from racinglines.pipelines import position_replay as P


def main(sport, venue, year, *events):
    sp = P.spec(sport)
    tol = getattr(P, "coherence_tol", lambda sp, venue: P.COHERENCE_TOL)(sp, venue)    # older checkouts: one tolerance
    engine = get_engine()
    with engine.connect() as conn:
        rs = P.select(P.races(conn, sp, [int(year)]), list(events) or None)
        lk = P.links(conn, sp, venue)
        print(f"{sport} {year} {venue}: {len(rs)} races; coherence tol {tol}, "
              f"group target {sp.get('group_target')}, volume floor ${P.MIN_VOLUME_24H:.0f}")
        for r in rs.itertuples():
            g = lk[lk["race_id"] == r.race_id] if len(lk) else lk
            if not len(g):
                continue
            field = set(int(a) for a in P.race_results(conn, r.race_id)["athlete_id"])
            probe = os.environ.get("PROBE_HOURS")
            stages = P.stage_times(r.start, dict(sp, stages=[[f"h{h}", float(h)] for h in probe.split(",")])
                                   if probe else sp)
            v = P._venue(conn, venue, g, stages, sp)
            print(f"{r.event_key} {r.name}: {len(g)} markets, {int(g['athlete_id'].isin(field).sum())} in the field")
            for lab, t in stages:
                views = [v.view(m, t, P.MIN_VOLUME_24H) for m in g.to_dict("records")]
                priced = sum(p is not None for p, _, _ in views)
                liquid = sum(ok for _, _, ok in views)
                opened = sum(P._open(m, t) for m in g.to_dict("records"))
                sums = {k: round(sum(p for p in (v.price(tok, t) for tok in g.loc[g["prediction"] == k, "token_id"])
                                     if p is not None), 2) for k in v.group_target}
                print(f"  {lab:9} {t:%Y-%m-%d %H:%M}: priced {priced}, liquid {liquid}, open {opened}, "
                      f"coherent {dict((k, v.coherent(k, t)) for k in v.group_target)}, price sum {sums}")


if __name__ == "__main__":
    main(*sys.argv[1:])
