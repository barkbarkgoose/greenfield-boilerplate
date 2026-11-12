#!/usr/bin/env bash
# provision.sh: set up (or repair) this app on a Debian/Ubuntu VPS:
#   nginx -> gunicorn -> Django -> PostgreSQL or SQLite, with the built Vue app served by nginx.
# Guide: docs/vps-hosting.md
#
# Run it from your Mac. It reads the deploy target from hosting/.env (asking for anything
# missing and saving the answers there), copies itself to DEPLOY_HOST and runs there:
#   ./hosting/provision.sh
#   ./hosting/provision.sh --check
#   ./hosting/provision.sh --env hosting/.env.staging      a second target
#
# On the server it keeps a copy of those settings in /srv/NAME/.env (the DEPLOY_* lines), so
# it can also be re-run there directly, as your normal sudo user (not root):
#   bash /tmp/provision-NAME/provision.sh --name NAME [--check]
#
# Safe to re-run. Every step checks before it changes anything, never overwrites an
# existing secret or the database, and finishes with a permissions check.
# Several apps can share one server. Each gets its own user, port, /srv/NAME, and pinned
# Python (/opt/uv/python) and Node (/usr/local/lib/node-MAJOR).
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------- project
# Facts about this repo, versioned with it: change them here. The Python version comes from
# BACKEND_DIR/.python-version and the Node major from "engines" in FRONTEND_DIR/package.json.
BACKEND_DIR=backend                        # folder with manage.py and pyproject.toml
FRONTEND_DIR=frontend                      # Vue project, or '' for none; builds to FRONTEND_DIR/dist
WSGI=config.wsgi:application               # gunicorn app
HEALTH_PATH=/health/                       # checked after start and deploy, or none
# nginx location for the sign-in endpoints, rate-limited to 5 req/min per IP (burst 10), or none
AUTH_LOCATION='~ ^/api/v1/auth/(login|register|refresh|passkeys/login)/'
TEST_CMD='pytest -q'                       # run in BACKEND_DIR with the staging venv; '' skips tests
BUILD_CMD='pnpm install --frozen-lockfile && pnpm build'   # run in FRONTEND_DIR
EXTRA=()                                   # other repo folders the backend imports, copied next to it
EXCLUDES=('keychain.key' 'keychain.json')  # never copied to the server
# Cron jobs as "schedule command", run as the app user; bin/ means /srv/NAME/bin/
JOBS=('40 3 * * *  bin/manage flushexpiredtokens')   # drop expired JWT blacklist rows

usage() {
  cat <<'EOF'
Usage: provision.sh [options]

On your Mac (settings come from hosting/.env; anything missing is asked for and saved there):
  --env FILE             settings file                                         [hosting/.env]
  --host HOST            ssh alias from ~/.ssh/config                          (DEPLOY_HOST)

Settings (each overrides its DEPLOY_* line for this run only):
  --name NAME            service user, /srv/NAME, systemd unit, nginx site, database
  --domain HOST          public hostname (its A record must point at the server for HTTPS)
  --email ADDR           address for Let's Encrypt expiry notices
  --db KIND              postgres (on this server) | sqlite | external (DATABASE_URL in .env)
  --repo URL             git SSH URL the server deploys from, or none to deploy from the Mac
  --branch NAME          branch bin/deploy deploys by default                  [main]
  --port N               local gunicorn port, one per app                      [first free from 8000]
  --workers N            gunicorn worker processes                             [2]
  --threads N            threads per worker                                    [2]
  --max-body SIZE        largest request nginx accepts (uploads), e.g. 1m, 26m [1m]
  --build-memory-max M   RAM for tests and the build on the server             [250M]
  --build-swap-max M     swap they may use before they are killed              [1G]

  -y, --yes              on the Mac: don't ask, use defaults for missing settings
  --force-cert           ask Let's Encrypt even if DNS does not appear to point here (e.g. proxied)
  --check                only verify files, permissions and services; change nothing
  -h, --help             show this help

On the server, settings come from flags, else from the DEPLOY_* lines in /srv/NAME/.env.
The Mac also passes --python-version and --node-major, read from the project's files.
Environment: SWAP_MB (default 1024).
EOF
}

# ---------------------------------------------------------------- settings
SWAP_MB="${SWAP_MB:-1024}"
UV_PYTHON_DIR="/opt/uv/python"

# The deploy target, as DEPLOY_<KEY> lines in hosting/.env (Mac) and /srv/NAME/.env (server).
KEYS=(NAME DOMAIN EMAIL DB REPO BRANCH PORT WORKERS THREADS MAX_BODY BUILD_MEMORY_MAX BUILD_SWAP_MAX PYTHON_VERSION NODE_MAJOR)
ASKED_KEYS=(HOST NAME DOMAIN EMAIL DB REPO BRANCH)        # asked for on the Mac when missing
OPTIONAL_KEYS=(PORT WORKERS THREADS MAX_BODY BUILD_MEMORY_MAX BUILD_SWAP_MAX)

RE_HOST='^[A-Za-z0-9._@-]+$'
RE_NAME='^[a-z][a-z0-9_-]{1,30}$'
RE_DOMAIN='^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$'
RE_EMAIL='^[^@ ]+@[^@ ]+\.[^@ ]+$'
RE_DB='^(sqlite|postgres|external)$'
RE_REPO='^(none|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9._/-]+)$'
RE_BRANCH='^[A-Za-z0-9._/-]+$'
RE_PYVER='^3\.[0-9]{1,2}(\.[0-9]{1,2})?$'
RE_NODEMAJ='^([1-9][0-9]|none)$'
RE_PORT='^[1-9][0-9]{3,4}$'
RE_COUNT='^[1-9][0-9]?$'
RE_SIZE='^[1-9][0-9]{0,3}[km]$'
RE_MEM='^[1-9][0-9]{0,4}[KMG]$'

HOST=""
for k in HOST "${KEYS[@]}"; do printf -v "$k" '%s' ''; printf -v "ARG_$k" '%s' ''; done
ASSUME_YES=0 CHECK_ONLY=0 FORCE_CERT=0 TTY=0

STEP_NUM=0 STEP_TOTAL=0 STEP_NAME="" STEP_STATUS=ok
RESULTS=() NOTES=()
RESTART_NEEDED=0 CHANGED=0 FAIL_LINE="" CHECK_FAILS=0

regex_for() {
  case $1 in
    HOST) echo "$RE_HOST" ;; NAME) echo "$RE_NAME" ;; DOMAIN) echo "$RE_DOMAIN" ;;
    EMAIL) echo "$RE_EMAIL" ;; DB) echo "$RE_DB" ;; REPO) echo "$RE_REPO" ;;
    BRANCH) echo "$RE_BRANCH" ;; PYTHON_VERSION) echo "$RE_PYVER" ;;
    NODE_MAJOR) echo "$RE_NODEMAJ" ;; PORT) echo "$RE_PORT" ;;
    WORKERS|THREADS) echo "$RE_COUNT" ;; MAX_BODY) echo "$RE_SIZE" ;;
    BUILD_MEMORY_MAX|BUILD_SWAP_MAX) echo "$RE_MEM" ;;
  esac
}

prompt_for() {
  case $1 in
    HOST)   echo "ssh alias of the server (from ~/.ssh/config)" ;;
    NAME)   echo "Project name (lowercase letters, digits, - _)" ;;
    DOMAIN) echo "Public domain (e.g. app.example.com)" ;;
    EMAIL)  echo "Email for Let's Encrypt notices" ;;
    DB)     echo "Database: postgres (on the server), sqlite or external" ;;
    REPO)   echo "Git SSH URL the server deploys from (none = deploy from the Mac)" ;;
    BRANCH) echo "Branch to deploy by default" ;;
  esac
}

default_for() { # shared defaults; empty means the setting is required
  case $1 in
    DB) echo postgres ;;
    BRANCH) echo main ;;
    WORKERS|THREADS) echo 2 ;;
    MAX_BODY) echo 1m ;;
    BUILD_MEMORY_MAX) echo 250M ;;
    BUILD_SWAP_MAX) echo 1G ;;
  esac
}

flag_for() { printf -- '--%s' "$(printf '%s' "$1" | tr 'A-Z_' 'a-z-')"; }

envfile_get() { # envfile_get KEY FILE: its value, without quotes or a trailing " # comment"
  [ -r "$2" ] || return 0
  sed -n "s/^$1=//p" "$2" | tail -n 1 |
    sed -e 's/[[:space:]][[:space:]]*#.*$//' -e 's/[[:space:]]*$//' -e "s/^'\(.*\)'\$/\1/" -e 's/^"\(.*\)"$/\1/'
}

