#!/usr/bin/env bash
# Restore the pinned test fixtures (tests/fixtures/f1, market, mtb: about 3 MB) from the private repository, where
# they are still in git, into this checkout. They stay untracked here: the public repo carries no data
# (docs/contributing.md "Data in this repository"). Needs read access to the private repo.
#
#   bash scripts/restore_test_fixtures.sh [<private repo URL or path>] [<ref>]
#
# Never rebuild them with `fetch_test_fixtures.py --refresh` to make tests run: that pulls today's data and moves
# the golden outputs. Files already here are kept (cp -n), so a local fixture is never overwritten.
set -euo pipefail

SRC=${1:-https://github.com/lalligagger/racinglines}
REF=${2:-main}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

git clone -q --depth 1 --branch "$REF" --filter=blob:none --sparse "$SRC" "$TMP/src"
git -C "$TMP/src" sparse-checkout set tests/fixtures
mkdir -p "$ROOT/tests/fixtures"
cp -Rn "$TMP/src/tests/fixtures/." "$ROOT/tests/fixtures/"
echo "restored tests/fixtures from $SRC@$(git -C "$TMP/src" rev-parse --short HEAD): $(find "$ROOT/tests/fixtures" -type f | wc -l | tr -d ' ') files"
