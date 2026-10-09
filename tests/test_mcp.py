"""The MCP server (racinglines/mcp): the page envelope's caps, the sql guard, a client round trip over an
in-memory transport against the throwaway test database: tools, errors, resources, a queued job; and the hosted
mode's per-account tokens (issue, look up, revoke, the bearer check)."""

import asyncio
import json

import numpy as np
import pandas as pd
import pytest

from racinglines.mcp import page as P
from racinglines.mcp import tools as T

# --- the envelope (no database) ------------------------------------------------------------------

pytestmark = pytest.mark.quick


def test_page_caps_rows_and_reports_the_rest():
    df = pd.DataFrame(dict(i=range(1187), x=np.linspace(0, 1, 1187)))
    out = P.page(df, limit=50)
    assert out["total"] == 1187 and len(out["rows"]) == 50 and out["truncated"] and out["next_offset"] == 50
    assert "offset=50" in out["note"]
    nxt = P.page(df, limit=50, offset=1150)
    assert [r["i"] for r in nxt["rows"]] == list(range(1150, 1187)) and not nxt["truncated"] and nxt["next_offset"] is None
    assert P.page(df, limit=5000)["limit"] == P.MAX_LIMIT                     # the hard cap
    assert P.page(df, limit=0)["limit"] == 1 and P.page(df, limit="x")["limit"] == P.DEFAULT_LIMIT


def test_page_byte_cap_cuts_and_says_so():
    rows = [dict(i=i, text="x" * 150) for i in range(500)]
    out = P.page(rows, limit=500, max_bytes=4000)
    assert 0 < len(out["rows"]) < 500 and "cut to" in out["note"] and out["truncated"]
    assert len(json.dumps(out["rows"])) <= 4000


def test_page_values_are_json_safe_and_previewed():
    df = pd.DataFrame(dict(f=[1 / 3, np.nan], t=[pd.Timestamp("2026-09-25T13:30", tz="UTC"), pd.NaT],
                           j=[{"a": list(range(200))}, None], s=["short", "y" * 400], n=[np.int64(3), None],
                           b=[True, np.bool_(False)]))
    rows = P.page(df)["rows"]
    assert rows[0]["f"] == 0.3333 and rows[1]["f"] is None
    assert rows[0]["t"] == "2026-09-25T13:30:00+00:00" and rows[1]["t"] is None
    assert set(rows[0]["j"]) == {"_preview", "_size", "_keys"} and rows[1]["j"] is None    # wide JSON is previewed
    assert rows[1]["s"].endswith("[400 chars]") and len(rows[1]["s"]) < 400
    assert rows[0]["n"] == 3 and rows[1]["n"] is None and rows[0]["b"] is True and rows[1]["b"] is False
    json.dumps(rows)
    assert P.plain({"a": list(range(200))}, preview=False) == {"a": list(range(200))}   # whole on request


def test_page_columns_subset_and_describe():
    df = pd.DataFrame(dict(a=[1, 2], b=["x", "y"], c=[0.5, None]))
    out = P.page(df, columns=["b", "zz"])
    assert out["columns"] == ["b"] and out["rows"] == [{"b": "x"}, {"b": "y"}] and "zz" in out["note"]
    d = P.describe(df)
    assert d["count"] == 2 and [c["name"] for c in d["columns"]] == ["a", "b", "c"]
    assert d["columns"][2]["nulls"] == 1 and d["columns"][1]["values"] == {"x": 1, "y": 1}


# --- the sql guard (no database) --------------------------------------------------------------------

@pytest.mark.parametrize("q", ["SELECT 1", "with x as (select 1) select * from x", "  select * from events; ",
                               "-- a note\nselect count(*) from results", "explain select 1",
                               "select 1 /* ; drop table x */"])
def test_sql_guard_accepts_reads(q):
    assert T.check_sql(q)


@pytest.mark.parametrize("q,why", [
    ("delete from jobs", "only SELECT"), ("select 1; drop table jobs", "one statement"),
    ("with d as (delete from jobs returning 1) select * from d", "read-only"), ("select * from users", "users"),
    ("select o.id from orders o", "orders"), ("select pg_sleep(10)", "read-only"), ("", "empty"),
    ("set statement_timeout = 0", "only SELECT"), ("select 1 union select lo_import('/etc/passwd')", "read-only"),
])
def test_sql_guard_refuses_writes_and_hidden_tables(q, why):
    with pytest.raises(ValueError, match=why):
        T.check_sql(q)


@pytest.mark.parametrize("q", [
    'select * from U&"\\0075sers"',                                          # a Unicode-escaped table name
    "select query_to_xml('select password_hash from us'||'ers', true, true, '')",  # a query hidden in a string
    "select pg_read_binary_file('/etc/passwd')", "select pg_stat_file('/etc/passwd')",
    "select set_config('role', 'racinglines', true)", "select * from ts_stat('select 1')",
    "select rolpassword from pg_authid", "select passwd from pg_catalog.pg_shadow",
    "select E'\\'', pg_read_binary_file('/etc/passwd'), ''",                  # an escaped quote must not hide code
    "select $q$x$q$, lo_get(1)",
])
def test_sql_guard_refuses_known_bypasses(q):
    """The audit's bypasses (2026-10-05) and their kin. The guard is a first filter; the sql tool's own database role
    (scripts/vm/mcp_sql_role.sh) is what keeps users and orders out of reach."""
    with pytest.raises(ValueError):
        T.check_sql(q)


