"""The admin Lab monitors page (owner, 2026-10-17, takers only): every lab-<candidate id> account with its Polymarket
paper record, best P&L first, an account with no weekends yet last, and admin only."""

import json

from sqlalchemy import text as T

from test_strategy_pick import app_db  # noqa: F401  (the fixture)


def test_lab_monitors_page_lists_each_monitor_with_its_record(app_db):  # noqa: F811
    from fastapi.testclient import TestClient

    from racinglines.db import config
    from racinglines.web import users as U
    with config.get_session() as s:
        U.create_user(s, "root", "root-password-1", "admin")
    with config.get_engine().begin() as c:
        ids = {}
        for name, disp in (("lab-1", "Lab monitor: Hold to lights out"), ("lab-2", "Lab monitor: Early taker"),
                           ("lab-3", "Lab monitor: Not started")):
            ids[name] = c.execute(T("""INSERT INTO users (username, display_name, password_hash, role)
                                       VALUES (:n, :d, 'x', 'pro') RETURNING id"""), dict(n=name, d=disp)).scalar()
        for name, ev, pnl, settled in (("lab-1", "2099-01", -2.0, True), ("lab-2", "2099-01", 5.0, True),
                                       ("lab-2", "2099-02", 1.5, False)):
            c.execute(T("""INSERT INTO strategy_signals (user_id, profile, strategy, event_key, market_key, kind, subject, stage,
                             dedupe, action, side, shares, limit_price, fair, price, edge, heat, status, signal_ts, detail)
                           VALUES (:u, 'lab', 'hold', :e, :e, 'race_win', 'Zed', 'after FP2', :e, 'buy', 'YES',
                             10, 0.4, 0.5, 0.4, 0.1, 1, 'done', now(), CAST(:d AS jsonb))"""),
                      dict(u=ids[name], e=ev, d=json.dumps({})))
            c.execute(T("""INSERT INTO paper_positions (user_id, event_key, market_key, kind, subject, yes_shares, cash, outcome,
                                                        mark, venue)
                           VALUES (:u, :e, :e, 'race_win', 'Zed', :y, :pnl, :o, 0.5, 'polymarket')"""),
                      dict(u=ids[name], e=ev, y=0 if settled else 1, pnl=pnl if settled else pnl - 0.5,
                           o=True if settled else None))

    pro, admin = TestClient(app_db.app), TestClient(app_db.app)
    for client, name in ((pro, "ada"), (admin, "root")):
        client.post("/login", data=dict(username=name, password=f"{name}-password-1"), follow_redirects=False)
    assert pro.get("/admin/monitors", follow_redirects=False).status_code in (302, 303, 403, 404)
    page = admin.get("/admin/monitors")
    assert page.status_code == 200
    html = page.text
    assert html.index("Early taker") < html.index("Hold to lights out") < html.index("Not started")   # best P&L first
    assert "Lab monitor:" not in html and 'href="/admin/monitors"' in html
    assert "$6.50" in html and "none yet" in html


def test_lab_monitors_page_says_how_to_make_them(app_db):  # noqa: F811
    from fastapi.testclient import TestClient

    from racinglines.db import config
    from racinglines.web import users as U
    with config.get_session() as s:
        U.create_user(s, "root", "root-password-1", "admin")
    admin = TestClient(app_db.app)
    admin.post("/login", data=dict(username="root", password="root-password-1"), follow_redirects=False)
    assert "strategy profiles f1 --monitors" in admin.get("/admin/monitors").text
