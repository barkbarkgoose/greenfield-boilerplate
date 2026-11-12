#!/usr/bin/env bash
# deploy.sh: deploy a pushed commit with the server's /srv/NAME/bin/deploy, which fetches it into
# staging, runs the tests and the frontend build there, and only then copies it live.
# Reads DEPLOY_HOST and DEPLOY_NAME from hosting/.env. Needs the server provisioned with
# hosting/provision.sh. Guide: docs/vps-hosting.md
#
#   ./hosting/deploy.sh                  deploy DEPLOY_BRANCH
#   ./hosting/deploy.sh REF              deploy a branch, tag or commit (e.g. the previous commit, to roll back)
#   ./hosting/deploy.sh --env FILE [REF] deploy to another target (e.g. hosting/.env.staging)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hosting/provision.sh
. "$HERE/provision.sh"

env_file="$HERE/.env"
if [ "${1:-}" = --env ]; then env_file="${2:?--env needs a file}"; shift 2; fi
HOST=$(envfile_get DEPLOY_HOST "$env_file")
NAME=$(envfile_get DEPLOY_NAME "$env_file")
[ -n "$HOST" ] && [ -n "$NAME" ] || {
  echo "deploy.sh: DEPLOY_HOST and DEPLOY_NAME are not set in $env_file (run ./hosting/provision.sh first)" >&2
  exit 1
}
REF=${1:-}
[[ $REF =~ ^[A-Za-z0-9._/-]*$ ]] || {
  echo "deploy.sh: '$REF' is not a branch, tag or commit name" >&2
  exit 1
}

# The server deploys what is pushed, not this folder: say so when they differ.
cd "$HERE/.."
if [ -n "$(git status --porcelain)" ]; then
  echo "note: uncommitted changes here are not deployed" >&2
fi
if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  git fetch -q || true
  ahead=$(git rev-list --count '@{u}..HEAD')
  if [ "$ahead" -gt 0 ]; then
    echo "note: $ahead local commit(s) not pushed; they are not deployed (git push first)" >&2
  fi
fi

ssh -t "$HOST" "/srv/$NAME/bin/deploy $REF"
