# Hosting on a VPS

`hosting/provision.sh` and `hosting/deploy.sh` set up and deploy this Django + Vue app on a Debian/Ubuntu server. nginx serves the built Vue app and proxies `/api/`, the Django admin (at a random path) and `/health/` to gunicorn, systemd keeps gunicorn running, and cron runs a rotating nightly database backup. The database is PostgreSQL, on the same server (default) or an external managed one.

Everything app-specific lives in this repo. The server only needs to be a Debian/Ubuntu box you can `ssh` into as a normal user with `sudo` (key login). Hardening the box itself (sshd settings, firewall policy, automatic updates, your dotfiles) is general server setup and isn't covered here.

```
Browser ──https──▶ nginx (80/443)
                    ├─ /                  /srv/NAME/frontend        (built Vue app)
                    ├─ /static/           BACKEND/staticfiles       (Django admin css/js)
                    └─ /api/ /ADMIN_URL/ /health/ ──▶ gunicorn 127.0.0.1:PORT ──▶ Django ──▶ PostgreSQL
systemd  : keeps gunicorn running, restarts it on crash/reboot
cron     : nightly DB backup and JWT blacklist cleanup, plus any jobs in /srv/NAME/cron.local
journald : app logs.   nginx : access/error logs (rotated by logrotate)
```

## What's in `hosting/`

| Path | Runs where | What it does |
|---|---|---|
| [`hosting/provision.sh`](../hosting/provision.sh) | Mac (runs itself on the server) | idempotent 17-step provisioner: packages, `uv` + Python, Node + pnpm, user, DB, `.env`, systemd, nginx, certbot, cron, `--check`. The project's own settings are at its top |
| [`hosting/deploy.sh`](../hosting/deploy.sh) | Mac | warns on uncommitted/unpushed work, then runs `/srv/NAME/bin/deploy` on the server |
| [`hosting/deploy-rsync.sh`](../hosting/deploy-rsync.sh) | Mac | for `DEPLOY_REPO=none`: tests and builds on the Mac, then rsyncs to the server |
| [`hosting/.env.example`](../hosting/.env.example) | — | documents the deploy settings; your real ones go in `hosting/.env` (gitignored) |

Several apps can share one server without Docker: each gets its own system user (`NAME`), localhost port, `/srv/NAME` tree, PostgreSQL role and database (isolated by Unix socket peer auth), systemd sandbox, Python in `/opt/uv/python`, and Node major in `/usr/local/lib/node-MAJOR` (with `pnpm` pinned by `corepack` from `frontend/package.json`).

## Settings

There are two kinds, and each lives in one place:

| Kind | Where | Examples |
|---|---|---|
| **The project** (true wherever it is deployed) | top of `hosting/provision.sh`, `backend/.python-version`, `"engines"` in `frontend/package.json` | backend/frontend folders, WSGI app, health path, rate-limited sign-in endpoints, test and build commands, files never copied, cron jobs; Python version; Node major |
| **The deploy target** (this server, this domain) | `hosting/.env` on your Mac, gitignored | `DEPLOY_HOST`, `DEPLOY_NAME`, `DEPLOY_DOMAIN`, `DEPLOY_REPO`, … |

The first time you run `./hosting/provision.sh` it asks for any missing target setting and appends the answer to `hosting/.env`; after that it just reads the file. Every run copies the settings into a `DEPLOY_*` block in `/srv/NAME/.env` on the server, which is where `bin/deploy` and later runs on the server read them. Change a setting in `hosting/.env` and re-run provision; don't edit the server's copy.

A flag (e.g. `--workers 4`) overrides its setting for that run only. For a second target (staging, a test VM), keep another file and pass it with `--env`: `./hosting/provision.sh --env hosting/.env.staging`, and the same for `deploy.sh`.

