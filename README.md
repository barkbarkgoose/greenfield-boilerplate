# Boilerplate

Ready-to-use Django + Vue 3 project boilerplate with JWT auth.

## First-Time Setup

The backend supports an encrypted keychain for secrets and other deployment-specific
configuration. It stores encrypted values in `backend/keychain.json` and its Fernet
key in `backend/keychain.key`; neither file is committed.

```bash
cd backend

# Install the cryptography dependency with the rest of the backend requirements.
uv pip install -r requirements.txt

# Create the encrypted store and its owner-only key file.
uv run python -m keychain init --from-example

# Move Django settings into the keychain. Quote values to preserve special characters.
uv run python -m keychain set "SECRET_KEY=replace-with-a-unique-production-secret"
uv run python -m keychain set "CORS_ALLOWED_ORIGINS=https://app.example.com"
uv run python -m keychain set "DATABASE_URL=postgres://user:password@db.example.com:5432/app"

# Verify encryption, decryption, and key-file permissions.
uv run python -m keychain doctor
```

`SECRET_KEY` and `CORS_ALLOWED_ORIGINS` use their `.env` values until a keychain value
is set, which keeps first-run management commands working. Once migrated, remove those
secret values from `.env`. Back up `backend/keychain.key` securely: without it,
`keychain.json` cannot be recovered. Rotate it with `uv run python -m keychain rotate-key`.

## Quick Start

Run both development servers together from the project root:

```bash
./dev.sh
```

The runner applies migrations, selects available ports beginning at `8800` and `5177`,
updates the Vite proxy and local CORS origins for those ports, and stops both processes
when you press Ctrl+C. Set `DEV_BACKEND_PORT_DEFAULT` or `DEV_FRONTEND_PORT_DEFAULT` in
the keychain to change the starting ports.

If `SECRET_KEY` is missing (or still the `.env.example` placeholder), the runner prompts
you to generate one and saves it to `backend/.env`. For unattended setups, set
`DEV_GENERATE_SECRET_KEY=1` to generate it without prompting.

### Backend

```bash
cd boilerplate/backend

# Create virtual environment
uv venv
source venv/bin/activate  # or .\.venv\Scripts\activate on Windows

# Install dependencies
uv pip install -r requirements.txt

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
cd boilerplate/frontend

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
uv run --with-requirements requirements.txt python -m pytest
```


## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/auth/register/` | POST | No | Register user + org |
| `/api/v1/auth/login/` | POST | No | Get JWT tokens + user |
| `/api/v1/auth/refresh/` | POST | No | Refresh access token |
| `/api/v1/auth/settings/` | GET | Yes | Read current user's settings |
| `/api/v1/auth/settings/` | PATCH | Yes | Update current user's settings |
| `/api/v1/intake/catalog/` | GET | No | Services, prices, bundles, booking policy |
| `/api/v1/intake/estimate/` | POST | No | Price a set of services for a date |
| `/api/v1/intake/requests/` | POST | Optional | Submit a booking or contact request (10/hour per IP) |
| `/api/v1/intake/requests/parts-estimate/` | POST | Claim token | Read a guest request's parts estimate |
| `/api/v1/garage/vehicles/` | GET | Yes | Customer's vehicles with repair history |
| `/api/v1/garage/vehicles/<id>/` | PATCH | Yes | Rename a vehicle (nickname) |
| `/api/v1/garage/requests/` | GET | Yes | Customer's requests |
| `/api/v1/garage/requests/<id>/` | GET | Yes | Request detail with messages |
| `/api/v1/garage/requests/<id>/messages/` | POST | Yes | Add a note/question |
| `/api/v1/garage/claim/` | POST | Yes | Attach a guest request via its claim token |
| `/api/v1/manage/summary/` | GET | Staff | Dashboard counts and upcoming appointments |
| `/api/v1/manage/requests/` | GET | Staff | All requests; `status`, `q`, `unread`, `emergency`, `ordering`, `page` |
| `/api/v1/manage/requests/<id>/` | GET/PATCH | Staff | Request detail / update status, appointment, notes |
| `/api/v1/manage/requests/<id>/parts-estimate/` | POST | Staff | Retry a failed parts estimate |
| `/api/v1/manage/requests/<id>/messages/` | POST | Staff | Reply to the customer (emails them) |

## Mobile Mechanic Site

### Pages

