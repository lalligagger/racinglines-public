"""The storage status (racinglines/storage_status.py): the VM's data folders and databases and the data bucket's
prefixes, as one snapshot read by the admin Storage page, `racinglines db storage` and the MCP tool storage_status
(owner, 2026-10-14)."""

import json
import os

import pytest

from test_strategy_pick import app_db  # noqa: F401  (the fixture)

LS = """gs://b/archive/:
      1000  2026-09-30T10:00:00Z  gs://b/archive/markets/polymarket/prices/month=2026-09/part-1.parquet
      3000  2026-09-29T10:00:00Z  gs://b/archive/markets/kalshi/books/part-2.parquet
gs://b/vendor/probalytics/:
   5000000  2026-10-14T20:01:00Z  gs://b/vendor/probalytics/f1/2026-05-09/books.parquet
        10  2026-10-14T19:00:00Z  gs://b/vendor/probalytics/README.md
       200  2026-10-14T20:05:00Z  gs://b/backups/prod/db/racinglines-nightly-20261014T020000Z.sql.gz
       100  2026-10-14T20:06:00Z  gs://b/backups/staging/db/racinglines-nightly-20261014T020000Z.sql.gz
         7  2026-10-01T00:00:00Z  gs://b/README.md
TOTAL: 7 objects, 5004317 bytes (4.77MiB)
"""


@pytest.mark.quick
def test_parse_ls_groups_by_prefix_and_the_folders_under_it():
    from racinglines import storage_status as ST
    tops = {p["prefix"]: p for p in ST.parse_ls(LS, "b")}
    assert list(tops) == ["(top)", "archive/", "backups/", "vendor/"]
    assert tops["archive/"]["bytes"] == 4000 and tops["archive/"]["objects"] == 2
    assert tops["archive/"]["newest"] == "2026-09-30T10:00:00Z"
    assert [(c["prefix"], c["bytes"]) for c in tops["backups/"]["children"]] == [("backups/prod/", 200),
                                                                                 ("backups/staging/", 100)]
    v = tops["vendor/"]
    assert v["bytes"] == 5000010 and [c["prefix"] for c in v["children"]] == ["vendor/probalytics/"]
    assert tops["(top)"]["objects"] == 1 and tops["(top)"]["children"] == []


@pytest.mark.quick
def test_snapshot_vm_folders_backups_and_a_bucket_that_cannot_be_listed(tmp_path, monkeypatch):
    from racinglines import paths
    from racinglines import storage_status as ST
    data = tmp_path / "data"
    (data / "backups" / "db").mkdir(parents=True)
    (data / "archive" / "markets").mkdir(parents=True)
    (data / "archive" / "markets" / "a.parquet").write_bytes(b"x" * 300)
    for i, name in enumerate(("racinglines-nightly-1.sql.gz", "racinglines-before-x-2.sql.gz")):
        f = data / "backups" / "db" / name
        f.write_bytes(b"y" * 50)
        os.utime(f, (1_700_000_000 + i, 1_700_000_000 + i))
    other = tmp_path / "staging-data"
    (other / "raw").mkdir(parents=True)
    (other / "raw" / "r.json").write_text("{}")
    monkeypatch.setattr(paths, "DATA", data)
    monkeypatch.setenv("RACINGLINES_STATUS_DATA_ROOTS", str(other))
    monkeypatch.setenv("RACINGLINES_STATUS_BUCKETS", "gs://b/, nope")

    def ls(bucket):
        if bucket == "nope":
            raise RuntimeError("AccessDenied")
        return LS

    snap = ST.refresh(None, ls=ls)
    assert ST.read() == json.loads(json.dumps(snap)) and ST.snapshot_path() == data / "status" / "storage.json"
    here, there = snap["vm"]["roots"]
    folders = {f["name"]: f for f in here["folders"]}
    assert folders["archive"]["bytes"] == 300 and folders["backups"]["files"] == 2
    assert here["backups"] == dict(dumps=2, bytes=100, newest="racinglines-before-x-2.sql.gz",
                                   newest_at="2023-11-14T22:13:21+00:00")
    assert there["path"] == str(other) and there["folders"][0]["name"] == "raw"
    assert snap["vm"]["disk"]["free"] > 0 and snap["databases"] == []
    ok, bad = snap["buckets"]
    assert ok["bucket"] == "b" and ok["objects"] == 7 and bad == dict(bucket="nope", error="RuntimeError: AccessDenied")
    text = "\n".join(ST.lines(snap))
    assert "gs://b  5.0 MB, 7 objects" in text and "vendor/probalytics/" in text and "not listed (RuntimeError" in text
    assert ST.age_seconds(snap) < 60 and ST.human(4_600_000_000) == "4.6 GB"


def test_database_sizes_page_cli_and_mcp_are_admin_only(app_db, tmp_path, monkeypatch, capsys):  # noqa: F811
    from fastapi.testclient import TestClient

    from racinglines import paths
    from racinglines import storage_status as ST
    from racinglines.cli import db as DB
    from racinglines.db import config
    from racinglines.web import users as U
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setenv("RACINGLINES_STATUS_DATA_ROOTS", "")
    monkeypatch.setenv("RACINGLINES_STATUS_BUCKETS", "b")
    monkeypatch.setattr(ST, "_gcloud_ls", lambda bucket: LS)
    with config.get_engine().connect() as c:
        snap = ST.refresh(c)
    test_db = config.get_engine().url.database
    assert test_db in {d["name"] for d in snap["databases"]} and all(d["bytes"] > 0 for d in snap["databases"])

    with config.get_session() as s:
        U.create_user(s, "root", "root-password-1", "admin")
    pro, admin = TestClient(app_db.app), TestClient(app_db.app)
    for client, name in ((pro, "ada"), (admin, "root")):
        client.post("/login", data=dict(username=name, password=f"{name}-password-1"), follow_redirects=False)
    assert pro.get("/admin/storage", follow_redirects=False).status_code in (302, 303, 403, 404)
    page = admin.get("/admin/storage").text
    assert "gs://b" in page and "vendor/probalytics/" in page and test_db in page and "Refresh now" in page
    assert 'href="/admin/storage"' in admin.get("/admin/db").text

    DB.main(["storage"])
    assert "gs://b  5.0 MB, 7 objects" in capsys.readouterr().out
    DB.main(["storage", "--json"])
    assert json.loads(capsys.readouterr().out)["buckets"][0]["objects"] == 7

    from racinglines.mcp import tools as T
    with config.get_engine().connect() as c:
        out = T.storage_status(c)
    assert out["snapshot"]["taken_at"] == snap["taken_at"] and out["refreshing"] is False
