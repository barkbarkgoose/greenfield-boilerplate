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
  input validation, and API keys encrypted at rest via `apps/users/crypto.py`.
  The AI provider and API key settings are hidden in this site's UI (it doesn't use
  AI); the API still accepts them, so they can come back without a migration.
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
| `/api/v1/intake/estimate/` | POST | No | Price a set of services for a date; also returns a parts estimate if `vehicle_type` is given |
| `/api/v1/intake/requests/` | POST | Optional | Submit a booking or contact request (10/hour per IP) |
| `/api/v1/intake/requests/parts-estimate/` | POST | Claim token | Read a guest request's parts estimate |
| `/api/v1/garage/vehicles/` | GET | Yes | Customer's vehicles with repair history |
| `/api/v1/garage/vehicles/<id>/` | PATCH | Yes | Rename a vehicle (nickname) |
| `/api/v1/garage/requests/` | GET | Yes | Customer's requests |
| `/api/v1/garage/requests/<id>/` | GET | Yes | Request detail with messages |
| `/api/v1/garage/requests/<id>/messages/` | POST | Yes | Add a note/question |
| `/api/v1/garage/requests/<id>/updates/` | GET | Yes | New messages since `?after=<message id>`, plus `updated_at` (polled by the open page) |
| `/api/v1/garage/claim/` | POST | Yes | Attach a guest request via its claim token |
| `/api/v1/manage/summary/` | GET | Staff | Dashboard counts and upcoming appointments |
| `/api/v1/manage/requests/` | GET | Staff | All requests; `status`, `q`, `unread`, `emergency`, `ordering`, `page` |
| `/api/v1/manage/requests/<id>/` | GET/PATCH | Staff | Request detail / update status, appointment, notes |
| `/api/v1/manage/requests/<id>/parts-estimate/` | POST | Staff | Recalculate a request's parts estimate |
| `/api/v1/manage/requests/<id>/messages/` | POST | Staff | Reply to the customer (emails them) |
| `/api/v1/manage/requests/<id>/updates/` | GET | Staff | New customer messages since `?after=<message id>` |
| `/api/v1/manage/requests/<id>/invoice/` | GET/PUT/DELETE | Staff | The request's invoice (GET without one returns a draft from the requested jobs) |
| `/api/v1/manage/requests/<id>/invoice/preview/` | POST | Staff | Price an invoice without saving it |

## Mobile Mechanic Site

### Pages

| Path | Who | What |
|------|-----|------|
| `/` (`/es`) | Anyone | Landing page: services, labor prices, bundles, booking policy |
| `/book` (`/es/book`) | Anyone | Intake form with live estimate; `?mode=callback` for "just contact me" |
| `/account` | Customers | "My garage": each car with its repair history |
| `/account/requests/:id` | Customers | Request details, appointment, invoice, notes/questions thread |
| `/settings` | Signed in | Profile and language |
| `/claim/:token` | Customers | Attaches a guest booking to the signed-in account |
| `/dashboard` | Staff (`is_staff`) | Bookings dashboard: filters, search, unread, upcoming |
| `/dashboard/requests/:id` | Staff | Manage status, appointment, odometer, private notes; build the invoice; reply |

Make yourself staff with `python manage.py createsuperuser` (or tick `is_staff` in the
Django admin). Customers create accounts at `/register`; no organization is needed.

Every page shares one header (`SiteHeader.vue`) and footer, signed in or not. Signed-in
people get an account menu; staff see "Dashboard" where customers see "My garage". A guest
who taps "My garage" gets a dialog explaining the garage, with buttons to create an
account or sign in (both come back to the garage afterwards).

### Saved booking drafts

The booking form saves itself in the browser as it's filled in (services, vehicle,
date, contact details and notes), so a refresh, a trip to another page or closing the
tab doesn't lose it. It's stored in `localStorage` on that device only, removed once the
request is sent, and expires after 14 days. The form shows "Picked up where you left
off" with a "Clear the form" button when it restores one. Code: `utils/intakeDraft.ts`.

### Invoices

On a request's dashboard page, the **Invoice** section builds the verified bill:

- **Work done:** tick catalog jobs on or off. They're repriced like a booking, so bundles,
  free add-ons and the volume rate still apply. You decide whether the rush fee applies.
- **Lines:** parts at what you actually paid, shipping, extra labor (hours × rate,
  for "other" work) and adjustments (a negative price for a discount). "+ Parts from
  estimate" pre-fills part lines from the parts estimate for you to correct.
- **Note to the customer**, shown on the invoice.

A live preview shows exactly what the customer will see. **Save draft** keeps it private;
**Publish to customer** shows it in their garage as a verified invoice (optionally
emailing it) and sets the request's final total to the invoice total. Edits after
publishing are visible as soon as you save; **Unpublish** hides it again. Logic:
`backend/apps/intake/invoicing.py`.