quote_words() { [ $# -eq 0 ] || printf '%q ' "$@"; } # shell-quoted, for writing arrays into scripts

node_major_of() { # node_major_of package.json: first major version in "engines": {"node": "..."}
  sed -n 's/.*"node"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -n 1 | grep -o '[0-9][0-9]*' | head -n 1 || true
}

# ---------------------------------------------------------------- output
say()  { printf '  %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }
die()  { printf '✗ %s\n' "$*" >&2; exit 1; }
skip() { STEP_STATUS=skipped; NOTES+=("$STEP_NAME: $*"); printf '  - skipped: %s\n' "$*"; }

print_summary() {
  local r
  echo
  echo "Summary"
  if [ ${#RESULTS[@]} -gt 0 ]; then
    for r in "${RESULTS[@]}"; do printf '  %s\n' "$r"; done
  fi
  if [ ${#NOTES[@]} -gt 0 ]; then
    echo
    echo "Still to do"
    for r in "${NOTES[@]}"; do printf '  - %s\n' "$r"; done
  fi
}

on_exit() {
  local rc=$?
  if [ $rc -ne 0 ] && [ -n "$STEP_NAME" ]; then
    echo >&2
    printf '✗ FAILED at step %s/%s: %s' "$STEP_NUM" "$STEP_TOTAL" "$STEP_NAME" >&2
    [ -n "$FAIL_LINE" ] && printf ' (script line %s)' "$FAIL_LINE" >&2
    printf '\n  Fix the cause above and re-run; completed steps are skipped quickly.\n' >&2
    RESULTS+=("FAIL     $STEP_NAME")
  fi
  [ -n "$STEP_NAME" ] && print_summary
  exit $rc
}

run_step() { # run_step N "label" function
  STEP_NUM=$1; STEP_NAME=$2; STEP_STATUS=ok
  printf '\n[%s/%s] %s\n' "$STEP_NUM" "$STEP_TOTAL" "$STEP_NAME"
  "$3"
  if [ "$STEP_STATUS" = ok ]; then RESULTS+=("ok       $STEP_NAME"); else RESULTS+=("skipped  $STEP_NAME"); fi
}

ask() { # ask VAR "Prompt" default regex
  local var=$1 prompt=$2 def=$3 re=$4 ans
  while :; do
    if [ -n "$def" ]; then printf '%s [%s]: ' "$prompt" "$def" >/dev/tty; else printf '%s: ' "$prompt" >/dev/tty; fi
    IFS= read -r ans </dev/tty || die "could not read an answer for '$prompt'"
    ans=${ans:-$def}
    if [[ $ans =~ $re ]]; then printf -v "$var" '%s' "$ans"; return 0; fi
    echo "  not valid, try again" >/dev/tty
  done
}

# ---------------------------------------------------------------- on the Mac
local_default_for() { # defaults that come from this checkout
  local v
  case $1 in
    NAME)
      v=$(basename "$(cd "$SCRIPT_DIR/.." && pwd)" | tr 'A-Z.' 'a-z-' | cut -c1-31)
      [[ $v =~ $RE_NAME ]] && echo "$v" ;;
    REPO)
      v=$(git -C "$SCRIPT_DIR/.." remote get-url origin 2>/dev/null || true)
      if [[ $v =~ $RE_REPO ]]; then echo "$v"; else echo none; fi ;;
    *) default_for "$1" ;;
  esac
}

save_setting() { # save_setting FILE KEY VALUE: append to the Mac settings file
  if [ ! -f "$1" ]; then
    ( umask 077
      printf '# Deploy target for hosting/provision.sh and hosting/deploy.sh (see hosting/.env.example).\n' > "$1" )
  fi
  printf 'DEPLOY_%s=%s\n' "$2" "$3" >> "$1"
}

project_versions() { # PYTHON_VERSION and NODE_MAJOR from the project's own files
  local root f
  root=$(cd "$SCRIPT_DIR/.." && pwd)
  f="$root/$BACKEND_DIR/.python-version"
  [ -f "$f" ] || die "$f is missing: put the Python version the server should run in it (e.g. 3.13)"
  PYTHON_VERSION=$(tr -d '[:space:]' < "$f")
  NODE_MAJOR=none
  if [ -n "$FRONTEND_DIR" ]; then
    f="$root/$FRONTEND_DIR/package.json"
    NODE_MAJOR=$(node_major_of "$f")
    [ -n "$NODE_MAJOR" ] || die "$f needs \"engines\": {\"node\": \">=22\"}; the server installs that major version"
  fi
}

mac_main() {
  local env_file="$SCRIPT_DIR/.env" k v flag remote_dir
  local remote=() keys
  while [ $# -gt 0 ]; do
    case "$1" in
      --env) env_file="${2:?--env needs a file}"; shift 2 ;;
      --host|--name|--domain|--email|--db|--repo|--branch|--port|--workers|--threads|--max-body|--build-memory-max|--build-swap-max)
        k=$(printf '%s' "${1#--}" | tr 'a-z-' 'A-Z_')
        printf -v "ARG_$k" '%s' "${2:?$1 needs a value}"
        shift 2 ;;
      -y|--yes) ASSUME_YES=1; shift ;;
      --check) CHECK_ONLY=1; remote+=(--check); shift ;;
      --force-cert) remote+=(--force-cert); shift ;;
      -h|--help) usage; exit 0 ;;
      *) usage >&2; die "unknown option: $1" ;;
    esac
  done
  if [ $ASSUME_YES = 0 ] && { : </dev/tty; } 2>/dev/null; then TTY=1; fi

  # Flags win for this run. Anything still missing is asked for (or defaulted) and saved,
  # so the file ends up complete; flags never overwrite a line that is already there.
  keys=("${ASKED_KEYS[@]}")
  [ $CHECK_ONLY = 0 ] || keys=(HOST NAME)
  for k in "${keys[@]}" "${OPTIONAL_KEYS[@]}"; do
    v=ARG_$k; v=${!v}
    [ -n "$v" ] || v=$(envfile_get "DEPLOY_$k" "$env_file")
    printf -v "$k" '%s' "$v"
  done
  for k in "${keys[@]}"; do
    [ -z "${!k}" ] || [ -n "$(envfile_get "DEPLOY_$k" "$env_file")" ] || save_setting "$env_file" "$k" "${!k}"
    [ -z "${!k}" ] || continue
    if [ $TTY = 1 ]; then
      ask "$k" "$(prompt_for "$k")" "$(local_default_for "$k")" "$(regex_for "$k")"
    else
      v=$(local_default_for "$k")
      [ -n "$v" ] || die "DEPLOY_$k is not set in $env_file (or pass $(flag_for "$k"))"
      printf -v "$k" '%s' "$v"
    fi
    save_setting "$env_file" "$k" "${!k}"
    say "saved DEPLOY_$k in $env_file"
  done

  DOMAIN=$(printf '%s' "$DOMAIN" | tr 'A-Z' 'a-z')
  for k in "${keys[@]}" "${OPTIONAL_KEYS[@]}"; do
    [ -z "${!k}" ] || [[ ${!k} =~ $(regex_for "$k") ]] || die "invalid DEPLOY_$k '${!k}' in $env_file"
  done

  remote+=(--name "$NAME")
  if [ $CHECK_ONLY = 0 ]; then
    project_versions
    for k in DOMAIN EMAIL DB REPO BRANCH "${OPTIONAL_KEYS[@]}" PYTHON_VERSION NODE_MAJOR; do
      [ -z "${!k}" ] || remote+=("$(flag_for "$k")" "${!k}")
    done
  fi

  remote_dir="/tmp/provision-$NAME"
  ssh "$HOST" "mkdir -p '$remote_dir'"
  scp -q "$SCRIPT_DIR/provision.sh" "$HOST:$remote_dir/provision.sh"
  exec ssh -t "$HOST" "bash '$remote_dir/provision.sh' $(printf '%q ' "${remote[@]}")"
}

# ---------------------------------------------------------------- on the server
srv_env_get() { # srv_env_get KEY FILE: its value, or nothing (also when FILE doesn't exist yet)
  sudo sh -c '[ ! -r "$2" ] || sed -n "s/^$1=//p" "$2" | tail -n 1' _ "$1" "$2"
}

