#!/usr/bin/env bash
# On the VM, after update.sh moved the checkout: put back, as untracked files, what the previous commit tracked and the
# new one doesn't. Moving from the private repo's history to the public one would otherwise delete data/, the test
# fixtures and the pitch images from disk. Run by scripts/deploy/vm.sh deploy, also when update.sh failed. If a later
# commit tracks one of these paths again, its checkout stops on "untracked files would be overwritten": delete that file.
#   deploy/vm/keep-files.sh <previous commit>
set -euo pipefail
cd "${0%/*}/../.."    # the checkout (/opt/racinglines on the VM)
old="${1:-}"
git cat-file -e "$old^{commit}" 2>/dev/null || { echo "[keep] no previous commit to keep files from"; exit 0; }
n=$(git diff --no-renames --name-only --diff-filter=D "$old" HEAD | wc -l)
[ "$n" -gt 0 ] || exit 0
git diff --no-renames --name-only --diff-filter=D -z "$old" HEAD |
  xargs -0 sh -c 'for f; do [ -e "$f" ] || printf "%s\0" "$f"; done' sh |
  xargs -0 -r sh -c 'git archive "$0" -- "$@" | tar -x' "$old"
echo "[keep] $n files ${old:0:12} tracked and HEAD doesn't are on disk as untracked files"
