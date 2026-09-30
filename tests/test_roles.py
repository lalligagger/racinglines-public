"""Roles and access tiers (racinglines/web/roles.py): pro / basic, the maker / taker aliases, the tier check."""

import pytest
from fastapi import Request

pytestmark = pytest.mark.quick


def test_aliases_and_db_spellings():
    from racinglines.web import roles as R
    assert R.ROLES == ("admin", "pro", "basic")
    assert R.canonical("maker") == "pro" and R.canonical("taker") == "basic"
    assert R.canonical("pro") == "pro" and R.canonical("admin") == "admin" and R.canonical("weird") == "weird"
    assert R.db_roles("pro", "admin") == ("pro", "maker", "admin")
    assert R.is_pro(dict(role="maker")) and R.is_pro(dict(role="admin")) and not R.is_pro(dict(role="taker"))
    assert R.is_basic(dict(role="taker")) and R.is_basic(dict(role="basic")) and not R.is_basic(dict(role="pro"))


def test_basic_tier_runs_only_its_own_draw():
    from racinglines.pipelines import profiles as PF
    from racinglines.web import roles as R
    a = dict(name=PF.PROFILES["A"]["name"], strategy="update")
    c = dict(name=PF.PROFILES["C"]["name"], strategy="maker")

    def draw(uid, codes=None):
        codes = codes or R.basic_members(uid)
        return dict(name=R.BASIC_NAME, strategy="update", members=[dict(code=k, weight=1 / 3, member={}) for k in codes])
    assert R.basic_profile_names() == (R.BASIC_NAME,)
    for role in ("admin", "pro", "maker"):                    # pro (and its old spelling): anything
        assert R.allowed_profile(role, a) and R.allowed_profile(role, c) and R.allowed_profile(role, None)
    other = next(u for u in range(2, 200) if set(R.basic_members(u)) != set(R.basic_members(1)))
    for role in ("basic", "taker"):
        assert R.allowed_profile(role, None) and R.allowed_profile(role, draw(1), user_id=1)
        assert not R.allowed_profile(role, draw(other), user_id=1)            # someone else's draw
        assert not R.allowed_profile(role, a) and not R.allowed_profile(role, c)
        assert R.allowed_profile(role, a, legacy_ok=True)                     # A, already assigned, keeps working
        assert not R.allowed_profile(role, c, legacy_ok=True)
        assert not R.allowed_profile(role, dict(name="something else", strategy="update"))


def test_allow_reads_old_role_values_as_the_new_tier():
    """A user row still stored as `maker` / `taker` passes allow() as pro / basic (no migration needed)."""
    from fastapi.testclient import TestClient
    from racinglines.web import app as A
    from racinglines.web import roles as R
    who = {}

    def as_user(request: Request):
        request.state.user = dict(id=1, username="tester", role=who["role"], sid=None)
        return request.state.user
    A.app.dependency_overrides[A.authenticate] = as_user
    A.app.dependency_overrides[A.conn] = lambda: None
    try:
        client = TestClient(A.app)
        assert A.PRO == R.PRO == ("admin", "pro") and A.ANY == ("admin", "pro", "basic")
        who["role"] = "taker"
        assert client.get("/lab/runs", follow_redirects=False).status_code == 403     # the Lab is pro-only
        who["role"] = "basic"
        assert client.get("/lab/runs", follow_redirects=False).status_code == 403
        who["role"] = "maker"
        r = client.get("/lab/runs", follow_redirects=False)
        assert r.status_code != 403                                                    # an old maker row is pro
        who["role"] = "pro"
        assert client.get("/lab/runs", follow_redirects=False).status_code == r.status_code
    finally:
        A.app.dependency_overrides.pop(A.authenticate, None)
        A.app.dependency_overrides.pop(A.conn, None)


def test_create_user_stores_the_new_spelling(test_engine):
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from racinglines.web import users as U
    with sessionmaker(test_engine)() as s:
        s.execute(text("DELETE FROM users WHERE username IN ('t_role_old', 't_role_new')"))
        s.commit()
        assert U.create_user(s, "t_role_old", "pw", "taker").role == "basic"          # old names still accepted
        assert U.create_user(s, "t_role_new", "pw", "pro").role == "pro"
        with pytest.raises(ValueError, match="role"):
            U.create_user(s, "t_role_bad", "pw", "vip")
        s.execute(text("DELETE FROM users WHERE username IN ('t_role_old', 't_role_new')"))
        s.commit()
