"""The pull's --to-bucket hook (scripts/probes/probalytics_pull.py): upload, size check, local delete, and a rerun that
skips what the bucket already has. gcloud is faked; nothing leaves the machine."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pull(tmp_path, monkeypatch):
    env = tmp_path / ".env.probalytics"
    env.write_text("PROBALYTICS_CH_USER=u\nPROBALYTICS_CH_PASSWORD=p\n")
    out = tmp_path / "probalytics"
    out.mkdir()
    monkeypatch.setenv("PROBALYTICS_ENV", str(env))
    monkeypatch.setenv("PROBALYTICS_OUT", str(out))
    monkeypatch.delenv("PROBALYTICS_BUCKET", raising=False)
    spec = importlib.util.spec_from_file_location("probalytics_pull", ROOT / "scripts/probes/probalytics_pull.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bucket = {}

    def fake_run(cmd, **kw):
        assert cmd[:2] == ["gcloud", "storage"]
        if cmd[2] == "cp":
            bucket[cmd[-1]] = Path(cmd[-2]).stat().st_size
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[2] == "objects":
            return subprocess.CompletedProcess(cmd, 0, f"{bucket.get(cmd[4], '')}\n", "")
        raise AssertionError(cmd)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    mod.BUCKET.update(to="gs://b/vendor/probalytics", keep_local=False)
    return mod, out, bucket


def written(mod, out, rel, key="k1"):
    p = out / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * 10)
    mod.manifest(file=rel, rows=3, bytes=10, links_key=key)
    return p


def test_upload_checks_size_then_deletes_and_rerun_skips(pull):
    mod, out, bucket = pull
    p = written(mod, out, "books/2026-07-15_CYC_KALSHI.parquet")
    mod.upload(p, rows=3, kind="books", links_key="k1")
    assert bucket["gs://b/vendor/probalytics/books/2026-07-15_CYC_KALSHI.parquet"] == 10
    assert "gs://b/vendor/probalytics/MANIFEST.jsonl" in bucket
    assert not p.exists()
    last = [json.loads(x) for x in (out / "MANIFEST.jsonl").read_text().splitlines()][-1]
    assert last["uploaded"].endswith("books/2026-07-15_CYC_KALSHI.parquet") and last["rows"] == 3
    assert mod.current(p, "k1")          # in the bucket: a rerun skips it
    assert not mod.current(p, "k2")      # a wider set of markets refetches it


def test_size_mismatch_keeps_the_local_file(pull, monkeypatch):
    mod, out, _ = pull
    p = written(mod, out, "fills/CYC_POLYMARKET_2026-07.parquet")
    real = mod.subprocess.run

    def short(cmd, **kw):
        r = real(cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, "9\n", "") if cmd[2] == "objects" else r

    monkeypatch.setattr(mod.subprocess, "run", short)
    with pytest.raises(SystemExit):
        mod.upload(p, links_key="k1")
    assert p.exists()
    assert not mod.entries()[str(p.relative_to(out))].get("uploaded")


def test_keep_local_and_missing_file_without_upload(pull):
    mod, out, _ = pull
    mod.BUCKET["keep_local"] = True
    p = written(mod, out, "stages/2026_17_POLYMARKET.parquet")
    mod.upload(p, links_key="k1")
    assert p.exists()
    q = written(mod, out, "books/2026-07-16_CYC_KALSHI.parquet")
    q.unlink()                           # written, never uploaded, then lost: fetch it again
    assert not mod.current(q, "k1")


def test_seed_from_bucket_marks_another_machines_files_present(pull, monkeypatch):
    mod, out, _ = pull
    pre = "gs://b/vendor/probalytics"
    mac = [{"at": "2026-10-14T10:00:00+00:00", "file": f"books/2026-10-1{d}_F1_KALSHI.parquet", "rows": 5,
            "bytes": 10, "links_key": "k1"} for d in (2, 3)]
    mac.append({"at": "2026-10-14T10:00:00+00:00", "file": "books/2026-10-11_F1_KALSHI.parquet", "links_key": "k1"})
    objects = [f"{pre}/{r['file']}" for r in mac[:2]] + [f"{pre}/MANIFEST.jsonl"]   # 10-11 never made it up
    mine = written(mod, out, "fills/F1_KALSHI_2026-10.parquet")

    def fake(cmd, **kw):
        if cmd[2] == "cat":
            return subprocess.CompletedProcess(cmd, 0, "".join(json.dumps(r) + "\n" for r in mac), "")
        if cmd[2] == "ls":
            return subprocess.CompletedProcess(cmd, 0, "\n".join(objects) + "\n", "")
        raise AssertionError(cmd)

    monkeypatch.setattr(mod.subprocess, "run", fake)
    assert mod.seed_from_bucket() == 2
    assert mod.current(out / "books/2026-10-12_F1_KALSHI.parquet", "k1")
    assert not mod.current(out / "books/2026-10-12_F1_KALSHI.parquet", "k2")    # a wider link set still refetches
    assert not mod.current(out / "books/2026-10-11_F1_KALSHI.parquet", "k1")    # listed but not in the bucket
    assert mod.current(mine, "k1")                                                # our own rows survive the merge
    assert mod.seed_from_bucket() == 0                                            # idempotent


def test_seed_from_an_empty_bucket(pull, monkeypatch):
    mod, out, _ = pull

    def missing(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(mod.subprocess, "run", missing)
    assert mod.seed_from_bucket() == 0
