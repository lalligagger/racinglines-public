"""scripts/vm/offsite.sh (the VM's nightly off-site copy) against fake docker and gcloud: it dumps, syncs, and removes a
VM copy of a nightly dump only once the bucket holds it at the same size. No network, no database."""

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/vm/offsite.sh"


def _run(tmp_path, *, bucket_has_same_size, dumps):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text("#!/bin/bash\nprintf -- '-- PostgreSQL database dump complete\\n--\\n'\n")
    describe = 'stat -c %s "$OLD_DUMP"' if bucket_has_same_size else "exit 1"
    (bin_ / "gcloud").write_text(
        '#!/bin/bash\necho "$*" >> "$GLOG"\n'
        f'case "$*" in *"objects describe"*) {describe};; *rsync*) echo "Copying x" >&2;; esac\n')
    for f in bin_.iterdir():
        f.chmod(0o755)
    app, stg = tmp_path / "app", tmp_path / "stg"
    db = app / "data/backups/db"
    db.mkdir(parents=True)
    (stg / "data/backups/db").mkdir(parents=True)
    (app / "data/archive/markets").mkdir(parents=True)
    now = time.time()
    for i in range(dumps):   # older than a day each, oldest last
        p = db / f"racinglines-nightly-2026100{i}T100000Z.sql.gz"
        p.write_text("x")
        os.utime(p, (now - 86400 * (i + 2), now - 86400 * (i + 2)))
    (tmp_path / "env").write_text("")
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", ENV_FILE=str(tmp_path / "env"), APP=str(app),
               STG=str(stg), GLOG=str(tmp_path / "gcloud.log"), OLD_DUMP=str(db / "racinglines-nightly-20261000T100000Z.sql.gz"))
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    return r, db, (tmp_path / "gcloud.log").read_text()


def test_dumps_syncs_and_prunes_only_what_the_bucket_holds(tmp_path):
    r, db, calls = _run(tmp_path, bucket_has_same_size=True, dumps=8)
    assert r.returncode == 0, r.stdout + r.stderr
    nightly = sorted(db.glob("racinglines-nightly-*.sql.gz"))
    assert len(nightly) == 7                       # a new dump plus the newest 6 of the old 8 (NIGHTLY_KEEP=7)
    assert "storage rsync --recursive data/backups gs://racinglines-data-384052502248/backups/prod" in calls
    assert "backups/staging" in calls and "archive/markets gs://racinglines-data-384052502248/archive/markets" in calls
    assert "delete" not in calls                   # never deletes in the bucket


def test_keeps_a_dump_the_bucket_does_not_hold(tmp_path):
    r, db, _ = _run(tmp_path, bucket_has_same_size=False, dumps=8)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(list(db.glob("racinglines-nightly-*.sql.gz"))) == 9
    assert "not in the bucket at the same size" in r.stdout


def test_status_reads_only(tmp_path):
    (tmp_path / "env").write_text("")
    app = tmp_path / "app"
    app.mkdir()
    r = subprocess.run(["bash", str(SCRIPT), "status"], capture_output=True, text=True, timeout=30,
                       env=dict(os.environ, ENV_FILE=str(tmp_path / "env"), APP=str(app)))
    assert "last passes" in r.stdout
