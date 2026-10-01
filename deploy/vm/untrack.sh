#!/usr/bin/env bash
# On the VM, as the racinglines user, before update.sh (vm.sh deploy pipes it over ssh, so the VM's own checkout
# doesn't need to have it yet). A checkout deletes the files the current commit tracks and the target
# doesn't: moving from the private history to the public one, that is data/raw, data/archive, the test fixtures and
# the pitch images. Back those up to data/backups/files/, then untrack them (git rm --cached and a local commit), so the checkout leaves
# them on disk as untracked files. No file is deleted or rewritten. If a later commit tracks one of them again, its
# checkout stops on "untracked working tree files would be overwritten": move that file aside.
#   untrack.sh <ref>
set -euo pipefail
cd /opt/racinglines
ref="${1:-main}"
git fetch --quiet --prune origin
if git rev-parse --verify -q "origin/$ref^{commit}" >/dev/null; then target="origin/$ref"; else target="$ref"; fi
target=$(git rev-parse --verify "$target^{commit}")
list=$(mktemp); trap 'rm -f "$list"' EXIT
git diff --no-renames --name-only --diff-filter=D -z HEAD "$target" > "$list"
n=$(tr -cd '\0' < "$list" | wc -c)
[ "$n" -gt 0 ] || { echo "[untrack] nothing to keep"; exit 0; }
mkdir -p data/backups/files
out="data/backups/files/racinglines-before-untrack-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -czf "$out" --ignore-failed-read --null -T "$list"
git rm -r -q --cached --ignore-unmatch --pathspec-from-file="$list" --pathspec-file-nul
# a local commit on the detached checkout that only stops tracking them (a staged removal alone makes checkout refuse)
git -c user.name=racinglines-vm -c user.email=vm@racinglines.bet commit -q --no-verify -m "untrack files $target does not track (vm.sh deploy)"
echo "[untrack] $n files stay on disk as untracked files; backup $out"
