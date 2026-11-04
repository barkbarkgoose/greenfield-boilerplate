# Hosting on a VPS

A minimal, standard setup for one small server: **nginx → gunicorn → Django → SQLite**, with systemd keeping it running, cron doing the scheduled jobs, and a rotating daily database backup.

This assumes a 512 MB RAM / 10 GB disk Ubuntu 24.04 droplet that has already had the base hardening done (non-root sudo user, key-only SSH, ufw, unattended-upgrades). That part is covered in `SERVER_SETUP.md` in vpshome and is not repeated here.

## The plan in one picture

```
Browser ──https──▶ nginx (80/443)
                    ├─ /            static files   /srv/myapp/frontend   (built Vue app)
                    ├─ /static/     static files   (Django admin css/js)
                    └─ /api/ /admin/ ──▶ gunicorn 127.0.0.1:8000 ──▶ Django ──▶ SQLite
                                                                      /srv/myapp/data/db.sqlite3
systemd  : keeps gunicorn running, restarts it on crash/reboot
cron     : nightly DB backup (plus any jobs you add)
journald : app logs.   nginx : access/error logs (rotated by logrotate)
```

**What is deliberately left out:** Docker, Postgres, Redis, Celery, a CI pipeline. The boilerplate uses SQLite and has no task queue, so none of that is needed to start. Add them only when a real problem demands it.

## Why these choices (given 512 MB)

- **SQLite, not Postgres.** Small app, small database. Postgres would eat ~100 MB of RAM for no benefit. Backups are a single file copy.
- **Build the frontend on your Mac.** `vue-tsc` + `vite build` can run a 512 MB box out of memory. Only the built `dist/` goes to the server, so Node is never installed there.
- **One gunicorn worker with threads.** Keeps memory low. If you add in-process background threads (anything started with `threading.Thread`), one worker also avoids losing them to a recycled worker. `--timeout 120` covers slow requests; lower it if you have none.
- **Add 1 GB of swap.** Heavy libraries (pandas, scikit-learn) can briefly spike past 512 MB. Swap turns an out-of-memory kill into a slow request. If you ever see `free -h` showing swap constantly in use, resize the droplet to 1 GB.

## What the boilerplate already does for production

The boilerplate already includes these. They are listed so you know what to check before deploying.

1. **gunicorn** is already a dependency in `backend/pyproject.toml`.
2. **`backend/config/settings/production.py` is already production-ready** (below). Check it and set the matching env vars:
   ```python
   ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")          # required in production, no default

   # nginx terminates TLS and tells Django via this header
   SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
   SECURE_SSL_REDIRECT = False                        # nginx already redirects 80 -> 443
   SESSION_COOKIE_SECURE = True
   CSRF_COOKIE_SECURE = True
   CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
   SECURE_HSTS_SECONDS = 31536000                     # turn on only after https works

   # Send app logs (including tracebacks) to stdout -> systemd journal
   LOGGING = {
       "version": 1,
       "disable_existing_loggers": False,
       "formatters": {"plain": {"format": "%(levelname)s %(name)s %(message)s"}},
       "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
       "root": {"handlers": ["console"], "level": "INFO"},
   }
   ```