@pytest.mark.parametrize("q", [
    "select * from model_runs where variant = 'gridq+pretrain+reset'",  # a keyword inside a value
    "select $$delete me$$ as note", "select E'it''s', 'update' as word",
])
def test_sql_guard_reads_keywords_in_values_as_values(q):
    assert T.check_sql(q)


def test_sql_role_script_hides_the_same_tables():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "scripts/vm/mcp_sql_role.sh").read_text()
    hidden = next(line for line in script.splitlines() if line.startswith("HIDDEN="))
    assert hidden.split("=", 1)[1].strip('"').split() == list(T.SQL_HIDDEN)


def test_sql_tool_uses_its_own_login_when_set(monkeypatch):
    from racinglines.mcp import server as S
    monkeypatch.setenv("RACINGLINES_MCP_SQL_URL", "postgresql+psycopg://racinglines_mcp_ro:pw@localhost:5433/racinglines")
    assert S._sql_engine().url.username == "racinglines_mcp_ro"
    monkeypatch.delenv("RACINGLINES_MCP_SQL_URL")
    assert S._sql_engine().url.username != "racinglines_mcp_ro"


def test_job_params_validated_against_the_lab_catalog():
    jt, p = T._job_params("f1_backtest", {"races": 5, "sims": 300, "track": "on"})
    assert jt.code == "f1_backtest" and p == {"races": 5, "half_life": 120.0, "sims": 300, "track": "on"}
    jt, p = T._job_params("f1_sweep", {"year": "2025", "settings": {"half_spread": 0.03, "variant": "gridq"}})
    assert p == {"year": "2025", "settings": {"variant": "gridq", "half_spread": 0.03}}
    with pytest.raises(ValueError, match="unknown knobs"):
        T._job_params("f1_backtest", {"races": 5, "bogus": 1})
    with pytest.raises(ValueError, match="unknown job type"):
        T._job_params("f1_nope", {})
    with pytest.raises(ValueError, match="between"):
        T._job_params("f1_backtest", {"races": 0})
    with pytest.raises(ValueError):
        T._job_params("f1_sweep", {"year": "2026", "settings": {"variant": "nope"}})
    assert {j["job_type"] for j in T.list_job_types()["job_types"]} >= {"f1_backtest", "f1_sweep", "dh_backtest"}


# --- a client round trip on the test database ---------------------------------------------------------

@pytest.fixture(scope="module")
def mcp(test_engine):
    """`mcp(name, **args)` calls one tool on a server bound to the (empty) test database over an in-memory
    transport and returns the parsed JSON, or ("error", text) for a tool error; `mcp.run(coro_fn)` runs a
    coroutine with the connected client for anything else (list_tools, resources)."""
    from mcp import Client
    from racinglines.mcp import server as S
    url = test_engine.url.render_as_string(hide_password=False)

    def run(fn):
        async def go():
            async with Client(S.build(engine_url=url)) as client:
                return await fn(client)
        return asyncio.run(go())

    def call(name, **args):
        async def go(client):
            r = await client.call_tool(name, args)
            text = r.content[0].text
            return ("error", text) if r.is_error else json.loads(text)
        return run(go)

    call.run, call.engine = run, test_engine
    try:
        yield call
    finally:
        S._URL = None


def test_tools_are_registered_with_descriptions(mcp):
    async def go(client):
        return (await client.list_tools()).tools
    tools = mcp.run(go)
    names = {t.name for t in tools}
    assert names >= {"overview", "list_events", "list_markets", "get_market_history", "sql", "run_job", "get_job", "replay_maker",
                     "edge_finder", "track_record", "describe_schema", "list_kinds", "map_book", "price_book",
                     "settle_book"}
    assert all(t.description for t in tools)
    lm = next(t for t in tools if t.name == "list_markets")
    assert "race_id" in lm.input_schema["properties"] and lm.input_schema["properties"]["limit"]["default"] == 50


def test_reads_on_the_test_database(mcp):
    """The test database is empty, or holds what earlier test modules ingested: the shapes hold either way."""
    ov = mcp("overview")
    assert {v["code"] for v in ov["venues"]} >= {"polymarket", "private"} and ov["row_counts"]["events"] >= 0
    assert set(ov) >= {"seasons", "forecasts", "model_runs", "market_links", "users", "upcoming", "hint"}
    ev = mcp("list_events", competition="f1_wdc", limit=5)
    assert len(ev["rows"]) <= 5 and ev["total"] >= len(ev["rows"]) and ev["limit"] == 5
    sc = mcp("describe_schema", table="model_runs")
    assert sc["rows"] >= 0 and "params" in {c["name"] for c in sc["columns"]}
    assert mcp("describe_schema")["tables"][0]["table"] == "sports"
    assert "forecasts" in mcp("get_forecast", competition="f1_wdc")
    assert mcp("edge_finder", year=2026)["configurations"] >= 0
    kind, text = mcp("describe_schema", table="nope")
    assert kind == "error" and "no table" in text


