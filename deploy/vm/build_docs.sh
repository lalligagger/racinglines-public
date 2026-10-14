#!/usr/bin/env bash
# On the VM, as the racinglines user: build the docs site (site/, served behind the login at /docs) from a checkout's
# docs/ and mkdocs.yml: production's (/opt/racinglines, the default) or staging's (/opt/racinglines-staging, passed as
# the first argument). vm.sh deploy, vm.sh docs and vm.sh staging deploy pipe it over ssh, so the VM's checkout doesn't
# need to have it yet. Fail-soft: a failed install or build prints a "docs:" line and exits 0, and the old site stays up.
# Touches only site/ and the venv's mkdocs/mkdocs-material packages: never data/ or the database.
#   bash -s < deploy/vm/build_docs.sh                               (production)
#   bash -s -- /opt/racinglines-staging < deploy/vm/build_docs.sh   (staging)
set -uo pipefail
cd "${1:-/opt/racinglines}" || exit 0
log() { echo "[docs $(date -u +%H:%M:%S)] $*"; }
py=.venv/bin/python
# mkdocs alone isn't enough: the theme is Material (mkdocs.yml), so a venv that has mkdocs but not material (or not
# pymdownx, which material pulls in) installs requirements-docs.txt too.
if ! "$py" -c "import mkdocs, material, pymdownx" 2>/dev/null; then
  log "installing mkdocs + mkdocs-material into the venv (requirements-docs.txt)"
  if ! .venv/bin/pip install --quiet -r requirements-docs.txt; then
    # Python 3.14: mkdocs's watchdog (only `mkdocs serve` needs it) may not build; requirements-docs.txt's fallback
    mkdocs_pin=$(grep -E '^mkdocs==' requirements-docs.txt) material_pin=$(grep -E '^mkdocs-material==' requirements-docs.txt)
    .venv/bin/pip install --quiet --no-deps "${mkdocs_pin:-mkdocs==1.6.1}" mkdocs-get-deps \
        "${material_pin:-mkdocs-material==9.5.50}" mkdocs-material-extensions &&
      .venv/bin/pip install --quiet click jinja2 markdown markupsafe pyyaml pyyaml-env-tag ghp-import mergedeep \
        packaging pathspec platformdirs "pymdown-extensions>=10.2,<11" "pygments>=2.16" babel colorama paginate \
        regex requests ||
      { log "docs: mkdocs could not be installed; /docs keeps its old site (or stays unbuilt)"; exit 0; }
  fi
  "$py" -c "import mkdocs, material, pymdownx" 2>/dev/null ||
    { log "docs: mkdocs-material still missing after the install; /docs keeps its old site (or stays unbuilt)"; exit 0; }
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