### Live updates

An open request page (customer or staff) checks for new messages every 10 seconds
while the tab is visible, and reloads the request when something else changed (status,
appointment, invoice). This is polling, not push: it works on any Django server with no
extra infrastructure. `docs/realtime-messaging.md` explains the options for instant
updates (Server-Sent Events or WebSockets) if you ever want them.

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

Labor estimates exclude parts; see parts estimates below.

### Parts estimates (your price table)

Parts estimates come from real prices you collect, stored as **price examples**: one row
per job and vehicle type (sedan, crossover, SUV, truck, European), optionally for a specific
make. `price` is the parts cost for one unit of the job: one axle for brakes and suspension,
the whole job otherwise (e.g. oil + filter).

For each job on a booking, the estimate is the **min / median / max** of the best-matching
examples: same make and type first, then same make, then same type. Jobs with no match are
shown as "quoted separately". No AI model is involved.

The customer can pick their own vehicle type on the booking form before submitting (no VIN
needed) to preview a parts range alongside the labor estimate; that choice is also what gets
saved, so the VIN decode at submission won't override it. If they leave it blank, the vehicle
type comes from the VIN decode instead (European make, then pickup / SUV / car body, with
SUVs split from crossovers by weight class) — and if that decode call itself fails,
`apps/intake/data/make_vehicle_type_defaults.json` has a small best-effort fallback for a
handful of makes with an unambiguous lineup (e.g. Ram is always a truck). You can change the
vehicle type on the request page, which recalculates the estimate. Customers see the result
on the confirmation screen and their request page, with the zero-markup promise. Until the
table has at least one row, the feature stays off.

Maintain the table in a spreadsheet and import it, or edit rows in the Django admin
(`/admin/intake/partpriceexample/`):

```bash
cd backend
# Blank fill-in sheet: every job x vehicle type, with the price unit spelled out.
cp apps/intake/data/part_prices_template.csv ~/part_prices.csv
uv run python manage.py import_part_prices ~/part_prices.csv --replace   # CSV becomes the table
uv run python manage.py export_part_prices > part_prices.csv             # back to a spreadsheet
```

Columns: `service`, `vehicle_type`, `price`, and optionally `vehicle_make`, `part_brand`,
`description`, `source`, `source_url`. Add as many rows per job as you like (several
brands, several stores): more examples make better ranges. Rows without a price are skipped,
and an import with any bad row imports nothing and lists what to fix.

`apps/intake/data/part_prices_example.csv` has placeholder prices (two brands per job x
vehicle type, so you get a real low/high range) to see the feature working end to end.
Import it to try it out, then replace it with your own research:
`uv run python manage.py import_part_prices apps/intake/data/part_prices_example.csv --replace`.

### Email

| Event | Goes to |
|-------|---------|
| New booking / contact request | `INTAKE_NOTIFY_EMAILS` (you) and the customer (confirmation + claim link) |
| Customer adds a note | `INTAKE_NOTIFY_EMAILS` |
| You reply | The customer |
| You change status/appointment with "Email the customer" ticked | The customer |
| You publish an invoice with "Email the invoice" ticked | The customer |

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

## Translations (English / Spanish)

Customers can use the site in English or Spanish. What's translated:

- **Customer pages:** landing page, booking form, garage, request pages, invoices,
  sign in/up, profile & settings, header/footer, parts estimate.
- **Server text:** service names, deals, discount lines, error messages, email subjects.
- **Customer emails:** sent in the language the customer booked in.

Your side stays English: the staff dashboard, your notification emails (which say which
language the customer used), and the Django admin. Messages customers type, and the
invoice lines and notes you type, are shown as written.

### Where the text lives

| What | File(s) |
|------|---------|
| Page text | `frontend/src/i18n/locales/en.json`, `es.json` |
| Server text (services, deals, errors, email subjects) | `backend/apps/intake/text/en.json`, `es.json` |
| Customer email bodies | `backend/apps/intake/templates/intake/email/customer_*.txt` (English) and `customer_*.es.txt` (Spanish) |
| Business name, phone, email (not translated) | `frontend/src/config/business.ts`, `BUSINESS_NAME` setting |

### Key names (BEM)

Keys say where the text appears: `block__element--modifier`.

- **block:** the page section or component, e.g. `landing-hero`, `intake-vehicle`,
  `garage-request`, `site-header`. Page sections carry the block as a CSS class
  (`<section class="landing-hero">`), so inspecting an element in the browser tells you
  which keys it uses.
- **element:** the piece of text inside it, e.g. `title`, `vin-label`, `cta`.
- **modifier** (optional): a variant, e.g. `--primary`, `--booking` / `--callback`, or a
  data value like `--brake_pads` or `--scheduled`.

Examples: `intake-vehicle__vin-label`, `landing-hero__cta--primary`,
`request-status__label--scheduled`, `service__name--brake_pads` (server).