app_names() { # apps this script provisioned: /srv/*/.env with deploy settings
  local f
  for f in /srv/*/.env; do
    [ -e "$f" ] && sudo grep -q '^DEPLOY_DOMAIN=' "$f" && basename "$(dirname "$f")"
  done
  return 0
}

port_listening() { ss -Hltn "sport = :$1" 2>/dev/null | grep -q .; }

unit_ports() { # "unit port" for every gunicorn unit on this server, ours and older ones
  grep -Ho -- '--bind 127\.0\.0\.1:[0-9]*' /etc/systemd/system/*.service 2>/dev/null |
    sed 's|^/etc/systemd/system/\(.*\)\.service:--bind 127\.0\.0\.1:| \1 |; s/^ //' || true
}

free_port() { # first port from 8000 that no other app's unit claims and nothing listens on
  local p=8000 used
  used=$(unit_ports | awk -v me="$NAME" '$1 != me {print $2}')
  while grep -qx "$p" <<<"$used" || port_listening "$p"; do p=$((p + 1)); done
  echo "$p"
}

port_owner() { unit_ports | awk -v me="$NAME" -v p="$PORT" '$1 != me && $2 == p {print $1; exit}'; }

load_settings() {
  local k v other names
  NAME=$ARG_NAME
  if [ -z "$NAME" ]; then
    names=$(app_names)
    [ "$(printf '%s\n' "$names" | grep -c .)" = 1 ] || die "pass --name (apps on this server: $(echo ${names:-none}))"
    NAME=$names
  fi
  [[ $NAME =~ $RE_NAME ]] || die "invalid project name '$NAME' (lowercase letters, digits, - and _; starts with a letter)"
  ENV_FILE="/srv/$NAME/.env"
  if [ $CHECK_ONLY = 1 ] && [ -z "$(srv_env_get DEPLOY_DOMAIN "$ENV_FILE")" ]; then
    die "no deploy settings in $ENV_FILE: provision '$NAME' first"
  fi

  for k in "${KEYS[@]}"; do
    [ "$k" = NAME ] && continue
    v=ARG_$k; v=${!v}
    [ -n "$v" ] || v=$(srv_env_get "DEPLOY_$k" "$ENV_FILE")
    if [ -z "$v" ]; then
      case $k in
        PORT) v=$(free_port) ;;
        REPO) v=none ;;
        *) v=$(default_for "$k") ;;
      esac
    fi
    [ -n "$v" ] || die "missing $(flag_for "$k"): run ./hosting/provision.sh from your Mac, or pass it"
    printf -v "$k" '%s' "$v"
  done

  DOMAIN=$(printf '%s' "$DOMAIN" | tr 'A-Z' 'a-z')
  for k in "${KEYS[@]}"; do
    [[ ${!k} =~ $(regex_for "$k") ]] || die "invalid $(flag_for "$k") '${!k}'"
  done
  [ "$PORT" -le 65535 ] || die "invalid --port '$PORT'"
  other=$(port_owner)
  [ -z "$other" ] || die "port $PORT is already used by '$other'; pick another with DEPLOY_PORT"
  return 0
}

# ---------------------------------------------------------------- file helpers
render() {
  sed -e "s|@NAME@|$NAME|g" -e "s|@DOMAIN@|$DOMAIN|g" -e "s|@DEPLOY_USER@|$DEPLOY_USER|g" \
      -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@WSGI@|$WSGI|g" -e "s|@PORT@|$PORT|g" \
      -e "s|@WORKERS@|$WORKERS|g" -e "s|@THREADS@|$THREADS|g" \
      -e "s|@MAX_BODY@|$MAX_BODY|g" -e "s|@HEALTH_PATH@|$HEALTH_PATH|g" \
      -e "s|@PYTHON_VERSION@|$PYTHON_VERSION|g" -e "s|@NODE_MAJOR@|$NODE_MAJOR|g"
}

install_file() { # install_file DEST MODE OWNER:GROUP < template. Sets CHANGED=1 if the content differed.
  local dest=$1 mode=$2 owner=$3 tmp
  tmp=$(mktemp)
  render > "$tmp"
  if sudo test -f "$dest" && sudo cmp -s "$tmp" "$dest"; then
    CHANGED=0
  else
    CHANGED=1
    sudo install -o "${owner%%:*}" -g "${owner##*:}" -m "$mode" "$tmp" "$dest"
  fi
  sudo chown "$owner" "$dest"
  sudo chmod "$mode" "$dest"
  rm -f "$tmp"
  if [ $CHANGED = 1 ]; then say "wrote $dest"; else say "unchanged $dest"; fi
}

env_has() { grep -Eq "^$1=[^[:space:]'\"]" "$ENV_FILE"; } # set and not empty
env_set() { # env_set KEY VALUE: replace the first KEY= line, or append. Never prints the value.
  local tmp; tmp=$(mktemp)
  awk -v k="$1" -v v="$2" '
    $0 ~ "^" k "=" && !done { print k "=" v; done = 1; next }
    { print }
    END { if (!done) print k "=" v }' "$ENV_FILE" > "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
  RESTART_NEEDED=1
  say "set $1"
}
env_default() { env_has "$1" || env_set "$1" "$2"; } # env_default KEY VALUE
env_sync() { # env_sync KEY VALUE: set KEY when it differs. Deploy settings only, so no restart.
  local restart=$RESTART_NEEDED
  [ "$(envfile_get "$1" "$ENV_FILE")" = "$2" ] && return 0
  env_set "$1" "$2"
  RESTART_NEEDED=$restart
}
admin_url() { # ADMIN_URL from .env as Django reads it: no leading slash, one trailing slash
  local a; a=$(envfile_get ADMIN_URL "$ENV_FILE"); a=${a#/}; a=${a%/}
  printf '%s/' "${a:-django-admin}"
}
gen_secret() { python3 -c 'import secrets; print(secrets.token_urlsafe(50))'; }
gen_fernet_key() { python3 -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'; }

as_postgres() { (cd / && sudo -u postgres "$@"); }
pg_has() { [ "$(as_postgres psql -tAc "SELECT 1 FROM $1 WHERE $2 = '$NAME'")" = 1 ]; } # pg_has CATALOG COLUMN

# ---------------------------------------------------------------- runtime installers
uv_install() {
  local tmp
  if [ ! -x /usr/local/bin/uv ]; then
    tmp=$(mktemp -d)
    curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null
    rm -rf "$tmp"
    say "installed uv $(/usr/local/bin/uv --version)"
  else
    say "uv $(/usr/local/bin/uv --version) present"
  fi
  # Managed Python lives in /opt/uv/python (outside /home) so the sandboxed service user
  # with ProtectHome=true can execute the interpreter symlinked from /srv/NAME/venv.
  sudo install -d -o root -g root -m 755 "$UV_PYTHON_DIR"
  if ! UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" /usr/local/bin/uv python find "$PYTHON_VERSION" >/dev/null 2>&1; then
    sudo env UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" /usr/local/bin/uv python install "$PYTHON_VERSION"
    sudo chmod -R a+rX "$UV_PYTHON_DIR"
    say "installed Python $PYTHON_VERSION in $UV_PYTHON_DIR"
  else
    say "Python $PYTHON_VERSION present in $UV_PYTHON_DIR"
  fi
}

node_install() {
  local major=$1 dir="/usr/local/lib/node-$1" have arch sums file tmp b
  have=$("$dir/bin/node" -v 2>/dev/null | sed -n 's/^v\([0-9]*\)\..*/\1/p' || true)
  if [ "$have" = "$major" ] && [ -x "$dir/bin/corepack" ] && [ -e "$dir/bin/pnpm" ]; then
    say "Node $("$dir/bin/node" -v) present in $dir"
  else
    case $(uname -m) in
      x86_64) arch=x64 ;; aarch64) arch=arm64 ;; *) die "no Node.js build for $(uname -m)" ;;
    esac
    sums=$(curl -fsSL "https://nodejs.org/dist/latest-v$major.x/SHASUMS256.txt")
    file=$(printf '%s\n' "$sums" | awk -v f="linux-$arch.tar.xz" '$2 ~ f"$" {print $2; exit}')
    [ -n "$file" ] || die "could not find the Node.js $major download for linux-$arch"
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/$file" "https://nodejs.org/dist/latest-v$major.x/$file"
    (cd "$tmp" && printf '%s\n' "$sums" | grep "  $file\$" | sha256sum -c --quiet -) ||
      die "Node.js download failed its checksum"
    sudo rm -rf "$dir"
    sudo mkdir -p "$dir"
    sudo tar -xJf "$tmp/$file" -C "$dir" --strip-components=1
    rm -rf "$tmp"
    # Run through node directly: corepack's `env node` shebang can't see $dir/bin under sudo.
    sudo "$dir/bin/node" "$dir/bin/corepack" enable --install-directory "$dir/bin"
    say "installed Node $("$dir/bin/node" -v) in $dir"
  fi
  for b in node npm npx corepack pnpm; do
    if [ -e "$dir/bin/$b" ] && [ ! -e "/usr/local/bin/$b" ]; then
      sudo ln -sf "$dir/bin/$b" "/usr/local/bin/$b"
    fi
  done
}

# ---------------------------------------------------------------- steps
step_packages() {
  local p missing="" pkgs="nginx python3 python3-venv certbot python3-certbot-nginx rsync curl ca-certificates git xz-utils"
  case $DB in
    sqlite)   pkgs="$pkgs sqlite3" ;;
    postgres) pkgs="$pkgs postgresql" ;;
    external) pkgs="$pkgs postgresql-client" ;;
  esac
  for p in $pkgs; do
    dpkg -s "$p" >/dev/null 2>&1 || missing="$missing $p"
  done
  if [ -z "$missing" ]; then say "all packages already installed"; return 0; fi
  say "installing:$missing"
  sudo apt-get update -qq
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y $missing
}

step_runtimes() {
  uv_install
  if [ "$REPO" != none ] && [ "$NODE_MAJOR" != none ]; then
    node_install "$NODE_MAJOR"
  fi
}