def test_sports_come_from_the_database(mcp):
    """Any sport with a competition row is reachable by its code (no list in the code); an unknown one says what exists."""
    from sqlalchemy import text
    with mcp.engine.begin() as c:
        c.execute(text("INSERT INTO sports (code, name, result_kind) VALUES ('kart_test', 'Karting', 'time') ON CONFLICT DO NOTHING"))
        c.execute(text("INSERT INTO leagues (code, name) VALUES ('kart_test_lg', 'Karting league') ON CONFLICT DO NOTHING"))
        c.execute(text("""INSERT INTO competitions (code, name, league_id, sport_id)
                          SELECT 'kart_test_cup', 'Karting cup', l.id, s.id FROM leagues l, sports s
                          WHERE l.code = 'kart_test_lg' AND s.code = 'kart_test' ON CONFLICT DO NOTHING"""))
        assert T.sports_of(c)["kart_test_cup"] == "kart_test"
        assert T._sport_filter(c, sport="kart_test") == "kart_test_cup"
        assert T._sport_filter(c, sport="kart_test_cup") == "kart_test_cup"
        assert T._sport_filter(c, competition="anything") == "anything" and T._sport_filter(c) is None
        with pytest.raises(ValueError, match="no sport 'curling'"):
            T._sport_filter(c, sport="curling")
    assert mcp("overview")["sports"]["kart_test_cup"] == "kart_test"
    assert mcp("list_events", sport="kart_test")["rows"] == []
    kind, text_ = mcp("list_events", sport="curling")
    assert kind == "error" and "kart_test" in text_


def test_edge_finder_and_track_record_take_venue_and_sport(mcp):
    assert mcp("edge_finder", year=2026, venue="kalshi")["venue"] == "kalshi"
    kind, text_ = mcp("edge_finder", year=2026, venue="nope")
    assert kind == "error" and "polymarket" in text_


def test_errors_reach_the_client_as_text(mcp):
    kind, text = mcp("get_event", event_id=424242)
    assert kind == "error" and "no event 424242" in text
    kind, text = mcp("sql", query="delete from jobs")
    assert kind == "error" and "only SELECT" in text
    kind, text = mcp("sql", query="select * from users")
    assert kind == "error" and "users" in text
    kind, text = mcp("track_record", user="nobody")
    assert kind == "error" and "no user" in text
    kind, text = mcp("list_markets")
    assert kind == "error" and "race_id" in text


def test_sql_is_read_only_and_paged(mcp):
    from sqlalchemy import text
    with mcp.engine.begin() as c:
        c.execute(text("INSERT INTO sports (code, name, result_kind) VALUES ('t_a', 'A', 'time'), ('t_b', 'B', 'time'), ('t_c', 'C', 'time')"
                       " ON CONFLICT DO NOTHING"))
    out = mcp("sql", query="select code from sports where code like 't_%' order by code", limit=2)
    assert [r["code"] for r in out["rows"]] == ["t_a", "t_b"] and out["truncated"] and out["next_offset"] == 2
    out = mcp("sql", query="select code from sports where code like 't_%' order by code", limit=2, offset=2)
    assert [r["code"] for r in out["rows"]] == ["t_c"] and not out["truncated"]
    kind, text = mcp("sql", query="select nextval('jobs_id_seq')")          # passes the word list; Postgres refuses it
    assert kind == "error" and "read-only" in text.lower()
    assert mcp("sql", query="explain select 1")["plan"]


def test_jobs_queue_and_cancel_without_running(mcp):
    out = mcp("run_job", job_type="f1_backtest", params={"races": 3, "sims": 300, "track": "on"})
    assert out["status"] == "queued" and out["params"]["races"] == 3
    job = mcp("get_job", job_id=out["job_id"])
    assert job["status"] == "queued" and job["user_id"] is None                       # no worker in the tests
    assert mcp("list_jobs")["rows"][0]["id"] == out["job_id"]
    assert mcp("cancel_job", job_id=out["job_id"])["cancelled"] is True
    assert mcp("get_job", job_id=out["job_id"])["status"] == "failed"
    assert mcp("cancel_job", job_id=out["job_id"])["cancelled"] is False
    kind, text = mcp("run_job", job_type="f1_backtest", params={"races": 3, "nope": 1})
    assert kind == "error" and "unknown knobs" in text
    assert "job_types" in mcp("list_job_types")


def test_docs_are_resources(mcp):
    async def go(client):
        index = (await client.read_resource("racinglines://docs")).contents[0].text
        page = (await client.read_resource("racinglines://docs/model.md")).contents[0].text
        sport = (await client.read_resource("racinglines://sports/f1")).contents[0].text
        return index, page, sport
    index, page, sport = mcp.run(go)
    assert "model.md" in index.split() and page.startswith("# ") and 'code = "f1"' in sport


# --- per-account tokens for the hosted mode -----------------------------------------------------------