Common blocks: `site-header`, `site-footer`, `app-nav`, `language-toggle`, `landing-*`,
`intake-*` (booking form sections), `garage-*` (customer account), `auth-login`,
`auth-register`, `parts-estimate`, `parts-policy`, `estimate-breakdown`,
`message-thread`, `request-status`, `page-meta` (browser titles and descriptions).
Server side: `service`, `bundle`, `deal`, `discount`, `vehicle-type`, `validation`,
`email`, `email-status`.

**Placeholders** use braces in both languages and must match: `"Hi {name}"` /
`"Hola {name}"`. **Plurals** (page text only) are separated by `" | "`:
`"{count} new reply | {count} new replies"`.

### Common changes

- **Reword something:** edit the value in both `en.json` and `es.json`. Not sure which key
  it is? Search the JSON for the English text.
- **Add text to a page:** add a key to both files and use `t('your-block__element')` in the
  component (`const { t } = useI18n()`).
- **Add a service:** add it in `pricing.py`, then `service__name--<key>` and
  `service__description--<key>` to both server text files.
- **Change an email:** edit both `customer_x.txt` and `customer_x.es.txt`.

### Reviewing translations in a spreadsheet

```bash
python i18n_review.py export translations.csv   # every string: area, key, english, spanish
# ...edit the english/spanish columns in Excel / Google Sheets / Numbers...
python i18n_review.py import translations.csv   # writes the JSON files back
```

The import refuses unknown keys or empty cells and changes nothing in that case. Email
bodies aren't in the CSV; review the `customer_*.es.txt` templates directly.

### Tests that guard the pairs

```bash
cd frontend && pnpm vitest run src/i18n                                              # page text
cd backend && uv run --with-requirements requirements.txt python -m pytest apps/intake/test_i18n.py   # server text + emails
```

They fail when:

- a key exists in one language but not the other, or is empty
- the two languages use different `{placeholders}` or plural branches
- a key isn't BEM-shaped
- the code uses a key that doesn't exist, or a key is no longer used (page text)
- a customer email template has no Spanish version

The frontend build also type-checks that `es.json` has every English key.

### How the language is chosen

1. An `/es/...` address, or `?lang=es` / `?lang=en` on any link. Spanish emails add
   `?lang=es` to their links, so they open in Spanish on any device.
2. Otherwise the visitor's last choice from the EN/ES toggle in the header, saved in
   their browser.
3. Otherwise their browser language (Spanish browsers get Spanish).

The frontend sends the language to the API (`Accept-Language`), so server text comes back
in it. Each booking records its language (`ServiceRequest.language`), and customer emails
use that language. Saved estimates store keys rather than text, so the same booking reads
in Spanish for the customer and English for you.

### Spanish addresses (`/es/`) and search engines

The landing page and booking form have Spanish addresses: `/es` and `/es/book`. Spanish
visitors on `/` or `/book` are redirected to them, and the toggle switches between the
two. Each page adds `hreflang` links (`en`, `es`, `x-default`) and a translated `<title>`
and description, so search engines can index both versions. Signed-in pages (garage,
requests) don't need separate addresses; they follow the saved language.

When you deploy:

- **Serve the app for `/es` paths.** The host must return `index.html` for `/es` and
  `/es/*`, the same single-page-app fallback every other route needs (e.g. Netlify
  `/* /index.html 200`, nginx `try_files $uri /index.html`).
- **Add both versions to your sitemap**: `/`, `/es`, `/book`, `/es/book`.
- **Check Search Console** after launch. Google renders JavaScript, so the hreflang links
  and titles are picked up. If Spanish pages don't show up in results after a few weeks,
  prerendering the two public pages (e.g. `vite-plugin-ssg` or a prerender service) is the
  next step.

**To give another public page a Spanish address:** change its route path to
`'/:locale(es)?/your-path'`, add `localized: true` to its `meta`, and add
`page-meta__title--<route-name>` (and optionally `page-meta__description--<route-name>`)
to both page text files.

### Adding a third language

1. Copy both `en.json` files to `<code>.json` and translate them.
2. Add the code to `SUPPORTED_LOCALES` in `frontend/src/i18n/index.ts`, to `LANGUAGES` in
   `backend/apps/intake/i18n.py`, and to `LANGUAGES` in `config/settings/base.py`.
3. Add `customer_*.<code>.txt` email templates.
4. Add `language-toggle__option--<code>`. The header toggle (`LanguageToggle.vue`) flips
   between two languages, so replace it with a small menu.
5. To give it its own addresses, widen the route pattern, e.g. `/:locale(es|fr)?`.

## Add New Apps

```bash
cd backend
source venv/bin/activate
uv run python manage.py startapp myapp
```

Then add to `INSTALLED_APPS` in `config/settings/base.py`.
