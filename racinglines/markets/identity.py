"""
Which driver and race a market is about, for the sports whose schema names a resolver ([identity] resolver in
sports/<code>.toml). A sync builds its link rows, hands them to `linker(sport, conn).fill(rows)`, and stores what comes
back: the same answer whichever exchange the rows came from, and the same one the database pass gives the links
already stored (`racinglines <sport> link`). A sport with no resolver gets None and nothing changes.

    L = linker("nascar", conn)
    if L:
        L.fill(rows)            # sets athlete_id / race_id / params on each row; never raises
        stats["identity"] = dict(L.counts)
"""

import importlib

from racinglines import sports


def linker(sport, conn):
    name = sports.identity(sport)
    if not name:
        return None
    return importlib.import_module(f"racinglines.sources.{name}.links").Linker(conn)
