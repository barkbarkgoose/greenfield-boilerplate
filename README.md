# Boilerplate

Ready-to-use Django + Vue 3 project boilerplate with JWT auth.

## First-Time Setup

The backend supports an encrypted keychain for secrets and other deployment-specific
configuration. It stores encrypted values in `backend/keychain.json` and its Fernet
key in `backend/keychain.key`; neither file is committed.

```bash
cd backend

# Create backend/.venv and install the locked dependencies (uv run also does this on demand).
uv sync

# Create the encrypted store and its owner-only key file.
uv run python -m keychain init --from-example

# Move Django settings into the keychain. Quote values to preserve special characters.
uv run python -m keychain set "SECRET_KEY=replace-with-a-unique-production-secret"
uv run python -m keychain set "CORS_ALLOWED_ORIGINS=https://app.example.com"
uv run python -m keychain set "DATABASE_URL=postgres://user:password@db.example.com:5432/app"

# Verify encryption, decryption, and key-file permissions.
uv run python -m keychain doctor
```

**Precedence: environment / `.env` first, then the keychain, then the default.** A value set
in the OS environment or `backend/.env` always overrides the keychain, so any machine can
override a setting without touching the encrypted store. Keep a value in only one place to
avoid confusion. Back up `backend/keychain.key` securely: without it, `keychain.json`
cannot be recovered. Rotate it with `uv run python -m keychain rotate-key`.

## Starting a New Project

Copy only the tracked files (no `node_modules`, `.venv`, `.env` or other ignored state)
into a fresh repo and commit them as one entry:

```bash
mkdir ../my-project && cd ../my-project && git init
git -C ../greenfield-boilerplate archive HEAD | tar -x
git add -A && git commit -m "added boilerplate"
```

## Preflight

```bash
./scripts/preflight.sh            # tooling, keychain, then project checks
./scripts/preflight.sh --skip-remote
```

Checks that `uv`, `node` and `pnpm` actually run (a stale shim on `PATH` fails), that
`pnpm` matches the `packageManager` pin, that `frontend/node_modules` exists, and that the
keychain is initialized with an owner-only key file. Per-project checks go in
`scripts/preflight_project.py`: list `REQUIRED_SETTINGS` (resolved env first, then
keychain; secrets are never printed), list `BASE_URL_SETTINGS` that must be a bare
`scheme://host` with no path, and define `run(pf, args)` to probe external services.
Keep `scripts/preflight.py` itself generic so it can be synced between projects.

## Quick Start

Run both development servers together from the project root:

```bash
./dev.sh
```

The runner creates the database if it doesn't exist, applies migrations, selects available ports beginning at `8800` and `5177`,
updates the Vite proxy and local CORS origins for those ports, and stops both processes
when you press Ctrl+C. Set `DEV_BACKEND_PORT_DEFAULT` or `DEV_FRONTEND_PORT_DEFAULT` in
the keychain to change the starting ports.

If `SECRET_KEY` is missing (or still the `.env.example` placeholder), the runner prompts
you to generate one and saves it to `backend/.env`. For unattended setups, set
`DEV_GENERATE_SECRET_KEY=1` to generate it without prompting.

### Database

PostgreSQL in development, tests and production, so the app always runs on the same database.
Locally that's a Homebrew server (match the major version to your servers; Ubuntu 24.04 has 16):

```bash
brew install postgresql@16
brew services start postgresql@16
```

With no `DATABASE_URL`, the app uses `postgres:///<repo folder name>` (dashes become
underscores, e.g. `greenfield_boilerplate`) over the local socket as your macOS user, and
`./dev.sh` creates it. Tests make `test_<name>` and drop it after each run. Set
`DATABASE_URL` in `backend/.env` (or the keychain) to use another server or name.

### Backend

Dependencies live in `backend/pyproject.toml` with exact versions pinned in `backend/uv.lock`.
Run every Python command through `uv run` from `backend/`: it creates `backend/.venv` and syncs
it to the lockfile first, so there is no separate install or activate step.