step_service_user() {
  if id -u "$NAME" >/dev/null 2>&1; then
    say "user '$NAME' exists"
  else
    sudo adduser --system --group --no-create-home "$NAME"
    say "created system user '$NAME' (no login)"
  fi
}

tidy_modes() {
  # Ubuntu logins use umask 002, so venv, uv and collectstatic leave group-writable files.
  # The guide says these trees are writable only by the deploy user; strip group/other write.
  local d
  for d in app frontend bin venv; do
    if [ -d "$ROOT/$d" ]; then
      sudo find "$ROOT/$d" -xdev ! -type l -perm /022 -exec chmod go-w {} +
    fi
  done
}

step_dirs() {
  local d venv_py=""
  sudo mkdir -p "$ROOT"/{app,frontend,data,backups,bin}
  sudo chown "$DEPLOY_USER:$DEPLOY_USER" "$ROOT"
  # fix only what is mis-owned (never a blanket -R: that would clobber data/ and backups/)
  for d in app frontend bin venv; do
    if [ -d "$ROOT/$d" ]; then
      sudo find "$ROOT/$d" -xdev \( ! -user "$DEPLOY_USER" -o ! -group "$DEPLOY_USER" \) -exec chown "$DEPLOY_USER:$DEPLOY_USER" {} +
    fi
  done
  sudo chown "$NAME:$NAME" "$ROOT/data" "$ROOT/backups"
  sudo chmod 755 "$ROOT" "$ROOT"/{app,frontend,bin,data}
  sudo chmod 700 "$ROOT/backups"
  sudo find "$ROOT/backups" -mindepth 1 \( ! -user "$NAME" -o ! -group "$NAME" \) -exec chown "$NAME:$NAME" {} +
  sudo find "$ROOT/backups" -mindepth 1 -type d ! -perm 700 -exec chmod 700 {} +
  sudo find "$ROOT/backups" -mindepth 1 -type f ! -perm 600 -exec chmod 600 {} +
  if [ -x "$ROOT/venv/bin/python" ]; then
    venv_py=$("$ROOT/venv/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
  fi
  if [ "$venv_py" = "${PYTHON_VERSION%.*}" ] || [ "$venv_py" = "$PYTHON_VERSION" ]; then
    say "venv exists (Python $venv_py)"
  else
    UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" /usr/local/bin/uv venv --clear --python "$PYTHON_VERSION" "$ROOT/venv" >/dev/null
    RESTART_NEEDED=1
    say "created $ROOT/venv (Python $PYTHON_VERSION)"
  fi
  tidy_modes
  say "$ROOT/{app,frontend,venv,data,backups,bin} ready"
}

step_swap() {
  local have
  have=$(free -m | awk '/^Swap:/ {print $2}')
  if [ "${have:-0}" -ge 512 ]; then say "swap already present (${have} MB)"; return 0; fi
  if [ ! -f /swapfile ]; then
    sudo fallocate -l "${SWAP_MB}M" /swapfile 2>/dev/null ||
      sudo dd if=/dev/zero of=/swapfile bs=1M count="$SWAP_MB" status=none
  fi
  sudo chmod 600 /swapfile
  sudo chown root:root /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -qE '^/swapfile[[:space:]]' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  say "enabled ${SWAP_MB} MB swap"
}

step_database() {
  case $DB in
    sqlite)
      say "SQLite at $ROOT/data/db.sqlite3 (the first migrate creates it)" ;;
    external)
      say "external PostgreSQL: the app uses DATABASE_URL from .env as-is" ;;
    postgres)
      sudo systemctl enable --now postgresql >/dev/null 2>&1
      # The role matches the service user, so the app logs in over the local socket with
      # peer authentication: no password exists to leak.
      if pg_has pg_roles rolname; then
        say "role '$NAME' exists"
      else
        as_postgres createuser --no-superuser --no-createdb --no-createrole "$NAME"
        say "created role '$NAME'"
      fi
      if pg_has pg_database datname; then
        say "database '$NAME' exists"
      else
        as_postgres createdb -O "$NAME" "$NAME"
        say "created database '$NAME' owned by '$NAME'"
      fi ;;
  esac
}

step_env() {
  local scheme k
  if [ ! -e "$ENV_FILE" ]; then
    sudo install -o "$DEPLOY_USER" -g "$NAME" -m 640 /dev/null "$ENV_FILE"
    say "created $ENV_FILE"
  fi
  sudo chown "$DEPLOY_USER:$NAME" "$ENV_FILE"
  sudo chmod 640 "$ENV_FILE"

  env_default DJANGO_ENV production
  env_default DEBUG False
  env_default ALLOWED_HOSTS "$DOMAIN"
  env_default CSRF_TRUSTED_ORIGINS "https://$DOMAIN"
  case $DB in
    sqlite)   env_default DATABASE_URL "sqlite:///$ROOT/data/db.sqlite3" ;;
    # No host in the URL: local socket. PGHOST pins the socket folder (pip's psycopg wheels
    # may default to /tmp, which PrivateTmp hides) and works with any URL parser; an
    # encoded host (%2F...) is not decoded by django-environ. Older runs wrote that form.
    postgres)
      if grep -qx "DATABASE_URL=postgres://%2Fvar%2Frun%2Fpostgresql/$NAME" "$ENV_FILE"; then
        env_set DATABASE_URL "postgres:///$NAME"
        say "DATABASE_URL: replaced the encoded socket host with postgres:///$NAME"
      fi
      env_default DATABASE_URL "postgres:///$NAME"
      env_default PGHOST /var/run/postgresql ;;
    external)
      if ! env_has DATABASE_URL; then
        grep -q '^# *DATABASE_URL=' "$ENV_FILE" ||
          printf '# DATABASE_URL=postgres://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require\n' >> "$ENV_FILE"
        NOTES+=("Set DATABASE_URL in $ENV_FILE (a placeholder is there), then re-run")
      fi ;;
  esac
  scheme=$(sed -n 's/^DATABASE_URL=\([a-z0-9+]*\):.*/\1/p' "$ENV_FILE" | head -n 1)
  case "$DB:$scheme" in
    sqlite:sqlite*|postgres:postgres*|external:postgres*|external:) ;;
    *) warn "DATABASE_URL in .env is a $scheme URL but --db is $DB; edit .env if you are switching" ;;
  esac

  # Generated once, never replaced.
  env_has ADMIN_URL || env_set ADMIN_URL "admin-$(python3 -c 'import secrets; print(secrets.token_hex(5))')/"
  env_has SECRET_KEY || env_set SECRET_KEY "$(gen_secret)"
  env_has SETTINGS_ENCRYPTION_KEY || env_set SETTINGS_ENCRYPTION_KEY "$(gen_fernet_key)"

  # The deploy settings, so bin/deploy and later runs on the server have them. hosting/.env
  # on the Mac is the source: every run from there rewrites these lines.
  grep -q '^DEPLOY_' "$ENV_FILE" ||
    printf '\n# Deploy settings: hosting/provision.sh rewrites these on every run (edit hosting/.env instead)\n' >> "$ENV_FILE"
  for k in "${KEYS[@]}"; do
    [ "$k" = NAME ] || env_sync "DEPLOY_$k" "${!k}"
  done
  grep -qE "^ALLOWED_HOSTS=.*$DOMAIN" "$ENV_FILE" || warn "ALLOWED_HOSTS in .env does not contain $DOMAIN"
  say ".env: -rw-r----- $DEPLOY_USER:$NAME (values not shown)"
}

backup_script() {
  cat <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /

DEST=/srv/@NAME@/backups
mkdir -p "$DEST"/daily "$DEST"/weekly "$DEST"/monthly

stamp=$(date +%F)
tmp=$(mktemp "$DEST/.tmp.XXXXXX")
trap 'rm -f "$tmp"' EXIT

EOF
  case $DB in
    sqlite) cat <<'EOF'
DB=/srv/@NAME@/data/db.sqlite3
if [ ! -f "$DB" ]; then echo "backup skipped: no database yet"; exit 0; fi

sqlite3 "$DB" ".backup '$tmp'"
if [ "$(sqlite3 "$tmp" 'PRAGMA integrity_check;')" != "ok" ]; then
  echo "backup FAILED: integrity check did not pass" >&2
  exit 1
fi

file="db-$stamp.sqlite3.gz"
gzip -c "$tmp" > "$DEST/daily/$file"
EOF
    ;;
    postgres) cat <<'EOF'
# peer authentication over the local socket: this runs as @NAME@, which owns the database
pg_dump -Fc -f "$tmp" @NAME@
pg_restore -l "$tmp" > /dev/null || { echo "backup FAILED: dump is not readable" >&2; exit 1; }

file="db-$stamp.dump"
mv "$tmp" "$DEST/daily/$file"
EOF
    ;;
    external) cat <<'EOF'
set -a; . /srv/@NAME@/.env; set +a
pg_dump -Fc -f "$tmp" "$DATABASE_URL"
pg_restore -l "$tmp" > /dev/null || { echo "backup FAILED: dump is not readable" >&2; exit 1; }

file="db-$stamp.dump"
mv "$tmp" "$DEST/daily/$file"
EOF
    ;;
  esac
  cat <<'EOF'

