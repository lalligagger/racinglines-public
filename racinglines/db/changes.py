"""
The data change log (table data_changes): what changed in the race history, when, by whom and why.

    record(session, "ingest", "12 files re-ingested ...", sport="mtb_dh", detail={...})
    racinglines db changes [--limit N] [--sport mtb_dh]      list, newest first
    racinglines db changes --add "why" [--sport mtb_dh]      a manual note (e.g. a re-download's reason)

Ingests that change nothing aren't logged. docs/data-changes.md keeps the story of the major updates.
"""

import getpass
import socket

from sqlalchemy import select

from racinglines.db import models as m


def _by():
    try:
        return f"{getpass.getuser()}@{socket.gethostname()}"[:80]
    except Exception:                                    # pragma: no cover
        return None


def record(session, kind, summary, sport=None, detail=None):
    """Add one row (the caller commits)."""
    row = m.DataChange(kind=kind, summary=summary, sport=sport, detail=detail, by=_by())
    session.add(row)
    return row


def recent(session, limit=20, sport=None):
    q = select(m.DataChange).order_by(m.DataChange.at.desc(), m.DataChange.id.desc()).limit(limit)
    if sport:
        q = q.where(m.DataChange.sport == sport)
    return session.scalars(q).all()