```bash
cd backend

# Install dependencies (optional; uv run does this automatically)
uv sync

# Copy and edit environment
cp .env.example .env

# Run migrations
uv run python manage.py migrate

# Create superuser
uv run python manage.py createsuperuser

# Run dev server
uv run python manage.py runserver 8800
```

### Frontend

This project uses [pnpm](https://pnpm.io). Enable it via Corepack if needed
(`corepack enable`) and install dependencies:

```bash
cd frontend

# Install dependencies
pnpm install

# Copy and edit environment
cp .env.example .env

# Run dev server
pnpm dev
```

## Structure

```
boilerplate/
├── backend/
│   ├── config/           # Django settings
│   │   └── settings/     # base.py, local.py, production.py
│   ├── apps/
│   │   ├── users/       # Custom User model + JWT auth
│   │   └── organizations/
│   └── manage.py
└── frontend/
    ├── src/
    │   ├── components/  # Navbar, etc.
    │   ├── views/       # Login, Register, Dashboard
    │   ├── stores/       # Pinia auth store
    │   ├── services/    # Axios with interceptors
    │   └── router/      # Vue Router with auth guards
    └── package.json
```

## Key Features

- **Tailwind CSS 4.x** via `@tailwindcss/vite` plugin
- **JWT Auth** with simplejwt (register/login/refresh endpoints)
- **Expired-token handling**: the auth store drops expired JWTs and the Axios
  interceptor redirects to `/login`, so the UI never gets stuck on a dead session
- **Custom User Model** with Organization FK
- **Per-user settings** (`/api/v1/auth/settings/`) with key whitelisting,
  input validation, and API keys encrypted at rest via `apps/users/crypto.py`
- **CORS configured** for frontend at localhost:5177
- **APPEND_SLASH=False** for clean API URLs

## Tests

```bash
cd backend
uv run pytest
```


## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/auth/config/` | GET | No | Public flags (`allow_registration`, `require_login`) |
| `/api/v1/auth/register/` | POST | No* | Register user + org (*404 unless `ALLOW_REGISTRATION`) |
| `/api/v1/auth/login/` | POST | No | Get JWT tokens + user (403 `passkey_required` for staff who have a passkey) |
| `/api/v1/auth/refresh/` | POST | No | Refresh access token |
| `/api/v1/auth/logout/` | POST | No | Revoke the refresh token (and end an admin session) |
| `/api/v1/auth/settings/` | GET | Yes | Read current user's settings |
| `/api/v1/auth/settings/` | PATCH | Yes | Update current user's settings |
| `/api/v1/auth/passkeys/` | GET | Yes | List your passkeys |
| `/api/v1/auth/passkeys/<id>/` | DELETE | Yes | Remove a passkey (staff keep at least one) |
| `/api/v1/auth/passkeys/register/begin/`, `finish/` | POST | Yes | Add a passkey |
| `/api/v1/auth/passkeys/login/begin/`, `finish/` | POST | No | Sign in with a passkey: same response as `login/` |

## Registration

Open sign-up is on in development and **off in production**. `ALLOW_REGISTRATION` defaults
to `True` in `base.py` and to `False` in `production.py`; set `ALLOW_REGISTRATION=True` in
the environment / `.env` to override either default. When it is off, `POST
/api/v1/auth/register/` answers 404 (as if it did not exist) and the frontend hides the
register link and page. For an app that should never accept sign-ups, leave it off.
For one you open after testing, flip it on in `.env` and restart; no rebuild is needed
because the frontend reads the setting at runtime from `GET /api/v1/auth/config/`.

Create accounts from the server with
`python manage.py add_user EMAIL --name NAME [--admin]` (password is prompted twice).
That is how the first production account is made; with `--admin` it must add a passkey
at its first sign-in (see below).

## Auth guard and the login switch

`REQUIRE_LOGIN` (default `True`) decides whether anonymous visitors see anything:

| | `REQUIRE_LOGIN=True` (default) | `REQUIRE_LOGIN=False` |
|---|---|---|
| Routes with `meta: { public: true }` | sign-in required | open to visitors |
| API views with `permission_classes = [PublicReadOnly]` | sign-in required | visitors may `GET`; writes need a sign-in |
| Everything else | sign-in required | sign-in required |
| Login and register pages, `/api/v1/auth/` sign-in endpoints, `/health/` | open | open |

Set it in `.env` and restart; the frontend reads it at runtime from `/api/v1/auth/config/`
and treats a missing answer as `True`. Both sides are default-deny: a new page or view is
private until you opt it in, and opting in only takes effect while the switch is off. The
router guard is only for the UI; the API's permissions are what protect the data.

```python
from apps.users.permissions import PublicReadOnly

class ArticleList(APIView):
    permission_classes = [PublicReadOnly]   # public reading when REQUIRE_LOGIN=False
```

Expired access tokens are renewed from the refresh token, once per request, before the
user is sent to `/login`. Logging out revokes the refresh token (simplejwt's blacklist);
the access token itself lives on until it expires (60 minutes by default).

## Passkeys and admin accounts

Any user can add passkeys (Profile & settings) and sign in with one instead of their
password. After a password sign-in, users without a passkey are offered one; "Don't ask
again" is saved in their settings.

Staff accounts (`is_staff`, e.g. `add_user --admin`) must use one:

- The first password sign-in is followed by a dialog to add a passkey that can't be
  dismissed (only logged out of). After that, the password alone is refused.
- The Django admin lives at `ADMIN_URL` (`django-admin/` in development; a random path on
  servers set up by `hosting/provision.sh`) and has no password form. It sends staff to
  the app's sign-in, and a passkey sign-in opens the admin session.
- For admin-only API views use `IsPasskeyAdmin` (staff who signed in with a passkey)
  rather than `IsAdminUser`.
- Staff can't remove their last passkey. If it's lost:
  `python manage.py reset_passkeys EMAIL` removes the user's passkeys and revokes their
  sessions, so the next password sign-in asks for a new one.

Passkeys only work over HTTPS or on `localhost` (so use `http://localhost:5177` in
development, not `127.0.0.1` or a LAN address), and each one belongs to the hostname it
was created on. `PASSKEY_RP_NAME` sets the name browsers show; `PASSKEY_RP_ID` can pin
the relying party to a parent domain (e.g. `example.com` for `app.example.com`).

## Deploying

`hosting/` provisions and deploys the app on a Debian/Ubuntu VPS (nginx, gunicorn, systemd, PostgreSQL, rotating backups, Let's Encrypt HTTPS, and isolated per-app Python/Node runtimes):

1. Run `./hosting/provision.sh`. The first time, it asks for the server, name, domain and repo, and saves the answers in `hosting/.env` (gitignored, see [`hosting/.env.example`](hosting/.env.example)). It then sets up the server and prints a read-only GitHub deploy key.
2. Add the printed deploy key to GitHub, then run `./hosting/deploy.sh` to test, build, and deploy the pushed commit on the server.

The project's own deploy settings (folders, test and build commands) are at the top of `hosting/provision.sh`; the Python version is in `backend/.python-version` and the Node major in `"engines"` in `frontend/package.json`.

See [`docs/vps-hosting.md`](docs/vps-hosting.md) for the full guide.

## Dependencies

```bash
cd backend
uv add requests            # runtime dependency
uv add --dev pytest-cov    # dev-only (tests, tooling)
uv lock --upgrade          # upgrade everything within the pyproject ranges
```

Commit both `pyproject.toml` and `uv.lock`.

## Add New Apps

```bash
cd backend
uv run python manage.py startapp myapp
```

Then add to `INSTALLED_APPS` in `config/settings/base.py`.
