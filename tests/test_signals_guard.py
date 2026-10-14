"""A signals pass stores only for the users who still run its profile (signals.still_assigned), and a fantasy reset
waits for a pass that is storing (web/accounts.reset locks the same rows): cback's race-17 positions came back 36 s
after the 12 Oct 2026 reset because a pass had loaded the old profile before it."""

import json

import pytest
from sqlalchemy import text

from racinglines.pipelines import profiles as PF
from racinglines.pipelines import signals as SG


def _user(c, name):
    return c.execute(text("""INSERT INTO users (username, password_hash, role) VALUES (:n, 'x', 'taker')
                             RETURNING id"""), dict(n=name)).scalar()


def test_a_pass_stores_only_for_users_who_still_run_its_profile(test_engine):
    """cback, race 17 of 2026: a pass loaded the old profile, the 12 Oct fantasy reset cleared it, and the pass wrote the
    positions back 36 s later. _run_one now re-reads the profile (rows locked) right before it stores."""
    prof = dict(candidate_id=999997, name="G · test", strategy="maker")
    out = dict(profile=prof, event=dict(event_key="2099-03", name="Test GP"), race_id=None, venue="polymarket",
               stages=[("FP1", None, None, None)], signals=[],
               positions=[dict(market_key="tok", kind="race_win", subject="X", yes_shares=5.0, no_shares=0.0, cash=-2.0,
                               mark=0.4, outcome=None)])
    with test_engine.begin() as c:
        a, b = _user(c, "guardtest-a"), _user(c, "guardtest-b")
        c.execute(text("UPDATE users SET prefs = jsonb_build_object(CAST(:k AS text), CAST(:p AS jsonb)) WHERE id IN (:a, :b)"),
                  dict(k=PF.pref(), p=json.dumps(prof), a=a, b=b))
        c.execute(text("UPDATE users SET prefs = prefs - CAST(:k AS text) WHERE id = :b"), dict(k=PF.pref(), b=b))     # b's reset
    n = lambda u: test_engine.connect().execute(text("SELECT count(*) FROM paper_positions WHERE user_id = :u"),  # noqa: E731
                                                dict(u=u)).scalar()
    said = []
    SG._run_one(test_engine, None, prof, out, [a, b], {a: None, b: None}, None, False, said.append, upcoming=None,
                guard=SG.guard(prof))
    assert (n(a), n(b)) == (1, 0) and any("no longer run G · test" in s for s in said)
    SG._run_one(test_engine, None, prof, out, [b], {b: None}, None, False, said.append, upcoming=None)
    assert n(b) == 1                                                    # no guard (a replay of another profile)
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), dict(a=a, b=b))


def test_a_reset_waits_for_a_pass_that_is_storing(test_engine):
    """The other order: a pass holding its users' rows (still_assigned, FOR SHARE) makes a fantasy reset wait, so the
    reset's deletes see what the pass wrote."""
    from sqlalchemy.exc import OperationalError
    from racinglines.web import accounts as ACC
    with test_engine.begin() as c:
        uid = _user(c, "guardtest-lock")
    with test_engine.connect() as held, test_engine.connect() as other:
        with held.begin():
            SG.still_assigned(held, [uid], key="x")
            with pytest.raises(OperationalError), other.begin():
                other.execute(text("SET LOCAL lock_timeout = '300ms'"))
                ACC.reset(other, apply=True)
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM users WHERE id = :u"), dict(u=uid))