def test_tokens_are_per_account_and_only_for_allowed_real_accounts(test_engine, monkeypatch):
    from sqlalchemy import text
    from racinglines.mcp import auth
    from racinglines.web import users as U
    from racinglines.db.config import get_session
    from sqlalchemy.orm import sessionmaker
    with sessionmaker(test_engine)() as s:
        for name, role, active in (("t_admin", "admin", True), ("t_maker", "pro", True), ("t_gone", "admin", False)):
            if not s.execute(text("SELECT 1 FROM users WHERE username = :u"), dict(u=name)).first():
                U.create_user(s, name, "pw", role)
        s.execute(text("UPDATE users SET active = false WHERE username = 't_gone'"))
        s.commit()
    tok = auth.new_token(test_engine, "t_admin")
    assert tok.startswith("rl_") and len(tok) == 51
    with test_engine.connect() as c:
        stored = c.execute(text("SELECT prefs->'mcp' FROM users WHERE username = 't_admin'")).scalar()
    assert tok not in str(stored) and stored["token_sha256"]                        # only the hash is kept
    assert auth.lookup(test_engine, tok) == dict(id=auth.lookup(test_engine, tok)["id"], username="t_admin", role="admin")
    assert auth.lookup(test_engine, "rl_" + "0" * 48) is None and auth.lookup(test_engine, "") is None
    tok2 = auth.new_token(test_engine, "t_admin")                                     # re-issue voids the old one
    assert auth.lookup(test_engine, tok) is None and auth.lookup(test_engine, tok2)["username"] == "t_admin"
    pro_token = auth.new_token(test_engine, "t_maker")
    assert auth.lookup(test_engine, pro_token)["role"] == "pro"
    monkeypatch.setattr(auth, "ROLES", ("admin",))
    assert auth.lookup(test_engine, pro_token) is None
    with pytest.raises(ValueError, match="role"):
        auth.new_token(test_engine, "t_maker")                                        # explicit admin-only override
    with pytest.raises(ValueError, match="inactive"):
        auth.new_token(test_engine, "t_gone")
    with pytest.raises(ValueError, match="no account"):
        auth.new_token(test_engine, "t_nobody")
    assert ("t_admin", "admin") in {(u, r) for u, r, _ in auth.holders(test_engine)}
    assert auth.revoke(test_engine, "t_admin") and not auth.revoke(test_engine, "t_admin")
    assert auth.lookup(test_engine, tok2) is None


@pytest.mark.parametrize("username,role", [("t_demo", "admin"), ("maker", "pro")])
def test_demo_accounts_never_get_a_token(test_engine, monkeypatch, username, role):
    from racinglines.mcp import auth, oauth
    from racinglines.web import demo, users as U
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    monkeypatch.setattr(demo, "DEMO_USERS", set())
    with sessionmaker(test_engine)() as s:
        if not s.execute(text("SELECT 1 FROM users WHERE username = :u"), dict(u=username)).first():
            U.create_user(s, username, "pw", role)
        s.commit()
    token = auth.new_token(test_engine, username)
    monkeypatch.setattr(demo, "DEMO_USERS", {username})
    with pytest.raises(ValueError, match="demo"):
        auth.new_token(test_engine, username)
    assert auth.lookup(test_engine, token) is None
    assert oauth.account(test_engine, username=username) is None


def test_pro_mcp_scopes_accounts_and_jobs_and_blocks_admin_tools(mcp, monkeypatch):
    from sqlalchemy import text
    from racinglines.mcp import server as S
    with mcp.engine.begin() as c:
        ids = {}
        for name in ("mcp-pro-own", "mcp-pro-other"):
            uid = c.execute(text("""INSERT INTO users (username, password_hash, role) VALUES (:n, 'x', 'pro')
                                    RETURNING id"""), dict(n=name)).scalar()
            ids[name] = uid
            c.execute(text("""INSERT INTO paper_positions
                (user_id, event_key, market_key, kind, subject, yes_shares, cash, outcome, venue)
                VALUES (:u, '2099-02', :n, 'race_win', :subject, 0, 5, true, 'polymarket')"""),
                      dict(u=uid, n=name, subject=name))
            c.execute(text("""INSERT INTO strategy_signals
                (user_id, profile, strategy, event_key, market_key, kind, subject, stage, dedupe,
                 action, side, status, signal_ts, detail)
                VALUES (:u, 'test', 'maker', '2099-02', :n, 'race_win', :subject,
                        'after FP2', :dedupe, 'quote', 'bid', 'new', now(), '{"venue":"polymarket"}'::jsonb)"""),
                      dict(u=uid, n=name, subject=name, dedupe=name))
    try:
        who = dict(id=ids["mcp-pro-own"], username="mcp-pro-own", role="pro")
        monkeypatch.setattr(S, "caller", lambda: who)
        ov = mcp("overview")
        assert [r["username"] for r in ov["users"]] == ["mcp-pro-own"]
        assert ov["row_counts"]["paper_positions"] == 1
        own = mcp("list_positions", user="mcp-pro-own")
        assert own["positions"]["total"] == 1
        signals = mcp("list_signals")
        assert signals["total"] == 1 and signals["rows"][0]["user"] == "mcp-pro-own"
        record = mcp("track_record", user="mcp-pro-own")
        assert record["user"] == "mcp-pro-own" and record["pnl"] == 5
        for name in ("list_positions", "track_record", "list_signals"):
            denied = mcp(name, user="mcp-pro-other")
            assert denied[0] == "error" and "own account" in denied[1]
        for name, args in (("sql", dict(query="SELECT * FROM paper_positions")),
                           ("describe_schema", {}), ("data_changes", {})):
            denied = mcp(name, **args)
            assert denied[0] == "error" and "admin-only" in denied[1]
        mine = mcp("run_job", job_type="f1_backtest", params=dict(races=3, sims=300))
        other = T.run_job(mcp.engine, "f1_backtest", dict(races=3, sims=300), user_id=ids["mcp-pro-other"])
        assert mcp("get_job", job_id=mine["job_id"])["user_id"] == who["id"]
        assert {r["id"] for r in mcp("list_jobs")["rows"]} == {mine["job_id"]}
        for name in ("get_job", "cancel_job"):
            assert mcp(name, job_id=other["job_id"])[0] == "error"
        assert mcp("cancel_job", job_id=mine["job_id"])["cancelled"]
        with mcp.engine.connect() as c:
            assert c.execute(text("SELECT status FROM jobs WHERE id = :i"), dict(i=other["job_id"])).scalar() == "queued"
        who["role"] = "admin"
        assert mcp("list_positions", user="mcp-pro-other")["positions"]["total"] == 1
        assert mcp("sql", query="SELECT 1 AS n")["rows"][0]["n"] == 1
    finally:
        with mcp.engine.begin() as c:
            for uid in ids.values():
                c.execute(text("DELETE FROM jobs WHERE user_id = :u"), dict(u=uid))
                c.execute(text("DELETE FROM users WHERE id = :u"), dict(u=uid))


