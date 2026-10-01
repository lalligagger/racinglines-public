#!/usr/bin/env bash
# On the VM, as the racinglines user: build the docs site (site/, served behind the login at /docs) from the
# checkout's docs/ and mkdocs.yml. vm.sh deploy and vm.sh docs pipe it over ssh, so the VM's checkout doesn't need to
# have it yet. Fail-soft: a failed install or build prints a "docs:" line and exits 0, and the old site stays up.
# Touches only site/ and the venv's mkdocs packages: never data/ or the database.
#   bash -s < deploy/vm/build_docs.sh      (from /opt/racinglines)
set -uo pipefail
cd /opt/racinglines || exit 0
log() { echo "[docs $(date -u +%H:%M:%S)] $*"; }
py=.venv/bin/python
if ! "$py" -c "import mkdocs" 2>/dev/null; then
  log "installing mkdocs into the venv (requirements-docs.txt)"
  if ! .venv/bin/pip install --quiet -r requirements-docs.txt; then
    # Python 3.14: mkdocs's watchdog (only `mkdocs serve` needs it) may not build; requirements-docs.txt's fallback
    .venv/bin/pip install --quiet --no-deps mkdocs==1.6.1 mkdocs-get-deps &&
      .venv/bin/pip install --quiet click jinja2 markdown markupsafe pyyaml pyyaml-env-tag ghp-import mergedeep \
        packaging pathspec platformdirs ||
      { log "docs: mkdocs could not be installed; /docs keeps its old site (or stays unbuilt)"; exit 0; }
  fi
fi
# build beside the live site, then swap, so /docs never serves a half-built folder
rm -rf site.new site.old
if "$py" -m mkdocs build --quiet --clean -d site.new; then
  [ -d site ] && mv site site.old
  mv site.new site && rm -rf site.old
  log "docs: built site/ from $(git log -1 --format='%h %s')"
else
  rm -rf site.new
  log "docs: mkdocs build failed (above); /docs keeps its old site (or stays unbuilt)"
fi
exit 0
