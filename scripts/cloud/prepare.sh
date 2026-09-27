#!/usr/bin/env bash
# Before launching a cloud sweep: bring the committed data set up to date with this machine, so the
# cloud database is an exact replica (identical prices) and needs no network beyond PyPI/GitHub.
#   1. move every market row from the Postgres buffer into the Parquet archive
#   2. export the model tables (with ids) and the market links
#   3. check that only allow-listed data would be committed
# Then: git add -A && git commit && git push  (see docs/cloud-sweep.md)
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv/bin/python
$PY - <<'PYEOF'
from datetime import timedelta
from racinglines.db.config import get_engine
from racinglines.markets import store as MS
eng = get_engine()
for name in ("prices", "trades"):
    print(f"archive {name}: {MS.archive(eng, name, older_than=timedelta(0))} rows moved to Parquet")
PYEOF
.venv/bin/racinglines db snapshot-export
.venv/bin/racinglines f1 pm-links-export
$PY -m pytest -q tests/test_no_data_in_git.py
echo "ready to commit: $(git status --short --untracked-files=all data | wc -l | tr -d ' ') data files changed"