3. **Registration is closed in production by default.** `production.py` sets `ALLOW_REGISTRATION` from the environment with a default of `False`. The API answers 404 and the frontend hides the register link and page (it asks `GET /api/v1/auth/config/`). Create accounts with `sudo -u myapp /srv/myapp/bin/manage add_user EMAIL --name NAME [--admin]`. To open sign-up, put `ALLOW_REGISTRATION=True` in the server `.env` and restart.
4. **Config precedence is env first, keychain second.** `base.py` now resolves every setting from the environment / `.env` first, then the encrypted keychain, then a default. So a value in `/srv/myapp/.env` or the systemd environment always overrides the keychain. This also applies to the JWT lifetimes.
5. **Keychain vs `.env` on the server: pick one workflow.**
   - *Keychain (one key to guard):* run `python -m keychain init` once as `myapp`, `set` the values, and store only `keychain.key` in your password vault. `keychain.key` and `keychain.json` are gitignored and excluded from `deploy.sh`, so copy `keychain.json` over once by hand (and again whenever it changes). Keep both outside the rsync'd tree and set `KEYCHAIN_KEY_PATH` / `KEYCHAIN_JSON_PATH` in `.env` to point at them. `.env` then only needs `DJANGO_ENV`, `ALLOWED_HOSTS`, `DATABASE_URL` and anything you want to override.  Anything your code reads with `os.getenv` directly (rather than through Django settings) must be a real environment variable.
   - *`.env` only:* skip the keychain entirely. Then set `SETTINGS_ENCRYPTION_KEY` once and never change it.
   - With the keychain present, users' saved settings are encrypted with `keychain.key` (see `apps/users/crypto.py`), so that one vault key covers them too. Losing it makes those settings unreadable, so back it up.

Run the tests and `cd frontend && pnpm run build` locally to confirm all of the above before the first deploy.

## Server layout

Everything lives under `/srv/myapp`. The rsync'd code is kept separate from the data, so a deploy can never touch the database or secrets.

```
/srv/myapp/
├── app/                  rsync target (owned by jake)
│   ├── backend/          Django project (manage.py, apps/, config/, keychain/, staticfiles/)
├── frontend/             built Vue app (contents of frontend/dist)
├── venv/                 Python virtualenv (managed by uv)
├── data/                 db.sqlite3  (owned by myapp)
├── backups/              daily/ weekly/ monthly/  (owned by myapp, mode 700)
├── bin/                  manage, backup-db  (small scripts, below)
└── .env                  secrets/config (jake:myapp, mode 640)
```

Two accounts: **jake** deploys and has sudo; **myapp** is a system user with no login and no sudo that runs the app and owns the data.

## One-time server setup

### 1. Packages, user, swap, folders

```bash
sudo apt update
sudo apt install -y nginx python3-venv sqlite3 certbot python3-certbot-nginx

# uv installs the locked Python dependencies (installs to ~/.local/bin for your user)
curl -LsSf https://astral.sh/uv/install.sh | sh

# service account: no login shell, no home
sudo adduser --system --group --no-create-home myapp

# folders
sudo mkdir -p /srv/myapp/{app,frontend,data,backups,bin}
sudo chown -R jake:jake /srv/myapp
sudo chown myapp:myapp /srv/myapp/data /srv/myapp/backups
sudo chmod 700 /srv/myapp/backups

# 1 GB swap
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h        # confirm Swap: 1.0Gi
```

### 2. Domain and DNS

Point an `A` record (e.g. `myapp.example.com`) at the droplet IP before step 7 so Let's Encrypt can issue a certificate. Without a domain you can still run over plain http on the IP for testing, but do not leave real logins on plain http.

### 3. Secrets file

