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
                     "edge_finder", "track_record", "describe_schema"}
    assert all(t.description for t in tools)
    lm = next(t for t in tools if t.name == "list_markets")
    assert "race_id" in lm.input_schema["properties"] and lm.input_schema["properties"]["limit"]["default"] == 50


def test_reads_on_the_test_database(mcp):
    """The test database is empty, or holds what earlier test modules ingested: the shapes hold either way."""
    ov = mcp("overview")
    assert {v["code"] for v in ov["venues"]} >= {"polymarket", "private"} and ov["row_counts"]["events"] >= 0
    assert set(ov) >= {"seasons", "forecasts", "model_runs", "market_links", "users", "upcoming", "hint"}
    ev = mcp("list_events", sport="f1", limit=5)
    assert len(ev["rows"]) <= 5 and ev["total"] >= len(ev["rows"]) and ev["limit"] == 5
    sc = mcp("describe_schema", table="model_runs")
    assert sc["rows"] >= 0 and "params" in {c["name"] for c in sc["columns"]}
    assert mcp("describe_schema")["tables"][0]["table"] == "sports"
    assert "forecasts" in mcp("get_forecast", sport="f1")
    assert mcp("edge_finder", year=2026)["configurations"] >= 0
    kind, text = mcp("describe_schema", table="nope")
    assert kind == "error" and "no table" in text


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

def test_tokens_are_per_account_and_only_for_allowed_real_accounts(test_engine):
    from sqlalchemy import text
    from racinglines.mcp import auth
    from racinglines.web import users as U
    from racinglines.db.config import get_session
    from sqlalchemy.orm import sessionmaker
    with sessionmaker(test_engine)() as s:
        for name, role, active in (("t_admin", "admin", True), ("t_maker", "maker", True), ("t_gone", "admin", False)):
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
    with pytest.raises(ValueError, match="role"):
        auth.new_token(test_engine, "t_maker")                                        # RACINGLINES_MCP_ROLES=admin
    with pytest.raises(ValueError, match="inactive"):
        auth.new_token(test_engine, "t_gone")
    with pytest.raises(ValueError, match="no account"):
        auth.new_token(test_engine, "t_nobody")
    assert ("t_admin", "admin") in {(u, r) for u, r, _ in auth.holders(test_engine)}
    assert auth.revoke(test_engine, "t_admin") and not auth.revoke(test_engine, "t_admin")
    assert auth.lookup(test_engine, tok2) is None


def test_demo_accounts_never_get_a_token(test_engine, monkeypatch):
    from racinglines.mcp import auth
    from racinglines.web import demo, users as U
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    monkeypatch.setattr(demo, "DEMO_USERS", {"t_demo"})
    with sessionmaker(test_engine)() as s:
        if not s.execute(text("SELECT 1 FROM users WHERE username = 't_demo'"), {}).first():
            U.create_user(s, "t_demo", "pw", "admin")
        s.commit()
    with pytest.raises(ValueError, match="demo"):
        auth.new_token(test_engine, "t_demo")


def test_bearer_check_guards_the_http_app(test_engine):
    """The ASGI wrapper: no token or a wrong one is 401 before the MCP app sees the request; a good one passes and
    names the caller for the request."""
    from starlette.testclient import TestClient
    from racinglines.mcp import auth, server as S
    tok = auth.new_token(test_engine, "t_admin")
    seen = []

    async def inner(scope, receive, send):
        seen.append(S.CALLER.get())
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})

    client = TestClient(S.bearer_app(inner, engine=test_engine))
    assert client.get("/mcp").status_code == 401
    assert client.get("/mcp", headers={"Authorization": "Bearer rl_nope"}).status_code == 401
    assert client.get("/mcp", headers={"Authorization": "Basic xyz"}).status_code == 401
    r = client.get("/mcp", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and seen[-1]["username"] == "t_admin" and S.CALLER.get() is None
    auth.revoke(test_engine, "t_admin")
    assert client.get("/mcp", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_http_app_serves_a_public_hostname(test_engine):
    """Behind the tunnel the Host header is the public name, not localhost: with a token the MCP app answers it
    (the SDK's localhost-only guard would give 421); without one it is 401 as ever."""
    from starlette.testclient import TestClient
    from racinglines.mcp import auth, server as S
    tok = auth.new_token(test_engine, "t_admin")
    url = test_engine.url.render_as_string(hide_password=False)
    body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    hdr = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    with TestClient(S.http_app(S.build(engine_url=url), engine=test_engine), base_url="https://mcp.racinglines.bet") as client:
        assert client.post("/mcp", json=body, headers=hdr).status_code == 401
        r = client.post("/mcp", json=body, headers={**hdr, "Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
    auth.revoke(test_engine, "t_admin")