| Setting | Flag | Default | Meaning |
|---|---|---|---|
| `DEPLOY_HOST` | `--host` | asked | `~/.ssh/config` alias of the server |
| `DEPLOY_NAME` | `--name` | asked (folder name) | service user, `/srv/NAME`, systemd unit, nginx site, Postgres role and database |
| `DEPLOY_DOMAIN` | `--domain` | asked | public hostname (its `A` record must point at the server before certbot runs) |
| `DEPLOY_EMAIL` | `--email` | asked | Let's Encrypt expiry notices |
| `DEPLOY_DB` | `--db` | `postgres` | `postgres` or `external` |
| `DEPLOY_REPO` | `--repo` | `origin` | git SSH URL the server deploys from, or `none` to deploy from the Mac |
| `DEPLOY_BRANCH` | `--branch` | `main` | branch `deploy.sh` deploys when given no ref |
| `DEPLOY_PORT` | `--port` | first free from 8000 | local gunicorn port, unique per app on the server |
| `DEPLOY_WORKERS`, `DEPLOY_THREADS` | `--workers`, `--threads` | `2`, `2` | gunicorn processes and threads per worker |
| `DEPLOY_MAX_BODY` | `--max-body` | `1m` | nginx `client_max_body_size` (raise for uploads) |
| `DEPLOY_BUILD_MEMORY_MAX` | `--build-memory-max` | `250M` | RAM for tests and the build on the server before they swap |
| `DEPLOY_BUILD_SWAP_MAX` | `--build-swap-max` | `1G` | swap they may use before they are killed |

Other flags: `-y` / `--yes` uses defaults instead of asking, `--force-cert` runs certbot even when DNS looks different (e.g. behind a Cloudflare proxy), `--check` verifies owners, modes, runtimes, DB and services without changing anything.

The server doesn't use the keychain from local development: production settings come from `/srv/NAME/.env`, and `keychain.key` / `keychain.json` are never copied.

## First-time setup (per app)

1. **Point a DNS `A` record** for the app's domain at the server IP.
2. **Run the provisioner** from your Mac and answer its questions:
   ```bash
   ./hosting/provision.sh
   ```
   It saves your answers in `hosting/.env`, copies itself to `DEPLOY_HOST` and runs there.
3. **Add the printed deploy key to GitHub:**
   Repo → Settings → Deploy keys → Add key (leave "Allow write access" **off**).