# weekly = the Sunday copy, monthly = the 1st-of-month copy
if [ "$(date +%u)" = 7 ]; then cp "$DEST/daily/$file" "$DEST/weekly/$file"; fi
if [ "$(date +%d)" = 01 ]; then cp "$DEST/daily/$file" "$DEST/monthly/$file"; fi

# keep the newest N in each folder
prune() { ls -1t "$1" | tail -n +"$(( $2 + 1 ))" | while read -r f; do rm -f "$1/$f"; done; }
prune "$DEST/daily" 4
prune "$DEST/weekly" 4
prune "$DEST/monthly" 6

echo "backup ok: $file"
EOF
}

step_bin() {
  install_file "$ROOT/bin/manage" 755 "$DEPLOY_USER:$DEPLOY_USER" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
set -a; . /srv/@NAME@/.env; set +a
cd @APP_DIR@
exec /srv/@NAME@/venv/bin/python manage.py "$@"
EOF
  install_file "$ROOT/bin/backup-db" 755 "$DEPLOY_USER:$DEPLOY_USER" < <(backup_script)
}

deploy_script() {
  cat <<'EOF'
#!/usr/bin/env bash
# deploy: fetch a commit into staging, test and build it there, and only then copy it live.
# Installed by hosting/provision.sh. The repo, branch and build limits are the DEPLOY_* lines
# in /srv/@NAME@/.env; the Python and Node versions come from the commit being deployed.
#
#   /srv/@NAME@/bin/deploy          deploy the tip of DEPLOY_BRANCH
#   /srv/@NAME@/bin/deploy REF      deploy a branch, tag or commit (e.g. to roll back)
#
# Run as the deploy user (owner of app/, frontend/, venv/), with sudo. Nothing under app/
# or frontend/ changes until tests and the build have passed in staging.
set -Eeuo pipefail
umask 022

NAME=@NAME@
ROOT=/srv/$NAME
STAGE=$ROOT/staging
SRC=$STAGE/src
PORT=@PORT@
DOMAIN=@DOMAIN@
HEALTH_PATH=@HEALTH_PATH@
UV_PYTHON_DIR=/opt/uv/python

# Project layout and commands, from the top of hosting/provision.sh (re-provision to change them)
EOF
  printf 'BACKEND=%q\nFRONTEND=%q\nTEST_CMD=%q\nBUILD_CMD=%q\n' "$BACKEND_DIR" "$FRONTEND_DIR" "$TEST_CMD" "$BUILD_CMD"
  printf 'EXTRA=(%s)\n' "$(quote_words ${EXTRA[@]+"${EXTRA[@]}"})"
  printf 'EXCLUDES=(%s)\n' "$(quote_words ${EXCLUDES[@]+"${EXCLUDES[@]}"})"
  cat <<'EOF'

die()  { printf '✗ %s\n' "$*" >&2; exit 1; }
step() { printf '\n== %s\n' "$*"; }

[ "$(id -un)" = "$(stat -c %U "$ROOT/app")" ] ||
  die "run as $(stat -c %U "$ROOT/app") (the owner of $ROOT/app), not $(id -un)"
sudo -n true 2>/dev/null || sudo -v || die "sudo access is required"

setting() { sed -n "s/^DEPLOY_$1=//p" "$ROOT/.env" | tail -n 1; }
REPO=$(setting REPO)
BRANCH=$(setting BRANCH)
BUILD_MEMORY_MAX=$(setting BUILD_MEMORY_MAX); BUILD_MEMORY_MAX=${BUILD_MEMORY_MAX:-250M}
BUILD_SWAP_MAX=$(setting BUILD_SWAP_MAX); BUILD_SWAP_MAX=${BUILD_SWAP_MAX:-1G}
[ -n "$REPO" ] && [ "$REPO" != none ] || die "DEPLOY_REPO is not set in $ROOT/.env (run hosting/provision.sh)"
# fetch through the read-only deploy key's ssh alias (in ~/.ssh/config)
REPO_URL="${REPO%%@*}@deploy-$NAME:${REPO#*:}"
REF=${1:-${BRANCH:-main}}

mkdir -p "$STAGE"
exec 9>"$STAGE/.lock"
flock -n 9 || die "another deploy is running"

step "Fetch $REF"
if [ ! -d "$SRC/.git" ]; then
  git clone --quiet "$REPO_URL" "$SRC"
fi
git -C "$SRC" remote set-url origin "$REPO_URL"
git -C "$SRC" fetch --quiet --prune --tags --force origin
if SHA=$(git -C "$SRC" rev-parse --verify --quiet "origin/$REF^{commit}"); then :
elif SHA=$(git -C "$SRC" rev-parse --verify --quiet "$REF^{commit}"); then :
else die "unknown branch, tag or commit: $REF"; fi
git -C "$SRC" checkout --quiet --force --detach "$SHA"
# A clean tree every time; dependency caches outside the repo's own files survive.
git -C "$SRC" clean -ffdxq -e node_modules
printf '  %s %s\n' "$(git -C "$SRC" rev-parse --short HEAD)" "$(git -C "$SRC" log -1 --format=%s)"

# Runtimes come from the checked-out commit, so a rollback gets the versions it was built with.
PYTHON_VERSION=@PYTHON_VERSION@
[ ! -f "$SRC/$BACKEND/.python-version" ] || PYTHON_VERSION=$(tr -d '[:space:]' < "$SRC/$BACKEND/.python-version")
NODE_DIR=""
if [ -n "$FRONTEND" ]; then
  NODE_MAJOR=$(sed -n 's/.*"node"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$SRC/$FRONTEND/package.json" 2>/dev/null |
    head -n 1 | grep -o '[0-9][0-9]*' | head -n 1 || true)
  NODE_MAJOR=${NODE_MAJOR:-@NODE_MAJOR@}
  NODE_DIR="/usr/local/lib/node-$NODE_MAJOR"
  [ -x "$NODE_DIR/bin/node" ] || die "Node $NODE_MAJOR is not installed at $NODE_DIR: run ./hosting/provision.sh from your Mac, then deploy again"
fi
if ! UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" /usr/local/bin/uv python find "$PYTHON_VERSION" >/dev/null 2>&1; then
  sudo env UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" /usr/local/bin/uv python install "$PYTHON_VERSION"
  sudo chmod -R a+rX "$UV_PYTHON_DIR"
fi

# Tests and the build run in a memory-capped scope: past BUILD_MEMORY_MAX they swap their own
# memory, not the live app's, and past BUILD_SWAP_MAX only they are killed. Low CPU/IO priority.
limited() {
  local run_path="$NODE_DIR/bin:$STAGE/venv/bin:/usr/local/bin:$PATH"
  if command -v systemd-run >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    sudo systemd-run --quiet --scope --collect \
      -p MemoryMax="$BUILD_MEMORY_MAX" -p MemorySwapMax="$BUILD_SWAP_MAX" -- \
      runuser -u "$(id -un)" -- env HOME="$HOME" PATH="$run_path" \
      UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" COREPACK_ENABLE_DOWNLOAD_PROMPT=0 CI=1 \
      nice -n 10 ionice -c 3 bash -c "$1"
  else
    printf '  (no systemd: running without a memory cap)\n'
    env PATH="$run_path" UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" COREPACK_ENABLE_DOWNLOAD_PROMPT=0 CI=1 \
      nice -n 10 bash -c "$1"
  fi
}

step "Backend: sync and test (staging, Python $PYTHON_VERSION)"
if [ -f "$SRC/$BACKEND/uv.lock" ]; then
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" UV_PROJECT_ENVIRONMENT="$STAGE/venv" \
    /usr/local/bin/uv sync --frozen -q --python "$PYTHON_VERSION" --project "$SRC/$BACKEND"
elif [ -f "$SRC/$BACKEND/requirements.txt" ]; then
  [ -x "$STAGE/venv/bin/python" ] ||
    UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" /usr/local/bin/uv venv --python "$PYTHON_VERSION" "$STAGE/venv" >/dev/null
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" /usr/local/bin/uv pip install --python "$STAGE/venv/bin/python" \
    --no-cache -q -r "$SRC/$BACKEND/requirements.txt"
else
  die "neither $BACKEND/uv.lock nor $BACKEND/requirements.txt found in the repo"
fi

if [ -n "$TEST_CMD" ]; then
  limited "cd '$SRC/$BACKEND' && $TEST_CMD" || die "tests failed: nothing was changed"
else
  printf '  no TEST_CMD: tests skipped\n'
fi

if [ -n "$FRONTEND" ]; then
  step "Frontend: build (staging, Node $("$NODE_DIR/bin/node" -v))"
  [ -n "$BUILD_CMD" ] || die "FRONTEND is set but BUILD_CMD is empty"
  limited "cd '$SRC/$FRONTEND' && $BUILD_CMD" || die "frontend build failed: nothing was changed"
  [ -f "$SRC/$FRONTEND/dist/index.html" ] || die "build finished but $FRONTEND/dist/index.html is missing"
fi

step "Back up the database"
sudo -u "$NAME" "$ROOT/bin/backup-db"

step "Copy into $ROOT"
excludes=(--exclude=__pycache__/ --exclude='*.pyc' --exclude=.pytest_cache/ --exclude=.env
          --exclude='db.sqlite3*' --exclude=media/ --exclude=staticfiles/ --exclude=tests/
          --exclude=conftest.py --exclude=.venv/ --exclude=node_modules/)
for e in ${EXCLUDES[@]+"${EXCLUDES[@]}"}; do excludes+=(--exclude="$e"); done
sources=()
for d in "$BACKEND" ${EXTRA[@]+"${EXTRA[@]}"}; do
  [ -d "$SRC/$d" ] || die "$d not found in the repo"
  sources+=("$SRC/$d")
done
rsync -a --delete "${excludes[@]}" "${sources[@]}" "$ROOT/app/"
[ -z "$FRONTEND" ] || rsync -a --delete "$SRC/$FRONTEND/dist/" "$ROOT/frontend/"
printf '  app/ and frontend/ updated\n'

step "Sync live venv, migrate, restart"
LIVE_BACKEND="$ROOT/app/$(basename "$BACKEND")"
if [ -f "$LIVE_BACKEND/uv.lock" ]; then
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" UV_PROJECT_ENVIRONMENT="$ROOT/venv" \
    /usr/local/bin/uv sync --frozen --no-dev -q --python "$PYTHON_VERSION" --project "$LIVE_BACKEND"
else
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" /usr/local/bin/uv pip install --python "$ROOT/venv/bin/python" \
    --no-cache -q -r "$LIVE_BACKEND/requirements.txt"
fi
sudo -u "$NAME" "$ROOT/bin/manage" migrate --noinput | tail -n 1
for f in "$ROOT"/data/db.sqlite3*; do
  if [ -e "$f" ]; then sudo chown "$NAME:$NAME" "$f"; sudo chmod 600 "$f"; fi
done
"$ROOT/bin/manage" collectstatic --noinput | tail -n 1
for d in app frontend venv; do
  find "$ROOT/$d" -xdev ! -type l -perm /022 -exec chmod go-w {} + 2>/dev/null || true
done
sudo systemctl restart "$NAME"
printf '%s %s %s %s\n' "$SHA" "$REF" "$(date -u +%FT%TZ)" "$(id -un)" > "$ROOT/REVISION"

step "Health check"
path=$HEALTH_PATH; [ "$path" = none ] && path=/
for _ in $(seq 1 20); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H "Host: $DOMAIN" "http://127.0.0.1:$PORT$path" || true)
  case $code in
    2??|3??) printf '  ok (%s -> %s)\n\nDeployed %s (%s).\n' "$path" "$code" "$(git -C "$SRC" rev-parse --short HEAD)" "$REF"; exit 0 ;;
  esac
  sleep 1