def test_pro_market_matrix_uses_own_book_and_event_propagates_viewer(monkeypatch):
    from racinglines.markets import private_book as house
    from racinglines.markets import venues as V
    own = dict(id=11, username="pro", role="pro")
    seen = []

    def matrix(conn, race_id, maker_id=house.ALL):
        seen.append(maker_id)
        return dict(event_id=1, title="race", competition="f1_wdc", season=2026, status="scheduled",
                    start_date=None, race_start=None), {}, pd.DataFrame()

    monkeypatch.setattr(V, "event_matrix", matrix)
    monkeypatch.setattr(T, "freshness", lambda *args, **kwargs: {})
    T.list_markets(None, race_id=1, viewer=own)
    T.list_markets(None, race_id=1, viewer=dict(own, role="admin"))
    assert seen == [11, house.ALL]
    monkeypatch.setattr(T.data, "event", lambda *args: {"id": 1})
    monkeypatch.setattr(T.data, "q", lambda *args, **kwargs: pd.DataFrame([dict(race_id=1)]))
    T.get_event(None, event_id=1, include="markets", viewer=own)
    assert seen[-1] == 11


def _http(test_engine, monkeypatch):
    """The hosted server (OAuth on) bound to the test database, as a TestClient on the public hostname."""
    from starlette.testclient import TestClient
    from racinglines.mcp import server as S
    monkeypatch.setenv("APP_SECRET", "test-secret")
    url = test_engine.url.render_as_string(hide_password=False)
    return TestClient(S.http_app(S.build(engine_url=url, oauth=True)), base_url="https://mcp.racinglines.bet")


def test_hosted_server_stops_within_its_grace_period(monkeypatch):
    """A restart (every deploy) must not wait on a client's open event stream: serve() gives uvicorn a finite graceful
    shutdown, and every unit's TimeoutStopSec leaves systemd a margin above it instead of the 90 s default."""
    import re
    from pathlib import Path
    import uvicorn
    from racinglines.cli import web as W
    from racinglines.mcp import auth, oauth
    from racinglines.mcp import server as S
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    monkeypatch.setattr(S, "build", lambda **kw: object())
    monkeypatch.setattr(S, "http_app", lambda srv: srv)
    monkeypatch.setattr(S, "_engine", lambda: None)
    monkeypatch.setattr(auth, "holders", lambda e: [])
    monkeypatch.setattr(oauth, "warn_if_disabled", lambda: None)
    S.serve(http=True)
    assert 0 < seen["timeout_graceful_shutdown"] == S.SHUTDOWN_GRACE_SEC
    seen.clear()
    W.main()
    assert 0 < seen["timeout_graceful_shutdown"] == W.SHUTDOWN_GRACE_SEC
    units = Path(__file__).resolve().parent.parent / "deploy/vm/systemd"
    for name, grace in [("racinglines-mcp.service", S.SHUTDOWN_GRACE_SEC), ("racinglines-web.service", W.SHUTDOWN_GRACE_SEC),
                        ("racinglines-staging-web.service", W.SHUTDOWN_GRACE_SEC)]:
        m = re.search(r"^TimeoutStopSec=(\d+)$", (units / name).read_text(), re.M)
        assert m and grace < int(m.group(1)) < 90, name


PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
HDR = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def test_rl_tokens_still_open_the_hosted_server(test_engine, monkeypatch):
    """Behind the tunnel the Host header is the public name (the SDK's localhost-only guard would give 421): no token
    or a wrong one is 401 with the OAuth discovery header; an account's rl_ token is 200 until revoked."""
    from racinglines.mcp import auth
    tok = auth.new_token(test_engine, "t_admin")
    with _http(test_engine, monkeypatch) as client:
        r = client.post("/mcp", json=PING, headers=HDR)
        assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]
        assert client.post("/mcp", json=PING, headers={**HDR, "Authorization": "Bearer rl_nope"}).status_code == 401
        assert client.post("/mcp", json=PING, headers={**HDR, "Authorization": f"Bearer {tok}"}).status_code == 200
        auth.revoke(test_engine, "t_admin")
        assert client.post("/mcp", json=PING, headers={**HDR, "Authorization": f"Bearer {tok}"}).status_code == 401


