"""Per-user settings that should follow the account to any device (users.prefs, JSONB): Edge Finder
combos and last-used knobs per job type. Pure view state (open sections, filters) stays in the
browser; history (jobs, runs, bets) lives in its own tables."""

import json

from sqlalchemy import text


def get(conn, user_id):
    if not user_id:
        return {}
    return conn.execute(text("SELECT prefs FROM users WHERE id = :u"), dict(u=user_id)).scalar() or {}


def put(conn, user_id, key, value):
    """Set one top-level key (the others are kept)."""
    if not user_id:
        return
    conn.execute(text("""UPDATE users SET prefs = coalesce(prefs, '{}'::jsonb) || jsonb_build_object(CAST(:k AS text), CAST(:v AS jsonb))
                         WHERE id = :u"""), dict(k=key, v=json.dumps(value), u=user_id))
    conn.commit()
