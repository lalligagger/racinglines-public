#!/usr/bin/env bash
# One-time setup of the racinglines VM (Ubuntu 24.04), as root. Safe to re-run. See docs/vm-deploy.md.
# Copied up and run by:  scripts/deploy/vm.sh setup
#
# 1. packages: git, docker + compose v2, uv (Python 3.14, as on the Mac), cloudflared
# 2. the racinglines user and a read-only GitHub deploy key (printed: add it to the repo, then re-run)
# 3. the checkout in /opt/racinglines (main, or REF), its venv, the database, /etc/racinglines.env
# 4. the systemd units (installed, not started: vm.sh start does that)
set -euo pipefail
REPO="${REPO:-https://github.com/lalligagger/racinglines-public.git}"
REF="${REF:-main}"      # the branch to clone first (vm.sh setup <branch> tests an unmerged branch)
APP=/opt/racinglines
log() { echo "[setup $(date -u +%H:%M:%S)] $*"; }
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }

log "packages"
export DEBIAN_FRONTEND=noninteractive
if ! command -v cloudflared >/dev/null; then
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
    > /etc/apt/sources.list.d/cloudflared.list
fi
apt-get update -qq
apt-get install -y -qq git docker.io docker-compose-v2 python3-venv cloudflared >/dev/null
systemctl enable --now docker
if [ ! -x /opt/uv/bin/uv ]; then python3 -m venv /opt/uv && /opt/uv/bin/pip install --quiet uv; fi

log "user racinglines"
id racinglines >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash racinglines
usermod -aG docker racinglines
as() { sudo -u racinglines -H "$@"; }
key=~racinglines/.ssh/id_ed25519
if [ ! -f "$key" ]; then
  as mkdir -p ~racinglines/.ssh
  as ssh-keygen -q -t ed25519 -N "" -C "racinglines-vm deploy key" -f "$key"
  as sh -c 'ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null'
fi

log "checkout $APP"
if [ ! -d "$APP/.git" ]; then
  mkdir -p "$APP" && chown racinglines: "$APP"
  if ! as git clone --quiet --branch "$REF" "$REPO" "$APP"; then
    echo
    echo "Add this read-only deploy key to GitHub (repo Settings > Deploy keys > Add, leave write access off),"
    echo "then run  scripts/deploy/vm.sh setup  again:"
    echo
    cat "$key.pub"
    exit 2
  fi
fi

log "python 3.14 venv"
[ -x "$APP/.venv/bin/python" ] || as sh -c "cd $APP && UV_PYTHON_INSTALL_DIR=\$HOME/.uv-python /opt/uv/bin/uv venv --quiet --seed --python 3.14 .venv"
as sh -c "cd $APP && .venv/bin/pip install --quiet -r requirements.txt -e ."

log "database"
as sh -c "cd $APP && printf 'COMPOSE_FILE=docker-compose.yml:deploy/vm/compose.override.yml\n' > .env"
as sh -c "cd $APP && docker compose up -d --wait db"
if [ ! -f /etc/racinglines.env ]; then
  install -o root -g racinglines -m 640 "$APP/deploy/vm/racinglines.env.example" /etc/racinglines.env
  sed -i "s/^APP_SECRET=$/APP_SECRET=$(openssl rand -hex 32)/" /etc/racinglines.env
  echo "  wrote /etc/racinglines.env: set ADMIN_PASSWORD (and the alert settings) with  sudo nano /etc/racinglines.env"
fi
as mkdir -p "$APP/data/runs/logs"

log "systemd units"
install -m 644 "$APP"/deploy/vm/systemd/* /etc/systemd/system/
systemctl daemon-reload
log "done. Next: vm.sh restore (first data load), then vm.sh start"