Generate the two keys on your Mac or the server:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"                     # SECRET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # SETTINGS_ENCRYPTION_KEY
```

Create `/srv/myapp/.env`:

```bash
DJANGO_ENV=production
SECRET_KEY=...
SETTINGS_ENCRYPTION_KEY=...    # skip SECRET_KEY / this line if they live in the keychain instead
DATABASE_URL=sqlite:////srv/myapp/data/db.sqlite3
ALLOWED_HOSTS=myapp.example.com
CSRF_TRUSTED_ORIGINS=https://myapp.example.com
# add any other settings your app reads from the environment
```

Note the **four** slashes in `DATABASE_URL`: three for the scheme plus one for the absolute path. Then lock it down:

```bash
chmod 640 /srv/myapp/.env
sudo chown jake:myapp /srv/myapp/.env
```

### 4. Helper scripts

`/srv/myapp/bin/manage`: runs any `manage.py` command with the right environment (used by you, cron and the deploy).

```bash
#!/usr/bin/env bash
set -euo pipefail
set -a; . /srv/myapp/.env; set +a
cd /srv/myapp/app/backend
exec /srv/myapp/venv/bin/python manage.py "$@"
```

`/srv/myapp/bin/backup-db`: see [Backups](#backups).

```bash
chmod +x /srv/myapp/bin/*
```

### 5. First deploy

From your Mac, run the deploy steps in [Deploying updates](#deploying-updates). The first time, after the code is on the box, create the virtualenv and the database:

```bash
UV_PROJECT_ENVIRONMENT=/srv/myapp/venv ~/.local/bin/uv sync --frozen --no-dev \
  --python /usr/bin/python3 --project /srv/myapp/app/backend
sudo -u myapp /srv/myapp/bin/manage migrate
sudo -u myapp /srv/myapp/bin/manage add_user YOU@EXAMPLE.COM --name YourName --admin
/srv/myapp/bin/manage collectstatic --noinput
```

`UV_PROJECT_ENVIRONMENT` puts the virtualenv at `/srv/myapp/venv` instead of inside the rsync'd code. `--frozen` installs exactly what `uv.lock` pins, `--no-dev` skips test tooling, and `--python /usr/bin/python3` uses the system Python so the `myapp` user can read the interpreter (a uv-managed Python would live in your home directory).

To start from existing local data, stop the service and copy your `db.sqlite3` to `/srv/myapp/data/`, owned by `myapp`.

### 6. systemd service

`/etc/systemd/system/myapp.service`:

```ini
[Unit]
Description=myapp (gunicorn)
After=network.target

[Service]
User=myapp
Group=myapp
WorkingDirectory=/srv/myapp/app/backend
EnvironmentFile=/srv/myapp/.env
ExecStart=/srv/myapp/venv/bin/gunicorn config.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 1 --threads 4 --timeout 120 \
    --access-logfile -
Restart=on-failure
RestartSec=3

# basic sandboxing
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/srv/myapp/data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now myapp
systemctl status myapp
curl -i http://127.0.0.1:8000/health/   # expect 200 {"status": "ok"}
```

### 7. nginx and HTTPS

`/etc/nginx/sites-available/myapp`:

```nginx
limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/m;

server {
    listen 80;
    server_name myapp.example.com;

    root /srv/myapp/frontend;
    index index.html;
    client_max_body_size 1m;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    # slow down password guessing on login/register/refresh
    location /api/v1/auth/ {
        limit_req zone=auth burst=10 nodelay;
        include /etc/nginx/snippets/myapp-proxy.conf;
    }

    location /api/ {
        include /etc/nginx/snippets/myapp-proxy.conf;
    }

    location /admin/ {
        # optional: allow 203.0.113.7; deny all;     (your home IP)
        include /etc/nginx/snippets/myapp-proxy.conf;
    }

    location /static/ {
        alias /srv/myapp/app/backend/staticfiles/;
        expires 7d;
    }

    # Vue app: hashed assets cache forever, everything else falls back to index.html
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    location / {
        try_files $uri /index.html;
    }
}
```

`/etc/nginx/snippets/myapp-proxy.conf`:

```nginx
proxy_pass http://127.0.0.1:8000;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_read_timeout 120s;
```

```bash
sudo ln -s /etc/nginx/sites-available/myapp /etc/nginx/sites-enabled/myapp
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# firewall (skip anything already done in SERVER_SETUP.md)
sudo ufw allow 'Nginx Full' && sudo ufw status

# HTTPS: certbot edits the server block, adds the redirect, and sets up auto-renew
sudo certbot --nginx -d myapp.example.com
sudo certbot renew --dry-run
```

After https works, deploy the production setting `SECURE_HSTS_SECONDS` if you haven't (it is in the settings block above) and restart.

Gunicorn only listens on `127.0.0.1`, so port 8000 is never exposed; only 22, 80 and 443 are open.

## Deploying updates

Because you rsync rather than pull from git, the deploy is "build, copy, then restart". Save this as `deploy.sh` in the repo root and run it from the Mac. Change `HOST` to your ssh alias.

```bash
#!/usr/bin/env bash
set -euo pipefail
HOST=myserver   # your ssh config alias
APP=/srv/myapp

# 1. tests + frontend build (locally)
(cd backend && uv run pytest -q)
(cd frontend && npx -y pnpm@11.13.0 run build)

# 2. copy code. Excludes keep secrets, venvs and server-side state out of the transfer
rsync -az --delete \
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='.pytest_cache/' --exclude='.venv/' \
  --exclude='.env' --exclude='db.sqlite3*' --exclude='keychain.key' --exclude='keychain.json' \
  --exclude='staticfiles/' --exclude='tests/' --exclude='conftest.py' \
  backend "$HOST:$APP/app/"
rsync -az --delete frontend/dist/ "$HOST:$APP/frontend/"

# 3. on the server: back up first, install deps, migrate, restart
ssh -t "$HOST" "
  set -e
  sudo -u myapp $APP/bin/backup-db
  UV_PROJECT_ENVIRONMENT=$APP/venv ~/.local/bin/uv sync --frozen --no-dev -q --python /usr/bin/python3 --project $APP/app/backend
  sudo -u myapp $APP/bin/manage migrate --noinput
  $APP/bin/manage collectstatic --noinput
  sudo systemctl restart myapp
"
echo 'Deployed.'
```

Notes:

- `--delete` removes files on the server that you deleted locally; the `--exclude` entries are also protected from that delete, so `.env`, `staticfiles/` and the DB are safe.
- The database backup runs **before** every migration, so a bad migration is always recoverable.
- If dependencies did not change, `uv sync` is a quick no-op.
- Check the site after each deploy: `curl -I https://myapp.example.com/` and `journalctl -u myapp -n 30`.

To **roll back**, check out the previous commit locally and run `deploy.sh` again; restore the DB from a backup only if a migration changed the schema.

## Scheduled jobs (cron)

`/etc/cron.d/myapp`:

```cron
# Nightly DB backup, 03:15 UTC
15 3 * * *   myapp  /srv/myapp/bin/backup-db 2>&1 | logger -t myapp-backup

# Add your own scheduled management commands here, e.g.:
# 30 22 * * 1-5  myapp  nice /srv/myapp/bin/manage some_command 2>&1 | logger -t myapp-some_command
```

Cron runs in the server's timezone (UTC unless you changed it).

## Backups

Goal: keep **4 daily, 4 weekly, 6 monthly** copies of the database, on the server for now.

Use SQLite's online `.backup` command rather than `cp`. It gives a consistent copy even while the app is writing.

`/srv/myapp/bin/backup-db`:

```bash
#!/usr/bin/env bash
set -euo pipefail
umask 077

DB=/srv/myapp/data/db.sqlite3
DEST=/srv/myapp/backups
mkdir -p "$DEST"/daily "$DEST"/weekly "$DEST"/monthly

stamp=$(date +%F)
tmp=$(mktemp "$DEST/.tmp.XXXXXX")
trap 'rm -f "$tmp"' EXIT

sqlite3 "$DB" ".backup '$tmp'"
if [ "$(sqlite3 "$tmp" 'PRAGMA integrity_check;')" != "ok" ]; then
  echo "backup FAILED: integrity check did not pass" >&2
  exit 1
fi

file="db-$stamp.sqlite3.gz"
gzip -c "$tmp" > "$DEST/daily/$file"

# weekly = the Sunday copy, monthly = the 1st-of-month copy
if [ "$(date +%u)" = 7 ]; then cp "$DEST/daily/$file" "$DEST/weekly/$file"; fi
if [ "$(date +%d)" = 01 ]; then cp "$DEST/daily/$file" "$DEST/monthly/$file"; fi

# keep the newest N in each folder
prune() { ls -1t "$1" | tail -n +"$(( $2 + 1 ))" | while read -r f; do rm -f "$1/$f"; done; }
prune "$DEST/daily" 4
prune "$DEST/weekly" 4
prune "$DEST/monthly" 6

echo "backup ok: $file"
```

Try it once by hand and look at the result:

```bash
sudo -u myapp /srv/myapp/bin/backup-db
ls -lh /srv/myapp/backups/daily
```

**Size:** the database compresses to a few MB, so 14 copies is well under 100 MB. Watch it with `df -h /` and `du -sh /srv/myapp/*`. The DB grows as your data does.

**Restore:**

```bash
sudo systemctl stop myapp
gunzip -c /srv/myapp/backups/daily/db-YYYY-MM-DD.sqlite3.gz \
  | sudo -u myapp tee /srv/myapp/data/db.sqlite3 > /dev/null
sudo systemctl start myapp
```

Do a restore test once (into a scratch file, then `sqlite3 file '.tables'`). A backup you have never restored is only a hope.

**Backups on the same disk do not protect against losing the droplet.** If the data cannot be rebuilt, every so often pull a copy to your Mac:

```bash
rsync -av myserver:/srv/myapp/backups/monthly/ ~/backups/myapp/
```

(`backups/` is mode 700 owned by `myapp`, so for this either `sudo`-copy the file to your home first or add `--rsync-path='sudo rsync'`.) Alternatively turn on DigitalOcean's weekly droplet backups in the control panel; it is about 20% of the droplet price and covers the whole machine.

## Logging

| What | Where | How to read it |
|---|---|---|
| App + gunicorn access log + Python tracebacks | systemd journal | `journalctl -u myapp -f` |
| Cron job output (backup, your jobs) | systemd journal / syslog | `journalctl -t myapp-backup` |
| nginx requests and errors | `/var/log/nginx/access.log`, `error.log` | `sudo tail -f ...`. Rotated weekly by logrotate, which is installed by default |
| Firewall / SSH | `/var/log/auth.log` | `sudo grep Failed /var/log/auth.log` |

One tweak so the journal can't fill a 10 GB disk: in `/etc/systemd/journald.conf` set `SystemMaxUse=200M`, then `sudo systemctl restart systemd-journald`.

Optional but worthwhile: a free external uptime check (UptimeRobot, Better Stack) on `https://myapp.example.com/` that emails you when the site is down. It will also tell you if the box ran out of memory and the service was down.

## Security checklist for this app

- [ ] `DJANGO_ENV=production`, `DEBUG` never true, real `SECRET_KEY` in `.env`
- [ ] `ALLOWED_HOSTS` is the real hostname, not `*`
- [ ] HTTPS only; HTTP redirects to HTTPS (certbot does this)
- [ ] Registration closed (or intentionally open)
- [ ] `/srv/myapp/.env` is mode 640 and not in git; `keychain.key` (if used) is mode 600, outside the rsync'd tree and backed up in your vault
- [ ] Port 8000 not reachable from outside (`curl http://SERVER_IP:8000` fails); only 22/80/443 open
- [ ] App runs as `myapp`, not as `jake` or root
- [ ] Backups exist, are mode 700, and a restore has been tested once
- [ ] Automatic security updates on (from `SERVER_SETUP.md`)
- [ ] Optional: restrict `/admin/` to your IP in nginx

## Day-to-day commands

```bash
systemctl status myapp                       # is it running
sudo systemctl restart myapp                 # restart after config changes
journalctl -u myapp -f                       # live app logs
free -h; df -h /                              # memory and disk
sudo -u myapp /srv/myapp/bin/manage shell   # Django shell
sudo -u myapp /srv/myapp/bin/backup-db      # backup now
sudo nginx -t && sudo systemctl reload nginx  # after nginx edits
```

## When to scale up

Do the simple thing first; move when you see these symptoms:

| Symptom | Fix |
|---|---|
| `Killed` / OOM entries in `sudo journalctl -k \| grep -i oom`, or constant swap use | Resize droplet to 1 GB RAM (DigitalOcean: Droplet → Resize, CPU/RAM only, keeps disk and can be reversed) |
| Disk over ~70% | Move old backups off-box (monthly pull above) or resize disk (permanent) |
| Several people using it at once, "database is locked" errors | Move to Postgres (set `DATABASE_URL`, `uv add "psycopg[binary]"` in `backend/`, then redeploy) |
| Background jobs you want to survive restarts | Then add a real queue (Celery + Redis) |