| Path | Who | What |
|------|-----|------|
| `/` | Anyone | Landing page: services, labor prices, bundles, booking policy |
| `/book` | Anyone | Intake form with live estimate; `?mode=callback` for "just contact me" |
| `/account` | Customers | "My garage": each car with its repair history |
| `/account/requests/:id` | Customers | Request details, appointment, notes/questions thread |
| `/claim/:token` | Customers | Attaches a guest booking to the signed-in account |
| `/dashboard` | Staff (`is_staff`) | Bookings dashboard: filters, search, unread, upcoming |
| `/dashboard/requests/:id` | Staff | Manage status, appointment, odometer, final total, private notes; reply |

Make yourself staff with `python manage.py createsuperuser` (or tick `is_staff` in the
Django admin). Customers create accounts at `/register`; no organization is needed.

### How bookings reach a customer's garage

Bookings made while signed in go straight to the customer's garage, matched to a car by
VIN. Guest bookings get a one-time claim link (on the confirmation screen and in the
confirmation email). Opening it while signed in moves the booking into that account.
Bookings are deliberately *not* linked by email address, because signup doesn't verify
email and anyone could otherwise register with someone else's address to see their history.

### Pricing

Pricing lives in one place, `backend/apps/intake/pricing.py`. Edit the business inputs at
the top (target rate, insurance reserve, drive time, emergency fee, lead time) and each
service's labor hours; the site and stored quotes follow. With the defaults, labor bills at
$55/hr ($50 target + $5 insurance), each visit adds a $45 service call fee for drive time,
jobs within 7 days add a $75 emergency fee, and pads/rotors/suspension on the same axle are
discounted by the labor hours they share. On top of that:

- **Free add-ons:** oil change and air filter labor is free when the rest of the visit is
  2+ hours (`FREE_ADDON_KEYS`, `FREE_ADDON_MIN_HOURS`).
- **Big-job rate:** once labor (after bundles, before fees) passes $200, further labor bills
  at $25/hr (`VOLUME_THRESHOLD`, `VOLUME_RATE`).

Labor estimates exclude parts; see AI parts estimates below.

### AI parts estimates

With `ANTHROPIC_API_KEY` set (keychain), each booking gets a parts estimate from Claude:
typical retail price ranges (economy to premium) for the parts each job needs on that
vehicle. Customers see it on the confirmation screen and their request page alongside an
all-in range; the mechanic sees the same estimate with a retry button if it failed.
Without a key the feature is off and nothing changes.

How it's locked down (details in `backend/apps/intake/parts.py`):

- No endpoint triggers a model call. Estimates are generated server-side, on a background
  thread, once per saved booking, which guests can only create after the captcha and the
  per-IP limit. The read endpoints only read.
- Only structured data is sent: VIN-decoded vehicle attributes (sanitized, 40 characters
  max) and catalog service keys. Customer notes and "other work" text are never sent.
- Output must match a JSON schema and is re-validated: unknown jobs dropped, prices and
  quantities clamped, text truncated. Totals are computed by the server.
- Results are cached per vehicle + jobs for 30 days, and `PARTS_ESTIMATE_DAILY_LIMIT`
  (default 50) caps new model calls per rolling 24 hours.

### Email

| Event | Goes to |
|-------|---------|
| New booking / contact request | `INTAKE_NOTIFY_EMAILS` (you) and the customer (confirmation + claim link) |
| Customer adds a note | `INTAKE_NOTIFY_EMAILS` |
| You reply | The customer |
| You change status/appointment with "Email the customer" ticked | The customer |

Local development prints emails to the backend console. For production, set `SITE_URL`,
`INTAKE_NOTIFY_EMAILS`, `DEFAULT_FROM_EMAIL`, `EMAIL_HOST`/`EMAIL_PORT`/`EMAIL_HOST_USER`
and put `EMAIL_HOST_PASSWORD` in the keychain (see `backend/.env.example`). Set
`TIME_ZONE` (e.g. `America/Denver`) so appointment times in emails are in shop time.
Emails are sent inline and failures are logged, never shown to the customer.

### Spam protection

- A hidden honeypot field rejects simple bots (always on).
- [Cloudflare Turnstile](https://developers.cloudflare.com/turnstile/) captcha for guest
  submissions, on when both keys are set: `TURNSTILE_SECRET_KEY` (backend keychain) and
  `VITE_TURNSTILE_SITE_KEY` (frontend `.env`). Signed-in customers skip it.
- Per-IP rate limits: 10 submissions/hour, 120 estimates/hour.

## Add New Apps

```bash
cd backend
source venv/bin/activate
uv run python manage.py startapp myapp
```

Then add to `INSTALLED_APPS` in `config/settings/base.py`.
