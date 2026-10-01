"""Guard: no data is tracked by git or about to be (untracked, not ignored), except the minimal
allow-listed set cloud sweeps need and the pinned test fixtures and goldens (.gitignore; the repo is
private since 2026-09-27)."""

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.quick

ROOT = Path(__file__).resolve().parents[1]
DATA_DIRS = ("data/", "tests/fixtures/", "tests/golden/")
DATA_EXT = (".parquet", ".npz", ".feather", ".arrow", ".sqlite", ".sqlite3", ".db", ".csv", ".pkl", ".pickle",
            ".joblib", ".json.gz")
ALLOWED_LARGE = ("docs/",)                      # screenshots / images in the docs
# the minimal data set for cloud sweeps (docs/cloud-sweep.md); must match the allow-list in .gitignore
ALLOWED_DATA = ("data/raw/f1/fastf1/", "data/archive/markets/polymarket/prices/",
                "data/archive/markets/polymarket/trades/", "data/archive/markets/polymarket/links/",
                "data/archive/markets/kalshi/prices/", "data/archive/markets/kalshi/trades/",
                "data/archive/markets/kalshi/links/", "data/archive/db/",
                "data/runs/search/", "tests/golden/", "tests/fixtures/f1/", "tests/fixtures/market/",
                "tests/fixtures/mtb/")
MAX_BYTES = 1_000_000


def _git(*args):
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.CalledProcessError) as ex:
        pytest.skip(f"git not available: {ex}")
    return [line for line in out.stdout.splitlines() if line]


def _offenders(files):
    bad = []
    for f in files:
        if f.startswith(ALLOWED_DATA):
            continue
        if f.startswith(DATA_DIRS) or f.endswith(DATA_EXT):
            bad.append(f)
        elif (ROOT / f).is_file() and (ROOT / f).stat().st_size > MAX_BYTES and not f.startswith(ALLOWED_LARGE):
            bad.append(f"{f} (> 1 MB)")
    return bad


def test_nothing_data_like_is_tracked():
    assert _offenders(_git("ls-files")) == []


def test_nothing_data_like_is_about_to_be_added():
    assert _offenders(_git("ls-files", "--others", "--exclude-standard")) == []