@pytest.mark.parametrize("account_role", ["admin", "pro"])
def test_oauth_sign_in_from_register_to_refresh(test_engine, monkeypatch, account_role):
    """The connector flow: register, /authorize to the web app's Allow page, Allow as a signed-in admin, code for
    tokens (once), a tool call as that account, refresh, and Disconnect ending it all. Basic accounts get no Allow."""
    import base64
    import hashlib
    from urllib.parse import parse_qs, urlparse
    from fastapi import Request
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from racinglines.mcp import oauth
    from racinglines.web import app as A
    from racinglines.web import users as U
    with sessionmaker(test_engine)() as s:
        for name, role in (("t_admin", "admin"), ("t_maker", "pro"), ("t_basic", "basic")):
            if not s.execute(text("SELECT 1 FROM users WHERE username = :u"), dict(u=name)).first():
                U.create_user(s, name, "pw", role)
        s.commit()
        ids = dict(s.execute(text("SELECT username, id FROM users WHERE username IN ('t_admin', 't_maker', 't_basic')")).fetchall())
    monkeypatch.setattr(A, "get_engine", lambda *a: test_engine)
    monkeypatch.setattr(A, "get_session", lambda *a: sessionmaker(test_engine, expire_on_commit=False)())
    who = {}

    def as_user(request: Request):
        request.state.user = dict(id=ids[who["u"]], username=who["u"], role=who["r"], sid=None)
        return request.state.user
    A.app.dependency_overrides[A.authenticate] = as_user
    A.app.dependency_overrides[A.conn] = lambda: None
    cb = "https://claude.ai/api/mcp/auth_callback"
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    try:
        web = TestClient(A.app, base_url="https://racinglines.bet")
        with _http(test_engine, monkeypatch) as mcp_http:
            meta = mcp_http.get("/.well-known/oauth-authorization-server").json()
            assert meta["issuer"].rstrip("/") == "https://mcp.racinglines.bet" and meta["registration_endpoint"]
            reg = mcp_http.post("/register", json=dict(redirect_uris=[cb], client_name="Claude",
                                                       token_endpoint_auth_method="none"))
            assert reg.status_code == 201, reg.text
            client_id = reg.json()["client_id"]
            assert oauth.unsign("client", client_id)                                   # signed, nothing stored

            def authorize():
                r = mcp_http.get("/authorize", params=dict(response_type="code", client_id=client_id, redirect_uri=cb,
                                                           code_challenge=challenge, code_challenge_method="S256",
                                                           state="st8"), follow_redirects=False)
                assert r.status_code == 302, r.text
                loc = r.headers["location"]
                assert loc.startswith("https://racinglines.bet/mcp/authorize?req=")
                return parse_qs(urlparse(loc).query)["req"][0]

            req = authorize()
            who.update(u="t_basic", r="basic")
            assert "isn't one" in web.get("/mcp/authorize", params=dict(req=req)).text
            assert web.post("/mcp/authorize", data=dict(csrf_token=A.CSRF_TOKEN, req=req, decision="allow"),
                            follow_redirects=False).status_code == 403
            account_name = "t_admin" if account_role == "admin" else "t_maker"
            who.update(u=account_name, r=account_role)
            page = web.get("/mcp/authorize", params=dict(req=req))
            assert "Allow" in page.text and page.headers["x-frame-options"] == "DENY"
            r = web.post("/mcp/authorize", data=dict(csrf_token=A.CSRF_TOKEN, req=req, decision="allow"), follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"].startswith(cb)
            q = parse_qs(urlparse(r.headers["location"]).query)
            assert q["state"] == ["st8"]
            form = dict(grant_type="authorization_code", code=q["code"][0], redirect_uri=cb, client_id=client_id,
                        code_verifier=verifier)
            tok = mcp_http.post("/token", data=form)
            assert tok.status_code == 200, tok.text
            assert mcp_http.post("/token", data=form).status_code == 400                # a code works once
            at, rt = tok.json()["access_token"], tok.json()["refresh_token"]
            auth_hdr = {**HDR, "Authorization": f"Bearer {at}"}
            assert mcp_http.post("/mcp", json=PING, headers=auth_hdr).status_code == 200
            call = dict(jsonrpc="2.0", id=2, method="tools/call",
                        params=dict(name="run_job", arguments=dict(job_type="f1_backtest", params=dict(races=3, sims=300))))
            out = mcp_http.post("/mcp", json=call, headers=auth_hdr).json()
            job = json.loads(out["result"]["content"][0]["text"])
            with test_engine.connect() as c:                                            # filed under the signed-in account
                assert c.execute(text("SELECT user_id FROM jobs WHERE id = :i"), dict(i=job["job_id"])).scalar() == ids[account_name]
            assert "Claude" in web.get("/settings").text
            ref = mcp_http.post("/token", data=dict(grant_type="refresh_token", refresh_token=rt, client_id=client_id))
            assert ref.status_code == 200, ref.text
            at2 = ref.json()["access_token"]
            assert web.post("/api/settings/mcp/disconnect", data=dict(csrf_token=A.CSRF_TOKEN)).status_code == 200
            for t in (at, at2):
                assert mcp_http.post("/mcp", json=PING, headers={**HDR, "Authorization": f"Bearer {t}"}).status_code == 401
            assert mcp_http.post("/token", data=dict(grant_type="refresh_token", refresh_token=ref.json()["refresh_token"],
                                                     client_id=client_id)).status_code == 400
            r = web.post("/mcp/authorize", data=dict(csrf_token=A.CSRF_TOKEN, req=authorize(), decision="deny"),
                         follow_redirects=False)
            assert "error=access_denied" in r.headers["location"]
    finally:
        A.app.dependency_overrides.clear()


def test_admin_mcp_page_lists_and_disconnects(test_engine, monkeypatch):
    from fastapi import Request
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from racinglines.mcp import auth, oauth
    from racinglines.web import admin as AD
    from racinglines.web import app as A
    monkeypatch.setenv("APP_SECRET", "test-secret")
    tok = auth.new_token(test_engine, "t_admin")
    with test_engine.connect() as c:
        uid = c.execute(text("SELECT id FROM users WHERE username = 't_admin'")).scalar()
    oauth._seen(test_engine, uid, "Claude")
    monkeypatch.setattr(AD, "get_engine", lambda *a: test_engine)
    monkeypatch.setattr(A, "get_engine", lambda *a: test_engine)

    def as_admin(request: Request):
        request.state.user = dict(id=uid, username="t_admin", role="admin", sid=None)
        return request.state.user
    A.app.dependency_overrides[A.authenticate] = as_admin
    A.app.dependency_overrides[A.conn] = lambda: None
    try:
        web = TestClient(A.app)
        page = web.get("/admin/mcp").text
        assert "t_admin" in page and "Claude" in page and "Disconnect everyone" in page
        gen = oauth.account(test_engine, user_id=uid)["gen"]
        r = web.post("/admin/mcp", data=dict(csrf_token=A.CSRF_TOKEN, action="disconnect_all"))
        assert r.status_code == 200 and oauth.account(test_engine, user_id=uid)["gen"] == gen + 1
        assert auth.lookup(test_engine, tok)                                             # the rl_ token is separate
        web.post("/admin/mcp", data=dict(csrf_token=A.CSRF_TOKEN, action="revoke_token", username="t_admin"))
        assert auth.lookup(test_engine, tok) is None
    finally:
        A.app.dependency_overrides.clear()


def test_track_record_all_lists_one_row_per_weekend_and_venue(mcp):
    """venue='all': the maker's weekend (Polymarket fills and a Kalshi replay of the same tape) shows as two
    rows with a venue column, totals per venue add up to the grand total; the default venue keeps its shape."""
    from sqlalchemy import text as T
    with mcp.engine.begin() as c:
        uid = c.execute(T("""INSERT INTO users (username, password_hash, role) VALUES ('mcp-maker', 'x', 'maker')
                             ON CONFLICT (username) DO UPDATE SET role = 'maker' RETURNING id""")).scalar()
        for venue, pnl in (("polymarket", 3.0), ("kalshi", -1.0)):
            c.execute(T("""INSERT INTO strategy_signals (user_id, profile, strategy, event_key, market_key, kind, subject, stage,
                             dedupe, action, side, shares, limit_price, fair, price, edge, heat, status, signal_ts, detail)
                           VALUES (:u, 'test', 'maker', '2099-02', :mk, 'race_winner', 'Zed', 'after FP2', :mk, 'fill', 'YES',
                             10, 0.4, 0.5, 0.4, 0.1, 1, 'done', now(), CAST(:d AS jsonb))"""),
                      dict(u=uid, mk=f"tok-{venue}", d=json.dumps(dict(venue=venue))))
            c.execute(T("""INSERT INTO paper_positions (user_id, event_key, market_key, kind, subject, yes_shares, cash, outcome, venue)
                           VALUES (:u, '2099-02', :mk, 'race_winner', 'Zed', 0, :pnl, true, :v)"""),
                      dict(u=uid, mk=f"tok-{venue}", pnl=pnl, v=venue))
    try:
        out = mcp("track_record", user="mcp-maker", venue="all")
        rows = out["rows"]["rows"]
        assert [(r["event_key"], r["venue"], r["pnl"]) for r in rows] == [("2099-02", "polymarket", 3.0), ("2099-02", "kalshi", -1.0)]
        assert out["weekends"] == 1 and out["pnl"] == 2.0 and out["up"] == 1  # one weekend, two rows
        assert out["totals"] == [dict(venue="polymarket", weekends=1, pnl=3.0, up=1), dict(venue="kalshi", weekends=1, pnl=-1.0, up=0)]
        default = mcp("track_record", user="mcp-maker")
        assert "totals" not in default and "venue" not in default["rows"]["rows"][0]
        assert default["weekends"] == 1 and default["pnl"] == 3.0 and default["rows"]["rows"][0]["fills"] == 1
        assert mcp("track_record", user="mcp-maker", sport="nascar")["weekends"] == 0    # no NASCAR weekend here
    finally:
        with mcp.engine.begin() as c:
            c.execute(T("DELETE FROM users WHERE username = 'mcp-maker'"))


def test_settings_page_token_is_the_one_the_server_accepts(test_engine, monkeypatch):
    """The Settings page issues the server's own token (auth.new_token), Save Settings keeps it, and the token
    endpoints need the CSRF field like every other POST."""
    from fastapi import Request
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from racinglines.mcp import auth
    from racinglines.web import app as A
    from racinglines.web import users as U
    with sessionmaker(test_engine)() as s:
        for name, role in (("t_admin", "admin"), ("t_maker", "pro")):
            if not s.execute(text("SELECT 1 FROM users WHERE username = :u"), dict(u=name)).first():
                U.create_user(s, name, "pw", role)
        s.commit()
        ids = dict(s.execute(text("SELECT username, id FROM users WHERE username IN ('t_admin', 't_maker')")).fetchall())
    monkeypatch.setattr(A, "get_engine", lambda *a: test_engine)
    monkeypatch.setattr(A, "get_session", lambda *a: sessionmaker(test_engine, expire_on_commit=False)())
    who = {}

    def as_user(request: Request):
        request.state.user = dict(id=ids[who["u"]], username=who["u"], role=who["r"], sid=None)
        return request.state.user
    A.app.dependency_overrides[A.authenticate] = as_user
    A.app.dependency_overrides[A.conn] = lambda: None
    try:
        client = TestClient(A.app)
        who.update(u="t_admin", r="admin")
        assert client.post("/api/settings/token/generate").status_code == 422             # no CSRF field
        r = client.post("/api/settings/token/generate", data=dict(csrf_token=A.CSRF_TOKEN))
        assert r.status_code == 200 and r.json()["url"].endswith("/mcp")
        tok = r.json()["token"]
        assert auth.lookup(test_engine, tok)["username"] == "t_admin"
        r = client.post("/settings", data=dict(csrf_token=A.CSRF_TOKEN, email="a@b.co", exchange="kalshi", sports=["f1"]))
        assert r.status_code == 200
        assert auth.lookup(test_engine, tok)["username"] == "t_admin"                     # saving settings keeps the token
        page = client.get("/settings").text
        assert "a@b.co" in page and "You have a token" in page
        assert client.post("/api/settings/token/revoke", data=dict(csrf_token=A.CSRF_TOKEN)).status_code == 200
        assert auth.lookup(test_engine, tok) is None
        with test_engine.connect() as c:
            assert c.execute(text("SELECT prefs->>'email' FROM users WHERE username = 't_admin'")).scalar() == "a@b.co"
        who.update(u="t_maker", r="pro")
        pro_token = client.post("/api/settings/token/generate", data=dict(csrf_token=A.CSRF_TOKEN))
        assert pro_token.status_code == 200
        assert auth.lookup(test_engine, pro_token.json()["token"])["username"] == "t_maker"
        monkeypatch.setattr(auth, "ROLES", ("admin",))                                    # explicit admin-only override
        assert client.post("/api/settings/token/generate", data=dict(csrf_token=A.CSRF_TOKEN)).status_code == 403
        assert "open to admin accounts" in client.get("/settings").text
    finally:
        A.app.dependency_overrides.clear()


def test_list_markets_flags_stale_or_missing_exchange_prices(mcp, monkeypatch):
    """freshness: per exchange, the newest synced_at over the event's links. An upcoming event with no link on a live
    exchange, or a newest sync older than RACINGLINES_STALE_HOURS, is flagged; a completed one never is."""
    from datetime import timedelta

    import pandas as pd
    from sqlalchemy import text
    now = pd.Timestamp("2026-10-07T21:00Z")
    with mcp.engine.begin() as c:
        c.execute(text("INSERT INTO sports (code, name, result_kind) VALUES ('fresh_t', 'Fresh', 'time') ON CONFLICT DO NOTHING"))
        c.execute(text("INSERT INTO leagues (code, name) VALUES ('fresh_t_lg', 'Fresh league') ON CONFLICT DO NOTHING"))
        comp = c.execute(text("""INSERT INTO competitions (code, name, league_id, sport_id)
                                 SELECT 'fresh_t_cup', 'Fresh cup', l.id, s.id FROM leagues l, sports s
                                 WHERE l.code = 'fresh_t_lg' AND s.code = 'fresh_t' RETURNING id""")).scalar()
        cat = c.execute(text("INSERT INTO categories (competition_id, code, name) VALUES (:c, 'DRV', 'Drivers') RETURNING id"),
                        dict(c=comp)).scalar()
        season = c.execute(text("INSERT INTO seasons (competition_id, year) VALUES (:c, 2026) RETURNING id"), dict(c=comp)).scalar()
        ev = c.execute(text("""INSERT INTO events (season_id, source, source_key, name, start_date)
                               VALUES (:s, 't', 'fresh-1', 'Fresh GP', '2026-10-11') RETURNING id"""), dict(s=season)).scalar()
        race = c.execute(text("INSERT INTO races (event_id, category_id) VALUES (:e, :c) RETURNING id"),
                         dict(e=ev, c=cat)).scalar()
        for ex, hours in (("polymarket", 1), ("polymarket", 30), ("og", 5)):
            c.execute(text("""INSERT INTO market_links (exchange, question, token_id, outcome, competition_id, race_id, prediction,
                                                        synced_at) VALUES (:x, 'q', :t, 'Yes', :c, :r, 'race_win', :at)"""),
                      dict(x=ex, t=f"fresh-{ex}-{hours}", c=comp, r=race, at=(now - timedelta(hours=hours)).to_pydatetime()))
        f = T.freshness(c, event_id=ev, now=now)
        by = {v["venue"]: v for v in f["venues"]}
        assert f["stale_hours"] == 3 and f["any_stale"]
        assert by["polymarket"]["links"] == 2 and by["polymarket"]["age_hours"] == 1 and not by["polymarket"]["stale"]
        assert by["og"]["stale"] and by["og"]["reason"] == "newest sync 5.0 h old (limit 3 h)"
        monkeypatch.setenv("RACINGLINES_STALE_HOURS", "6")
        f = T.freshness(c, event_id=ev, now=now)
        assert f["stale_hours"] == 6 and not {v["venue"]: v for v in f["venues"]}["og"]["stale"]
        empty = c.execute(text("""INSERT INTO events (season_id, source, source_key, name, start_date)
                                  VALUES (:s, 't', 'fresh-2', 'Bare GP', '2026-10-18') RETURNING id"""), dict(s=season)).scalar()
        bare = T.freshness(c, event_id=empty, now=now)["venues"]
        assert bare and all(v["stale"] and v["reason"] == "no linked markets" for v in bare)
        assert not T.freshness(c, event_id=ev, upcoming=False, now=now)["any_stale"]
        out = T.list_markets(c, race_id=race)
        assert out["freshness"]["venues"] and "any_stale" in out["freshness"]
        c.execute(text("DELETE FROM market_links WHERE token_id LIKE 'fresh-%'"))
