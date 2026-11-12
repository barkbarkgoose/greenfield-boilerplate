#!/usr/bin/env bash
# deploy-rsync.sh (rsync variant): test and build locally on the Mac, rsync to the server,
# then back up, sync dependencies with uv, migrate and restart there.
# For apps provisioned with DEPLOY_REPO=none; otherwise use ./hosting/deploy.sh.
# Reads DEPLOY_HOST and DEPLOY_NAME from hosting/.env (or --env FILE), and the project layout
# from the top of hosting/provision.sh. Guide: docs/vps-hosting.md
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hosting/provision.sh
. "$HERE/provision.sh"

env_file="$HERE/.env"
if [ "${1:-}" = --env ]; then env_file="${2:?--env needs a file}"; shift 2; fi
HOST=$(envfile_get DEPLOY_HOST "$env_file")
NAME=$(envfile_get DEPLOY_NAME "$env_file")
[ -n "$HOST" ] && [ -n "$NAME" ] || {
  echo "deploy-rsync.sh: DEPLOY_HOST and DEPLOY_NAME are not set in $env_file (run ./hosting/provision.sh first)" >&2
  exit 1
}
cd "$HERE/.."
project_versions
APP=/srv/$NAME
SERVER_BACKEND=$APP/app/$(basename "$BACKEND_DIR")

# 1. tests + frontend build (locally)
(cd "$BACKEND_DIR" && uv run pytest -q)
if [ -n "$FRONTEND_DIR" ]; then
  (cd "$FRONTEND_DIR" && pnpm run build)
fi

# 2. copy code. Excludes keep secrets, local databases and server-side state out of the transfer,
#    and --delete leaves excluded paths on the server alone.
excludes=(--exclude='__pycache__/' --exclude='*.pyc' --exclude='.pytest_cache/'
          --exclude='.env' --exclude='db.sqlite3*' --exclude='media/'
          --exclude='staticfiles/' --exclude='tests/' --exclude='conftest.py'
          --exclude='.venv/' --exclude='node_modules/')
for e in ${EXCLUDES[@]+"${EXCLUDES[@]}"}; do excludes+=(--exclude="$e"); done

rsync -az --delete "${excludes[@]}" "$BACKEND_DIR" ${EXTRA[@]+"${EXTRA[@]}"} "$HOST:$APP/app/"
if [ -n "$FRONTEND_DIR" ]; then
  rsync -az --delete "$FRONTEND_DIR/dist/" "$HOST:$APP/frontend/"
fi

# 3. on the server: back up first, sync locked deps with uv, migrate, restart
ssh -t "$HOST" "
  set -e
  umask 022
  sudo -u $NAME $APP/bin/backup-db
  if [ -f $SERVER_BACKEND/uv.lock ]; then
    UV_PYTHON_INSTALL_DIR=/opt/uv/python UV_PROJECT_ENVIRONMENT=$APP/venv /usr/local/bin/uv sync --frozen --no-dev -q --python $PYTHON_VERSION --project $SERVER_BACKEND
  else
    $APP/venv/bin/pip install --no-cache-dir -q -r $SERVER_BACKEND/requirements.txt
  fi
  sudo -u $NAME $APP/bin/manage migrate --noinput
  $APP/bin/manage collectstatic --noinput
  sudo systemctl restart $NAME
"
echo 'Deployed.'
