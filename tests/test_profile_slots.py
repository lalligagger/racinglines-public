"""Strategy profiles per sport and exchange: the prefs keys, the admin page's slots (from the schemas) and an
assignment to one slot that leaves the others alone."""


def test_pref_keys_keep_the_f1_ones():
    from racinglines.pipelines import profiles as PF
    assert PF.pref() == PF.PREF == "strategy_profile" and PF.pref("kalshi") == PF.PREF_KALSHI
    assert PF.pref("og", "nascar") == "strategy_profile_og_nascar" and PF.pref("polymarket", "motogp") == "strategy_profile_motogp"


def test_admin_slots_come_from_the_schemas():
    from racinglines.web import admin as AD
    keys = [s["key"] for s in AD.profile_slots()]
    assert keys[0] == "f1:polymarket"
    assert {"f1:kalshi", "f1:og", "nascar:polymarket", "nascar:kalshi", "nascar:og", "motogp:polymarket",
            "motogp:kalshi"} <= set(keys)
    assert "motogp:og" not in keys and not any(k.startswith("mtb_dh:") for k in keys)   # not listed there
    assert next(s["label"] for s in AD.profile_slots() if s["key"] == "nascar:og") == "NASCAR · OG.com"


def test_assigning_a_slot_leaves_the_others(test_engine, monkeypatch):
    from fastapi import Request
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from racinglines.db.ingest import seed
    from racinglines.pipelines import profiles as PF
    from racinglines.web import admin as AD
    from racinglines.web import app as A
    from racinglines.web import users as U
    with sessionmaker(test_engine)() as s:
        seed(s)                                       # the competitions a candidate row is filed under
        if not s.execute(text("SELECT 1 FROM users WHERE username = 't_slots'")).first():
            U.create_user(s, "t_slots", "pw", "pro")
        s.commit()
    with test_engine.begin() as c:
        uid = c.execute(text("SELECT id FROM users WHERE username = 't_slots'")).scalar()
        ids = PF.ensure_candidates(c)
    monkeypatch.setattr(AD, "get_engine", lambda *a: test_engine)
    monkeypatch.setattr(A, "get_engine", lambda *a: test_engine)                   # audit()

    def as_admin(request: Request):
        request.state.user = dict(id=uid, username="t_slots", role="admin", sid=None)
        return request.state.user
    A.app.dependency_overrides[A.authenticate] = as_admin
    A.app.dependency_overrides[A.conn] = lambda: None
    try:
        web = TestClient(A.app)
        post = lambda **d: web.post(f"/admin/users/{uid}/profile", data=dict(csrf_token=A.CSRF_TOKEN, **d),  # noqa: E731
                                    follow_redirects=False)
        assert post(candidate_id=str(ids["T1"]), slot="nascar:kalshi").status_code == 303
        assert post(candidate_id=str(ids["A"])).status_code == 303                   # no slot: F1 on Polymarket
        assert post(candidate_id=str(ids["A"]), slot="mtb_dh:kalshi").status_code == 400
        with test_engine.connect() as c:
            nk, f1 = PF.of_user(c, uid, "kalshi", "nascar"), PF.of_user(c, uid)
            assert nk["name"] == PF.PROFILES["T1"]["name"] and (nk["venue"], nk["sport"]) == ("kalshi", "nascar")
            assert f1["name"] == PF.PROFILES["A"]["name"] and "sport" not in f1
            assert PF.of_user(c, uid, "kalshi") is None and PF.of_user(c, uid, "og", "nascar") is None
            assert [u for u, *_ in PF.assigned(c, "kalshi", "nascar")] == [uid]
        assert post(candidate_id="", slot="nascar:kalshi").status_code == 303        # clear one slot
        with test_engine.connect() as c:
            assert PF.of_user(c, uid, "kalshi", "nascar") is None and PF.of_user(c, uid)["name"] == PF.PROFILES["A"]["name"]
    finally:
        A.app.dependency_overrides.clear()
        with test_engine.begin() as c:
            c.execute(text("DELETE FROM activity_log WHERE username = 't_slots'"))
            c.execute(text("DELETE FROM users WHERE username = 't_slots'"))