4. **Add any app-specific secrets** to `/srv/NAME/.env` on the server (`SECRET_KEY`, `SETTINGS_ENCRYPTION_KEY`, `ADMIN_URL`, `DATABASE_URL`, `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are generated automatically). To let visitors read public pages without an account, add `REQUIRE_LOGIN=False` (see the README).
5. **Deploy the code:**
   ```bash
   ./hosting/deploy.sh
   ```
   This clones the pushed commit into `/srv/NAME/staging/src`, syncs the staging venv with `uv`, runs the tests, builds the Vue frontend with `pnpm`, backs up the DB, copies the build into `/srv/NAME/{app,frontend}`, syncs the production venv (`--no-dev`), runs migrations and `collectstatic`, restarts gunicorn, and checks `/health/`.
6. **Create the first admin account:**
   ```bash
   ssh -t HOST 'sudo -u NAME /srv/NAME/bin/manage add_user you@example.com --name "Your Name" --admin'
   ```
   Sign in at `https://DOMAIN` with that password; the app then makes you add a passkey, and from then on the account signs in with the passkey only. The Django admin is at `https://DOMAIN/ADMIN_URL` (provision prints it; it's also in `/srv/NAME/.env`). Lost every passkey? `sudo -u NAME /srv/NAME/bin/manage reset_passkeys you@example.com` removes them and signs the account out everywhere.
7. **Turn on the firewall** if the server doesn't have one yet. Provision allows nginx in `ufw` but never enables it, since that could lock you out if your SSH port isn't allowed:
   ```bash
   ssh -t HOST 'sudo ufw allow OpenSSH && sudo ufw enable'
   ```
8. **Verify permissions and services (any time):**
   ```bash
   ./hosting/provision.sh --check
   ```

After that, day-to-day deploys are just `git push && ./hosting/deploy.sh`.

## What the boilerplate already configures for production

1. **`backend/pyproject.toml` and `backend/uv.lock`** include `gunicorn` and `psycopg[binary]`.
2. **`backend/config/settings/production.py`** reads `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL` and `ALLOW_REGISTRATION` (default `False` in production) from `.env` / environment, trusts nginx's `X-Forwarded-Proto`, marks cookies secure, and logs tracebacks to stdout for `journald`.
3. **`STATIC_ROOT = BASE_DIR / "staticfiles"`**, served by nginx at `/static/`.
4. **Health check at `/health/`** (`backend/config/urls.py`) that verifies the database connection and returns 200 (or 503 if the DB is unreachable). nginx proxies it to Django, so an external uptime monitor sees the real status; `provision.sh` and `bin/deploy` check it after every start.
5. **Sign-in endpoints** (`login`, `register`, `refresh` and passkey sign-in under `/api/v1/auth/`), which nginx rate-limits to 5 requests/min per IP (burst 10): `AUTH_LOCATION` at the top of `provision.sh`.
6. **The Django admin at `ADMIN_URL`**, which `provision.sh` sets to a random `admin-xxxxxxxxxx/` the first time and nginx proxies. Its password form is replaced by the app's passkey sign-in. Change it in `/srv/NAME/.env` and re-run provision (nginx needs the new path).

## Choosing a database

| `DEPLOY_DB` | Use when | How the app connects | Backups |
|---|---|---|---|
| `postgres` (default) | most apps | local socket, role and database both named `NAME`, peer auth (no password) | `pg_dump -Fc` |
| `external` | managed PostgreSQL (DigitalOcean, etc.) | `DATABASE_URL` you put in `/srv/NAME/.env` | `pg_dump -Fc` over the network |

- **postgres:** lives in `/var/lib/postgresql`. Because the PostgreSQL role matches the service user `NAME`, only `NAME` can log in over the local Unix socket: no password exists to leak, and other apps on the same server cannot access it.
- **external:** the first run adds a commented `DATABASE_URL=` placeholder to `/srv/NAME/.env` and skips migrations until you fill it in.
- **Deploy tests** (git deploys) run against the server's own PostgreSQL either way, as you: provision gives your role `CREATEDB`, and the tests create `test_NAME` and drop it afterwards. You have sudo, so that adds nothing you couldn't already do; the app's role still can't create databases.

Development and tests use PostgreSQL too (see the README), so there is no SQLite option.

## What `hosting/provision.sh` does

| # | Step | Does |
|---|---|---|
| 1 | Packages | `nginx`, `python3`, `certbot` + `python3-certbot-nginx`, `rsync`, `curl`, `git`, `xz-utils`, plus `postgresql` (or only `postgresql-client` for an external database with rsync deploys) |
| 2 | Runtimes | `uv` (`/usr/local/bin/uv`), the project's Python in `/opt/uv/python`, and (when deploying from git) the project's Node major in `/usr/local/lib/node-MAJOR` with `corepack` enabled |
| 3 | Service account | system user `NAME`, no login, no home |
| 4 | Folders and venv | `/srv/NAME/...` with strict owners/modes; creates `/srv/NAME/venv` |
| 5 | Swap | `/swapfile` of `SWAP_MB` (1024 MB), unless ≥512 MB swap exists |
| 6 | Database | `postgres`: role and database `NAME`. Git deploys: a role for you with `CREATEDB`, for the tests |
| 7 | Secrets file | creates `/srv/NAME/.env` (`you:NAME`, `640`), generates `SECRET_KEY`, `SETTINGS_ENCRYPTION_KEY` and `ADMIN_URL` once, sets `DJANGO_ENV`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL` (and `PGHOST` for local Postgres), and writes the `DEPLOY_*` settings |
| 8 | Helper scripts | `bin/manage` (`manage.py` with `.env` loaded) and `bin/backup-db` |
| 9 | Deploy from git | read-only deploy key `~/.ssh/deploy_NAME` + ssh alias, `staging/`, `bin/deploy` |
| 10 | systemd | `NAME.service`, sandboxed (`ProtectSystem=strict`, `ProtectHome=true`, writable `data/` only) |
| 11 | nginx and HTTPS | site, proxy snippet, Let's Encrypt certificate once DNS points here, renewal reload hook |
| 12 | Cron | `/etc/cron.d/NAME`: nightly backup, the project's `JOBS` (top of `provision.sh`; `flushexpiredtokens`), plus any jobs in `/srv/NAME/cron.local` |
| 13 | Journal | caps the systemd journal at 200 MB |
| 14 | Firewall | allows `Nginx Full` in `ufw` (never enables `ufw` itself) |
| 15 | App | once code is deployed: `uv sync --frozen --no-dev`, `migrate`, `collectstatic`, account check |
| 16 | Start | starts or restarts `NAME`, checks `/health/` |
| 17 | Verify | file modes and owners, runtimes, database and services (the same as `--check`) |

## Server layout

```
/srv/NAME/
├── app/                  deployed backend code                                (you)
│   └── backend/          manage.py, pyproject.toml, uv.lock, staticfiles/
├── frontend/             built Vue app (contents of frontend/dist/)           (you)
├── venv/                 production Python virtualenv (links /opt/uv/python)  (you)
├── data/                 the only folder the running app may write            (NAME)
├── backups/              daily/ weekly/ monthly/, mode 700                    (NAME)
├── bin/                  manage, backup-db, deploy                            (you)
├── staging/              git clone, staging venv and node_modules             (you)
├── REVISION              commit, ref, timestamp and user of last deploy       (you)
├── cron.local            optional: app-specific cron jobs                     (you)
└── .env                  secrets and DEPLOY_* settings, mode 640              (you:NAME)
```

## Deploying

### From git on the server (default)

The server deploys a pushed commit, never uncommitted files from a laptop:

```bash
./hosting/deploy.sh              # deploy the tip of DEPLOY_BRANCH
./hosting/deploy.sh 1a2b3c4      # deploy a specific commit, branch or tag (also used to roll back)
ssh HOST cat /srv/NAME/REVISION  # see what commit is live
```

What `/srv/NAME/bin/deploy` does on the server (nothing under `app/` or `frontend/` is touched until step 4 passes):

1. Acquires a lock (`/srv/NAME/staging/.lock`) so two deploys cannot overlap.
2. Fetches the commit into `/srv/NAME/staging/src` with the read-only deploy key and cleans untracked files (keeping `node_modules`).
3. Reads the Python version from the commit's `backend/.python-version` (`uv` installs it into `/opt/uv/python` if it's new) and the Node major from its `frontend/package.json`, so a rollback runs with the versions it was built for. A Node major that isn't installed stops the deploy with a message to re-run provision.
4. Syncs `staging/venv` with `uv sync --frozen` (including dev deps) and runs the tests, then builds `frontend/`. Both run inside a `systemd-run --scope` cgroup capped at `DEPLOY_BUILD_MEMORY_MAX` RAM and `DEPLOY_BUILD_SWAP_MAX` swap at low CPU/IO priority, so on a small server builds swap their *own* memory instead of evicting the live app.
5. Backs up the database (`/srv/NAME/bin/backup-db`).
6. Rsyncs `backend/` (and any `EXTRA` folders) to `/srv/NAME/app/` and `frontend/dist/` to `/srv/NAME/frontend/`, excluding `.env`, `keychain.key`, `keychain.json`, local databases, `media/`, `staticfiles/` and tests.
7. Syncs the live `/srv/NAME/venv` with `uv sync --frozen --no-dev`, runs `migrate` and `collectstatic`, restarts `NAME.service`, writes `/srv/NAME/REVISION`, and checks `/health/`.

The project settings at the top of `hosting/provision.sh` (folders, test and build commands) are written into `bin/deploy`, so re-run provision after changing them.

### From your Mac with rsync (`DEPLOY_REPO=none`)

Run `./hosting/deploy-rsync.sh` from your Mac instead. It runs `uv run pytest -q` and `pnpm run build` locally, rsyncs the working tree to the server, and runs `backup-db`, `uv sync --frozen --no-dev`, `migrate`, `collectstatic`, and `systemctl restart`.

## Testing on a local VM

You can rehearse provisioning and deploying on a disposable Ubuntu VM on your Mac before touching a real server. [Multipass](https://multipass.run) works well: real Ubuntu cloud images with systemd, its own IP, and an `ubuntu` user with passwordless `sudo`.

1. **Create the VM** (1 GB matches a small VPS; less can stall on first boot) and allow your SSH key:
   ```bash
   multipass launch 24.04 --name hosting-test --cpus 1 --memory 1G --disk 10G
   multipass exec hosting-test -- bash -c "echo '$(cat ~/.ssh/id_rsa.pub)' >> ~/.ssh/authorized_keys"
   multipass info hosting-test | grep IPv4
   ```
   Add it to `~/.ssh/config` (`Host hosting-test`, `HostName` the VM's IP, `User ubuntu`), and give it a name for the browser in `/etc/hosts` (Multipass on macOS has no DNS names for VMs):
   ```bash
   echo "IP gfb.test" | sudo tee -a /etc/hosts
   ```
   Use a `.test` name (reserved for testing; `.local` clashes with mDNS). Passkeys need a name rather than an IP, and HTTPS (step 5).
2. **Give the VM a repo to deploy from**, so no GitHub deploy key is needed. A bare repo on the VM itself:
   ```bash
   ssh hosting-test 'git init -q --bare -b main ~/gfb.git'
   git push hosting-test:gfb.git HEAD:main
   ```
3. **Write `hosting/.env.test`** (gitignored):
   ```
   DEPLOY_HOST=hosting-test
   DEPLOY_NAME=gfb
   DEPLOY_DOMAIN=gfb.test
   DEPLOY_EMAIL=you@example.com
   DEPLOY_DB=postgres
   DEPLOY_REPO=ubuntu@localhost:/home/ubuntu/gfb.git
   DEPLOY_BRANCH=main
   ```
4. **Provision, let the deploy key read the repo, deploy:**
   ```bash
   ./hosting/provision.sh --env hosting/.env.test
   ssh hosting-test 'cat ~/.ssh/deploy_gfb.pub >> ~/.ssh/authorized_keys'
   ./hosting/deploy.sh --env hosting/.env.test
   ```
5. **Turn on HTTPS** with a locally trusted certificate. There's no public DNS, so certbot is skipped and the site starts on plain HTTP, where password sign-in works but passkeys don't (browsers only allow them over https or on `localhost`) and neither does the Django admin (production cookies are secure-only). [`mkcert`](https://github.com/FiloSottile/mkcert) makes a certificate your Mac trusts:
   ```bash
   brew install mkcert && mkcert -install          # once: adds a local CA to your keychain
   mkcert -cert-file gfb.test.pem -key-file gfb.test-key.pem gfb.test
   scp gfb.test.pem gfb.test-key.pem hosting-test:
   ssh hosting-test 'sudo install -d /etc/letsencrypt/live/gfb.test &&
     sudo install -m 644 gfb.test.pem /etc/letsencrypt/live/gfb.test/fullchain.pem &&
     sudo install -m 600 gfb.test-key.pem /etc/letsencrypt/live/gfb.test/privkey.pem && rm gfb.test*.pem'
   ./hosting/provision.sh --env hosting/.env.test   # sees the certificate, switches nginx to https
   ```
   Then open `https://gfb.test`. Firefox uses its own trust store: `brew install nss` before `mkcert -install`.
6. **Throw it away:** `multipass delete --purge hosting-test`, then remove the `~/.ssh/config` block, the `/etc/hosts` line, and the VM's `~/.ssh/known_hosts` entry.

## Scheduled jobs (`cron.local`)

`/etc/cron.d/NAME` is managed by `provision.sh`. Put app-specific cron jobs in `/srv/NAME/cron.local` on the server as `schedule command` lines (without a user column: `provision.sh` inserts `NAME` so jobs always run as the service user, never root):

```cron
# weekdays after the US close
30 22 * * 1-5  nice /srv/@NAME@/bin/manage backfill_intraday 2>&1 | logger -t @NAME@-backfill
@hourly        /srv/@NAME@/bin/manage clearsessions
```

Keep `/srv/NAME/cron.local` owned by your deploy user and mode `644`, then re-run `./hosting/provision.sh`.

Jobs every deployment of the project needs go in `JOBS` at the top of `hosting/provision.sh` instead, in the same format (`bin/` there means `/srv/NAME/bin/`). The boilerplate's one is a nightly `manage flushexpiredtokens`, which deletes expired rows from the JWT blacklist tables.

## Backups

`bin/backup-db` keeps **4 daily, 4 weekly (Sundays), and 6 monthly (1st of the month)** copies in `/srv/NAME/backups` (mode `700`, owned by `NAME`). It runs nightly at `03:15` server time and before every deploy, verifying each copy (`pg_restore -l`) before keeping it.

```bash
sudo -u NAME /srv/NAME/bin/backup-db        # run a backup now
sudo ls -lh /srv/NAME/backups/daily
```

**Restore** (stop the app first: `sudo systemctl stop NAME`, then `start` afterwards):

```bash
# postgres (local)
sudo -u NAME pg_restore --clean --if-exists -d NAME /srv/NAME/backups/daily/db-YYYY-MM-DD.dump

# external: as NAME, with DATABASE_URL loaded from .env
sudo -u NAME bash -c 'set -a; . /srv/NAME/.env; pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL" /srv/NAME/backups/daily/db-YYYY-MM-DD.dump'
```

**Pulling backups off the server to your Mac:**
Because `/srv/NAME/backups` is mode `700` owned by `NAME`, copy or stream via `ssh`:

```bash
mkdir -p ~/backups/NAME
ssh -t HOST "sudo tar -C /srv/NAME/backups -cf - monthly" | tar -C ~/backups/NAME -xvf -
```

## Day-to-day commands on the server

Always use `/srv/NAME/bin/manage` (as `NAME`), never bare `python manage.py`: `bin/manage` loads `/srv/NAME/.env` and runs inside `/srv/NAME/venv`, and running as `NAME` authenticates to PostgreSQL over the local socket.

```bash
systemctl status NAME                                                    # service status
sudo systemctl restart NAME                                              # restart after editing .env
journalctl -u NAME -f                                                    # live app logs & tracebacks
journalctl -t NAME-backup                                                # backup logs
sudo -u NAME /srv/NAME/bin/manage add_user you@example.com --name "You" --admin
sudo -u NAME /srv/NAME/bin/manage reset_passkeys you@example.com         # lost passkeys: remove them, sign out everywhere
grep ^ADMIN_URL /srv/NAME/.env                                           # where the Django admin is
sudo -u NAME /srv/NAME/bin/manage shell                                  # Django shell
sudo -u NAME psql NAME                                                   # Postgres shell
```

## Permissions (`./hosting/provision.sh --check`)

| Path | Mode | Owner:Group |
|---|---|---|
| `/srv/NAME`, `app`, `frontend`, `venv`, `bin` | 755 | you |
| `bin/manage`, `bin/backup-db`, `bin/deploy` | 755 | you |
| `staging` | 750 | you |
| `.env` | 640 | you:NAME |
| `data` | 755 | NAME |
| `backups` and everything in it | 700 / 600 | NAME |
| `/etc/systemd/system/NAME.service`, `/etc/nginx/sites-available/NAME`, `/etc/nginx/snippets/NAME-proxy.conf`, `/etc/cron.d/NAME` | 644 | root |
| `/swapfile` | 600 | root |

`--check` also confirms that `uv`, the project's Python and (when deploying from git) its Node major are installed.