done
sudo journalctl -u "$NAME" -n 30 --no-pager >&2 || true
die "the app did not answer $path after the restart (last: ${code:-none}). The new code is live; fix forward, or deploy the previous commit: $ROOT/bin/deploy <sha>"
EOF
}

repo_host() { local h=${REPO#*@}; printf '%s' "${h%%:*}"; }  # git@github.com:o/r.git -> github.com
repo_user() { printf '%s' "${REPO%%@*}"; }
repo_path() { printf '%s' "${REPO#*:}"; }

step_git_deploy() {
  local key alias=deploy-$NAME cfg url
  if [ "$REPO" = none ]; then
    skip "no --repo: deploys come from the Mac (hosting/deploy-rsync.sh)"
    return 0
  fi
  [ "$BACKEND_DIR" != . ] || die "deploying from git needs the backend in its own folder (BACKEND_DIR), not ."

  # Read-only deploy key, used only for this repo through an ssh alias.
  key="$HOME/.ssh/deploy_$NAME"
  cfg="$HOME/.ssh/config"
  mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"
  if [ ! -f "$key" ]; then
    ssh-keygen -q -t ed25519 -N '' -C "$NAME deploy key ($(hostname))" -f "$key"
    say "created deploy key $key"
  fi
  touch "$cfg"; chmod 600 "$cfg"
  if ! grep -qx "Host $alias" "$cfg"; then
    cat >> "$cfg" <<EOF

# hosting/provision.sh: read-only deploy key for $NAME
Host $alias
  HostName $(repo_host)
  User $(repo_user)
  IdentityFile $key
  IdentitiesOnly yes
  BatchMode yes
  StrictHostKeyChecking accept-new
EOF
    say "added ssh alias $alias to $cfg"
  fi

  install -d -m 750 "$ROOT/staging"
  sudo chown "$DEPLOY_USER:$DEPLOY_USER" "$ROOT/staging"
  sudo chmod 750 "$ROOT/staging"
  install_file "$ROOT/bin/deploy" 755 "$DEPLOY_USER:$DEPLOY_USER" < <(deploy_script)

  url="$(repo_user)@$alias:$(repo_path)"
  if timeout 20 git ls-remote "$url" HEAD >/dev/null 2>&1; then
    say "repository reachable with the deploy key"
  else
    say "the deploy key can't read $REPO yet. Add it as a read-only deploy key"
    say "(GitHub: repo > Settings > Deploy keys > Add, leave write access off):"
    say "  $(cat "$key.pub")"
    NOTES+=("Add the deploy key in $key.pub to $REPO (read-only), then run ./hosting/deploy.sh")
  fi
}

step_systemd() {
  install_file "/etc/systemd/system/$NAME.service" 644 root:root <<'EOF'
[Unit]
Description=@NAME@ (gunicorn)
After=network.target postgresql.service

[Service]
User=@NAME@
Group=@NAME@
WorkingDirectory=@APP_DIR@
EnvironmentFile=/srv/@NAME@/.env
ExecStart=/srv/@NAME@/venv/bin/gunicorn @WSGI@ \
    --bind 127.0.0.1:@PORT@ \
    --workers @WORKERS@ --threads @THREADS@ --timeout 120 \
    --access-logfile -
Restart=on-failure
RestartSec=3

# basic sandboxing
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/srv/@NAME@/data

[Install]
WantedBy=multi-user.target
EOF
  if [ $CHANGED = 1 ]; then sudo systemctl daemon-reload; RESTART_NEEDED=1; fi
  sudo systemctl enable "$NAME" >/dev/null 2>&1
  say "service enabled at boot"
}

nginx_body() {
  cat <<'EOF'
    root /srv/@NAME@/frontend;
    index index.html;
    client_max_body_size @MAX_BODY@;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

EOF
  if [ "$AUTH_LOCATION" != none ]; then
    cat <<EOF
    # slow down password guessing on the sign-in endpoints
    location $AUTH_LOCATION {
        limit_req zone=@NAME@_auth burst=10 nodelay;
        include /etc/nginx/snippets/@NAME@-proxy.conf;
    }

EOF
  fi
  if [ "$HEALTH_PATH" != none ]; then
    cat <<EOF
    # uptime checks reach Django, not the SPA fallback
    location = $HEALTH_PATH {
        include /etc/nginx/snippets/@NAME@-proxy.conf;
    }

EOF
  fi
  cat <<EOF
    location /api/ {
        include /etc/nginx/snippets/@NAME@-proxy.conf;
    }

    # the Django admin, at ADMIN_URL from .env (staff sign in to it with a passkey)
    location /$(admin_url) {
        include /etc/nginx/snippets/@NAME@-proxy.conf;
    }

EOF
  cat <<'EOF'

    location /static/ {
        alias @APP_DIR@/staticfiles/;
        expires 7d;
    }

    # SPA: hashed assets cache forever, everything else falls back to index.html
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    location / {
        try_files $uri /index.html;
    }
EOF
}

nginx_site() { # nginx_site plain|tls
  if [ "$AUTH_LOCATION" != none ]; then
    echo 'limit_req_zone $binary_remote_addr zone=@NAME@_auth:10m rate=5r/m;'
    echo
  fi
  if [ "$1" = tls ]; then
    cat <<'EOF'
server {
    listen 80;
    server_name @DOMAIN@;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name @DOMAIN@;
    ssl_certificate     /etc/letsencrypt/live/@DOMAIN@/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/@DOMAIN@/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:ssl_@NAME@:10m;
    ssl_session_timeout 1d;

EOF
  else
    cat <<'EOF'
server {
    listen 80;
    server_name @DOMAIN@;

EOF
  fi
  nginx_body
  echo '}'
}

nginx_apply() { # nginx_apply plain|tls
  install_file "$SITE" 644 root:root < <(nginx_site "$1")
  sudo ln -sfn "$SITE" "/etc/nginx/sites-enabled/$NAME"
  sudo rm -f /etc/nginx/sites-enabled/default
  sudo nginx -t
  sudo systemctl reload nginx
}

have_cert() { sudo test -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem"; }

step_nginx() {
  local my_ip dns_ip
  install_file "/etc/nginx/snippets/$NAME-proxy.conf" 644 root:root <<'EOF'
proxy_pass http://127.0.0.1:@PORT@;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_read_timeout 120s;
EOF

  # certbot renews with the nginx authenticator only, so reload nginx after each renewal
  sudo mkdir -p /etc/letsencrypt/renewal-hooks/deploy
  install_file /etc/letsencrypt/renewal-hooks/deploy/reload-nginx 755 root:root <<'EOF'
#!/bin/sh
systemctl reload nginx
EOF

  if have_cert; then
    nginx_apply tls
    say "https is configured (certificate present)"
    return 0
  fi

  nginx_apply plain
  dns_ip=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1 {print $1}' || true)
  my_ip=$(curl -4fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)
  if [ $FORCE_CERT = 0 ]; then
    if [ -z "$dns_ip" ]; then skip "no A record for $DOMAIN yet; add it, then re-run for the certificate"; return 0; fi
    if [ -n "$my_ip" ] && [ "$dns_ip" != "$my_ip" ]; then
      skip "$DOMAIN points at $dns_ip but this server is $my_ip; fix DNS (or --force-cert) and re-run"; return 0
    fi
  fi
  sudo certbot certonly --nginx -d "$DOMAIN" -m "$EMAIL" --agree-tos --no-eff-email --non-interactive
  nginx_apply tls
  say "certificate issued; http now redirects to https"
}

cron_local_lines() { # cron_local_lines FILE: "schedule command" lines -> "schedule NAME command"
  awk -v u="$NAME" '
    /^[[:space:]]*(#|$)/ { next }
    {
      n = ($1 ~ /^@/) ? 1 : 5
      if (NF <= n) { printf "cron.local line %d has no command: %s\n", NR, $0 > "/dev/stderr"; bad = 1; next }
      rest = $0; sched = ""
      sub(/^[[:space:]]+/, "", rest)
      for (i = 1; i <= n; i++) { sched = sched $i " "; sub(/^[^[:space:]]+[[:space:]]+/, "", rest) }
      print sched u "  " rest
    }
    END { exit bad }' "$1"
}

cron_file() { # cron_file PROJECT_LINES LOCAL_LINES
  cat <<'EOF'
# Managed by hosting/provision.sh: edits here are overwritten on the next run.
# App jobs go in /srv/@NAME@/cron.local as "schedule command"; they run as @NAME@.
# Cron ignores this file unless it is owned by root and not writable by anyone else.

# Nightly DB backup, 03:15 server time
15 3 * * *  @NAME@  /srv/@NAME@/bin/backup-db 2>&1 | logger -t @NAME@-backup
EOF
  if [ -n "$1" ]; then
    printf '\n# from JOBS in hosting/provision.sh\n%s\n' "$1"
  fi
  if [ -n "$2" ]; then
    printf '\n# from /srv/@NAME@/cron.local\n%s\n' "$2"
  fi
}

step_cron() {
  local jobs="" extra="" file="$ROOT/cron.local"
  if [ ${#JOBS[@]} -gt 0 ]; then
    # bin/ is /srv/NAME/bin/; output goes to the journal like the backup's
    jobs=$(printf '%s 2>&1 | logger -t @NAME@-cron\n' "${JOBS[@]}" | sed "s| bin/| $ROOT/bin/|" |
           cron_local_lines /dev/stdin) || die "fix JOBS at the top of hosting/provision.sh"
  fi
  if [ -f "$file" ]; then
    # these lines end up running from a root-owned cron file, so only the deploy user may write them
    if [ "$(stat -c %U "$file")" != "$DEPLOY_USER" ] || [ -n "$(find "$file" -perm /022)" ]; then
      die "$file must be owned by $DEPLOY_USER and not writable by group/others (chmod 644)"
    fi
    extra=$(cron_local_lines "$file") || die "fix $file and re-run"
    say "including $(printf '%s\n' "$extra" | grep -c .) job(s) from $file"
  fi
  install_file "/etc/cron.d/$NAME" 644 root:root < <(cron_file "$jobs" "$extra")
}

step_journald() {
  sudo mkdir -p /etc/systemd/journald.conf.d
  install_file /etc/systemd/journald.conf.d/10-size-limit.conf 644 root:root <<'EOF'
[Journal]
SystemMaxUse=200M
EOF
  if [ $CHANGED = 1 ]; then sudo systemctl restart systemd-journald; fi
}

step_firewall() {
  if ! command -v ufw >/dev/null 2>&1; then skip "ufw is not installed (sudo apt-get install ufw, then re-run)"; return 0; fi
  sudo ufw allow 'Nginx Full' >/dev/null
  if sudo ufw status | head -1 | grep -q inactive; then
    # Enabling it here could lock you out if sshd listens on a port ufw doesn't allow yet.
    warn "ufw is inactive; not enabling it here"
    NOTES+=("Firewall: 'sudo ufw allow OpenSSH' (or your ssh port), then 'sudo ufw enable'")
  else
    say "ufw allows 'Nginx Full'"
  fi
}

step_app() {
  local f users
  if [ ! -f "$APP_DIR/manage.py" ]; then
    skip "no code at $APP_DIR yet: run ./hosting/deploy.sh from your Mac, then re-run"
    return 0
  fi
  if [ -f "$APP_DIR/uv.lock" ]; then
    UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" UV_PROJECT_ENVIRONMENT="$ROOT/venv" \
      /usr/local/bin/uv sync --frozen --no-dev -q --python "$PYTHON_VERSION" --project "$APP_DIR"
  elif [ -f "$APP_DIR/requirements.txt" ]; then
    UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" /usr/local/bin/uv pip install --python "$ROOT/venv/bin/python" \
      --no-cache -q -r "$APP_DIR/requirements.txt"
  else
    die "neither uv.lock nor requirements.txt found in $APP_DIR"
  fi
  say "dependencies synced"
  if [ ! -x "$ROOT/venv/bin/gunicorn" ]; then
    skip "gunicorn is not installed: add it to pyproject.toml, deploy, re-run"
    return 0
  fi
  if [ "$DB" != sqlite ] && ! "$ROOT/venv/bin/python" -c 'import psycopg' 2>/dev/null \
                         && ! "$ROOT/venv/bin/python" -c 'import psycopg2' 2>/dev/null; then
    skip "no PostgreSQL driver: add psycopg[binary] to pyproject.toml, deploy, re-run"
    return 0
  fi
  if [ "$DB" = external ] && ! env_has DATABASE_URL; then
    skip "DATABASE_URL is not set in $ENV_FILE"
    return 0
  fi
  sudo -u "$NAME" "$ROOT/bin/manage" migrate --noinput | tail -n 1
  if [ "$DB" = sqlite ]; then
    for f in "$ROOT"/data/db.sqlite3*; do
      if [ -e "$f" ]; then sudo chown "$NAME:$NAME" "$f"; sudo chmod 600 "$f"; fi
    done
  fi
  "$ROOT/bin/manage" collectstatic --noinput | tail -n 1
  tidy_modes
  users=$(sudo -u "$NAME" "$ROOT/bin/manage" shell -c 'from django.contrib.auth import get_user_model as g; print(g().objects.count())' 2>/dev/null | tail -n 1 || true)
  if [ "$users" = 0 ]; then
    NOTES+=("No accounts yet: sudo -u $NAME $ROOT/bin/manage add_user EMAIL --name Name --admin")
  fi
}

step_start() {
  local i code path url
  if [ ! -x "$ROOT/venv/bin/gunicorn" ] || [ ! -f "$APP_DIR/manage.py" ]; then
    skip "service not started: code or gunicorn is not installed yet"
    return 0
  fi
  if systemctl is-active --quiet "$NAME"; then
    if [ $RESTART_NEEDED = 1 ]; then sudo systemctl restart "$NAME"; say "restarted (config changed)"; else say "already running"; fi
  else
    sudo systemctl start "$NAME"; say "started"
  fi
  path=$HEALTH_PATH; [ "$path" = none ] && path=/
  url="http://127.0.0.1:$PORT$path"
  for i in $(seq 1 20); do
    # Django rejects Host: 127.0.0.1 (ALLOWED_HOSTS is the domain), so send the real one like nginx does
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H "Host: $DOMAIN" "$url" 2>/dev/null || true)
    case $code in
      2??|3??) say "health check ok ($url -> $code)"; return 0 ;;
      4??)
        if [ "$HEALTH_PATH" = none ]; then say "service answers ($url -> $code)"
        else
          say "service answers, but $url -> $code"
          NOTES+=("$url answers $code: add that view, or set HEALTH_PATH=none at the top of hosting/provision.sh")
        fi
        return 0 ;;
    esac
    sleep 1
  done
  sudo journalctl -u "$NAME" -n 20 --no-pager >&2 || true
  die "service did not answer $url (Host: $DOMAIN) within 20s"
}

check_ok()   { printf '  ok    %s\n' "$*"; }
check_fail() { printf '  FAIL  %s\n' "$*"; CHECK_FAILS=$((CHECK_FAILS + 1)); }
check_path() { # check_path PATH MODE OWNER:GROUP [optional]
  local p=$1 mode=$2 own=$3 got
  if ! got=$(sudo stat -c '%a %U:%G' "$p" 2>/dev/null); then
    [ "${4:-}" = optional ] && return 0
    check_fail "$p is missing"; return 0
  fi
  if [ "$got" = "$mode $own" ]; then printf '  ok    %-45s %s %s\n' "$p" "$mode" "$own"
  else check_fail "$p is $got, expected $mode $own"; fi
}

check_database() {
  case $DB in
    sqlite)
      for f in "$ROOT"/data/db.sqlite3*; do check_path "$f" 600 "$NAME:$NAME" optional; done ;;
    postgres)
      if (cd / && sudo -u "$NAME" psql -d "$NAME" -tAc 'SELECT 1') 2>/dev/null | grep -qx 1; then
        check_ok "PostgreSQL database '$NAME' reachable as '$NAME'"
      else check_fail "cannot connect to PostgreSQL database '$NAME' as '$NAME'"; fi ;;
    external)
      if ! env_has DATABASE_URL; then NOTES+=("DATABASE_URL is not set in $ENV_FILE")
      elif (set -a; . "$ENV_FILE"; set +a; psql "$DATABASE_URL" -tAc 'SELECT 1') 2>/dev/null | grep -qx 1; then
        check_ok "external database reachable"
      else check_fail "cannot connect to DATABASE_URL from .env"; fi ;;
  esac
}

step_verify() {
  local f bad
  CHECK_FAILS=0
  echo "  permissions"
  check_path "$ROOT" 755 "$DEPLOY_USER:$DEPLOY_USER"
  for f in app frontend bin venv; do check_path "$ROOT/$f" 755 "$DEPLOY_USER:$DEPLOY_USER"; done
  check_path "$ROOT/data" 755 "$NAME:$NAME"
  check_path "$ROOT/backups" 700 "$NAME:$NAME"
  check_path "$ROOT/.env" 640 "$DEPLOY_USER:$NAME"
  check_path "$ROOT/bin/manage" 755 "$DEPLOY_USER:$DEPLOY_USER"
  check_path "$ROOT/bin/backup-db" 755 "$DEPLOY_USER:$DEPLOY_USER"
  if [ "$REPO" != none ]; then
    check_path "$ROOT/bin/deploy" 755 "$DEPLOY_USER:$DEPLOY_USER"
    check_path "$ROOT/staging" 750 "$DEPLOY_USER:$DEPLOY_USER"
  fi
  check_path "/etc/systemd/system/$NAME.service" 644 root:root
  check_path "$SITE" 644 root:root
  check_path "/etc/nginx/snippets/$NAME-proxy.conf" 644 root:root
  check_path "/etc/cron.d/$NAME" 644 root:root
  check_path /swapfile 600 root:root optional
  if [ "$(sudo readlink "/etc/nginx/sites-enabled/$NAME" 2>/dev/null || true)" = "$SITE" ]; then
    printf '  ok    %-45s -> %s\n' "/etc/nginx/sites-enabled/$NAME" "$SITE"
  else check_fail "/etc/nginx/sites-enabled/$NAME is not a link to $SITE"; fi

  # uv creates venv/.lock as 0666 on purpose; it is a lock file, not code or data.
  bad=$(sudo find "$ROOT" -xdev ! -type l -perm -0002 ! -path '*/venv/.lock' 2>/dev/null | head -n 5 || true)
  [ -z "$bad" ] || check_fail "world-writable under $ROOT: $(echo "$bad" | tr '\n' ' ')"
  bad=$(sudo find "$ROOT" -xdev -user root 2>/dev/null | head -n 5 || true)
  [ -z "$bad" ] || check_fail "root-owned under $ROOT (a sudo editor?): $(echo "$bad" | tr '\n' ' ')"
  bad=$(sudo find "$ROOT/backups" -mindepth 1 \( -type d ! -perm 700 -o -type f ! -perm 600 \) 2>/dev/null | head -n 5 || true)
  [ -z "$bad" ] || check_fail "backups not private: $(echo "$bad" | tr '\n' ' ')"

  echo "  runtimes"
  if [ -x /usr/local/bin/uv ]; then check_ok "uv installed (/usr/local/bin/uv)"; else check_fail "/usr/local/bin/uv missing"; fi
  if UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" /usr/local/bin/uv python find "$PYTHON_VERSION" >/dev/null 2>&1; then
    check_ok "Python $PYTHON_VERSION installed in $UV_PYTHON_DIR"
  else check_fail "Python $PYTHON_VERSION missing from $UV_PYTHON_DIR"; fi
  if [ "$REPO" != none ] && [ "$NODE_MAJOR" != none ]; then
    if [ -x "/usr/local/lib/node-$NODE_MAJOR/bin/node" ]; then
      check_ok "Node $("/usr/local/lib/node-$NODE_MAJOR/bin/node" -v) installed in /usr/local/lib/node-$NODE_MAJOR"
    else check_fail "Node $NODE_MAJOR missing from /usr/local/lib/node-$NODE_MAJOR"; fi
  fi

  echo "  database ($DB)"
  check_database

  echo "  services"
  if sudo nginx -t >/dev/null 2>&1; then check_ok "nginx config valid"; else check_fail "nginx -t fails"; fi
  if systemctl is-active --quiet nginx; then check_ok "nginx running"; else check_fail "nginx is not running"; fi
  if systemctl is-active --quiet "$NAME"; then check_ok "$NAME running on 127.0.0.1:$PORT"
  elif [ -f "$APP_DIR/manage.py" ]; then check_fail "$NAME service is not running"
  else printf '  -     %s not running (no code deployed yet)\n' "$NAME"; fi
  if have_cert; then check_ok "certificate present for $DOMAIN"
  else NOTES+=("No certificate for $DOMAIN yet (DNS, then re-run)"); fi

  [ "$CHECK_FAILS" -eq 0 ] || die "$CHECK_FAILS check(s) failed, see FAIL lines above"
}

# ---------------------------------------------------------------- main
STEPS=(
  "step_packages|Install packages"
  "step_runtimes|Install runtimes (uv, Python, Node)"
  "step_service_user|Create service account"
  "step_dirs|Create folders, ownership and venv"
  "step_swap|Swap"
  "step_database|Database"
  "step_env|Secrets file (.env)"
  "step_bin|Helper scripts (manage, backup-db)"
  "step_git_deploy|Deploy from git (deploy key, staging, bin/deploy)"
  "step_systemd|systemd service"
  "step_nginx|nginx and HTTPS certificate"
  "step_cron|Cron jobs"
  "step_journald|Journal size limit"
  "step_firewall|Firewall"
  "step_app|App: dependencies, migrate, static files"
  "step_start|Start service and health check"
  "step_verify|Verify permissions and services"
)

server_main() {
  local s n=0 k
  while [ $# -gt 0 ]; do
    case "$1" in
      --name|--domain|--email|--db|--repo|--branch|--port|--workers|--threads|--max-body|--build-memory-max|--build-swap-max|--python-version|--node-major)
        k=$(printf '%s' "${1#--}" | tr 'a-z-' 'A-Z_')
        printf -v "ARG_$k" '%s' "${2:?$1 needs a value}"
        shift 2 ;;
      -y|--yes) shift ;;  # nothing is asked on the server
      --force-cert) FORCE_CERT=1; shift ;;
      --check)  CHECK_ONLY=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) usage >&2; die "unknown option: $1" ;;
    esac
  done

  [ "$(id -u)" -ne 0 ] || die "run as your normal sudo user, not root (that user owns the deployed code)"
  command -v apt-get >/dev/null 2>&1 || die "this script targets Debian/Ubuntu servers"
  sudo -n true 2>/dev/null || sudo -v || die "sudo access is required"

  load_settings

  DEPLOY_USER=$(id -un)
  ROOT="/srv/$NAME"
  APP_DIR="$ROOT/app"
  [ "$BACKEND_DIR" = . ] || APP_DIR="$APP_DIR/$BACKEND_DIR"
  SITE="/etc/nginx/sites-available/$NAME"
  ENV_FILE="$ROOT/.env"

  trap 'FAIL_LINE=$LINENO' ERR
  trap on_exit EXIT

  if [ $CHECK_ONLY = 1 ]; then
    STEP_TOTAL=1
    run_step 1 "Verify permissions and services" step_verify
    return 0
  fi

  STEP_TOTAL=${#STEPS[@]}
  for s in "${STEPS[@]}"; do
    n=$((n + 1))
    run_step "$n" "${s#*|}" "${s%%|*}"
  done
  echo
  if have_cert; then echo "Done. https://$DOMAIN/"; else echo "Done. http://$DOMAIN/ (no certificate yet)"; fi
  echo "Django admin: /$(admin_url) (staff sign in with a passkey)"
}

main() { # on the Mac: read hosting/.env and run on the server; on the server: provision
  if [ "$(uname -s)" = Linux ]; then server_main "$@"; else mac_main "$@"; fi
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
