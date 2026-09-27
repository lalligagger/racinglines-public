"""Parquet market store: archive from Postgres, merged reads, dedupe."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import text

from racinglines.markets import store as MS

TOK = "test-token-marketstore-0000"


def test_parquet_roundtrip_and_filters(tmp_path):
    t0 = datetime(2026, 9, 25, tzinfo=timezone.utc)
    df = pd.DataFrame(dict(token_id=[TOK] * 3 + ["other"], ts=[t0, t0 + timedelta(minutes=1), t0 + timedelta(days=10), t0],
                           price=[0.1, 0.2, 0.3, 0.9]))
    assert MS._write("prices", df, root=tmp_path) == 4
    assert {p.name for p in (tmp_path / "prices").iterdir()} == {"month=2026-09", "month=2026-10"}
    got = MS.read(None, "prices", tokens=[TOK], start=t0, end=t0 + timedelta(hours=1), root=tmp_path)
    assert got["price"].tolist() == [0.1, 0.2]
    assert MS.last_before(None, [TOK], t0 + timedelta(days=1), root=tmp_path) == {TOK: 0.2}


def test_merge_drops_duplicates_across_stores(tmp_path):
    t0 = datetime(2026, 9, 25, tzinfo=timezone.utc)
    a = pd.DataFrame(dict(token_id=[TOK, TOK], ts=[t0, t0 + timedelta(minutes=1)], price=[0.1, 0.2]))
    b = pd.DataFrame(dict(token_id=[TOK], ts=[t0], price=[0.1]))
    assert len(MS.merge(a, b, "prices")) == 2


def test_compact(tmp_path):
    t0 = datetime(2026, 9, 25, tzinfo=timezone.utc)
    df = pd.DataFrame(dict(token_id=[TOK], ts=[t0], price=[0.5]))
    MS._write("prices", df, root=tmp_path)
    MS._write("prices", df, root=tmp_path)
    MS.compact("prices", root=tmp_path)
    assert len(list((tmp_path / "prices").rglob("*.parquet"))) == 1
    assert len(MS.read(None, "prices", root=tmp_path)) == 1


def test_archive_moves_rows_out_of_postgres(tmp_path, test_engine):
    e = test_engine
    old, new = datetime.now(timezone.utc) - timedelta(days=2), datetime.now(timezone.utc)
    with e.begin() as c:
        c.execute(text("DELETE FROM market_price_history WHERE token_id = :t"), dict(t=TOK))
        c.execute(text("INSERT INTO market_price_history (token_id, ts, price) VALUES (:t, :a, 0.4), (:t, :b, 0.6)"),
                  dict(t=TOK, a=old, b=new))
    try:
        assert MS.archive(e, "prices", older_than=timedelta(hours=6), tokens=[TOK], root=tmp_path) == 1
        with e.connect() as c:
            assert c.execute(text("SELECT count(*) FROM market_price_history WHERE token_id = :t"), dict(t=TOK)).scalar() == 1
            both = MS.read(c, "prices", tokens=[TOK], root=tmp_path)
        assert both["price"].tolist() == [0.4, 0.6]                  # one from Parquet, one from Postgres
    finally:
        with e.begin() as c:
            c.execute(text("DELETE FROM market_price_history WHERE token_id = :t"), dict(t=TOK))


@pytest.mark.live
def test_policy_keeps_hot_tokens(tmp_path):
    """A token of an upcoming race stays in Postgres; an unknown (stale) one is archived."""
    from racinglines.db.config import get_engine
    try:
        e = get_engine()
        with e.connect() as c:
            hot, _ = MS.hot_tokens(c)
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"no database: {ex}")
    if not hot:
        pytest.skip("no upcoming race markets")
    t_old = datetime.now(timezone.utc) - timedelta(days=30)
    with e.begin() as c:
        c.execute(text("INSERT INTO market_price_history (token_id, ts, price) VALUES (:h, :a, 0.4), (:s, :a, 0.6) "
                       "ON CONFLICT DO NOTHING"), dict(h=hot[0], s=TOK, a=t_old))
    try:
        assert MS.archive(e, "prices", policy=True, tokens=[hot[0], TOK], root=tmp_path) == 1
        with e.connect() as c:
            left = c.execute(text("SELECT token_id FROM market_price_history WHERE token_id = ANY(:t) AND ts = :a"),
                             dict(t=[hot[0], TOK], a=t_old)).scalars().all()
        assert left == [hot[0]]
    finally:
        with e.begin() as c:
            c.execute(text("DELETE FROM market_price_history WHERE token_id = ANY(:t) AND ts = :a"),
                      dict(t=[hot[0], TOK], a=t_old))
