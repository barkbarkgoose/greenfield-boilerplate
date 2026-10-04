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
│   │   ├── users/       # Custom User model, JWT auth, password reset
│   │   ├── intake/      # Delivery site: products, service area, dispatch, orders, invoices, staff
│   │   └── organizations/  # migration stub only (see Key Features)
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
- **Custom User Model** (email login, case-insensitive)
- **Password reset by email**: one-time links that expire after 2 hours
  (`PASSWORD_RESET_TIMEOUT`)
- **Rate limits** on sign-in (30/hour per IP) and reset requests (5/hour per IP)
- **Sessions** (`apps/users/tokens.py`, `frontend/src/utils/session.ts`): a short-lived
  access token renewed silently with a refresh token. Customers stay signed in for
  7 days (`JWT_*` keychain settings). Staff tokens last 15 minutes and staff sign in
  again after 8 hours (`STAFF_ACCESS_TOKEN_MINUTES`, `STAFF_SESSION_HOURS`).
  Changing or resetting a password signs out every other device right away.

The boilerplate's organizations and per-user settings / AI API key storage were
removed: this site doesn't use them. `apps/organizations` stays only as a migration
stub (its last migration drops the table) and can be deleted after a migration squash.
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
| `/api/v1/auth/register/` | POST | No | Create a customer account |
| `/api/v1/auth/login/` | POST | No | Get JWT tokens + user |
| `/api/v1/auth/refresh/` | POST | No | Refresh access token |
| `/api/v1/auth/password-reset/` | POST | No | Email a reset link (same answer whether or not the email exists; 5/hour) |
| `/api/v1/auth/password-reset/confirm/` | POST | No | Set a new password with the link's `uid` + `token` |
| `/api/v1/intake/catalog/` | GET | No | Products, per-yard prices, delivery fees, delivery days |
| `/api/v1/intake/estimate/` | POST | No | Coverage for a ZIP, routed loads and a price for `items` + `preferred_date` (120/hour) |
| `/api/v1/intake/orders/` | POST | Optional | Submit an order or special request (10/hour per IP); books the order's loads |
| `/api/v1/account/orders/` | GET | Yes | Customer's orders |
| `/api/v1/account/orders/<id>/` | GET | Yes | Order detail with messages and published invoice |
| `/api/v1/account/orders/<id>/messages/` | POST | Yes | Add a note/question (messaging on) |
| `/api/v1/account/orders/<id>/updates/` | GET | Yes | New messages since `?after=<message id>`, plus `updated_at` |
| `/api/v1/account/claim/` | POST | Yes | Attach a guest order via its claim token |
| `/api/v1/manage/summary/` | GET | Staff | Dashboard counts and scheduled deliveries |
| `/api/v1/manage/orders/` | GET | Staff | All orders; `status`, `q`, `unread`, `rush`, `needs_dispatch`, `ordering`, `page` |
| `/api/v1/manage/orders/<id>/` | GET/PATCH | Staff | Order detail (with loads and the ZIP's yard distances) / update status, date, window, notes |
| `/api/v1/manage/orders/<id>/replan/` | POST | Staff | Route the order again from scratch |
| `/api/v1/manage/orders/<id>/loads/<load id>/` | PATCH | Staff | Move a load to another truck (`{"truck": id}`) or unassign it (`null`) |
| `/api/v1/manage/orders/<id>/messages/` | POST | Staff | Reply to the customer (emails them) |
| `/api/v1/manage/orders/<id>/updates/` | GET | Staff | New customer messages since `?after=<message id>` |
| `/api/v1/manage/orders/<id>/invoice/` | GET/PUT/DELETE | Staff | The order's invoice (GET without one returns a draft from the order and its loads) |
| `/api/v1/manage/orders/<id>/invoice/preview/` | POST | Staff | Price an invoice without saving it |
| `/api/v1/manage/dispatch/?date=` | GET | Staff | One day's yards, stock, trucks and loads |
| `/api/v1/manage/stock/<id>/` | PATCH | Staff | Flip a product in/out of stock at a yard |
| `/api/v1/manage/trucks/<id>/` | PATCH | Staff | Take a truck out of service / back in |
| `/api/v1/manage/trucks/<id>/days-off/` | POST/DELETE | Staff | Mark a truck off for a date (`DELETE ?date=` clears it) |

## Dirt & Topsoil Delivery Site

This branch turns the boilerplate's mobile-mechanic site into a dirt and topsoil delivery
business. Accounts, passkeys, translations, the staff dashboard, invoices, consent, spam
protection and emails carry over; products, the zip-code service area, yards, trucks and
dispatch are new. **`docs/scheduling-and-dispatch.md`** explains routing in depth and
plans the scheduling work that's deferred.

### Try it locally

```bash
cd backend
uv run python manage.py migrate
uv run python manage.py seed_network        # 3 sample yards, 5 trucks, stock
uv run python manage.py check_service_area  # validates data/service_area.json
uv run python manage.py createsuperuser     # staff login for /dashboard
```

The sample service area is ~85 Denver-metro ZIP codes (e.g. `80202` Denver, `80002`
Arvada; `80403` Golden is special-request only; `99999` is outside). Replace it with your
own; see the doc above.

The intake app's migrations were reset to a single `0001_initial` for this branch, so
delete an old mechanic `db.sqlite3` before migrating.

### Pages

| Path | Who | What |
|------|-----|------|
| `/` (`/es`) | Anyone | Landing page: ZIP checker, products and prices, delivery pricing |
| `/order` (`/es/order`) | Anyone | Order form with live coverage, routing and price; `?mode=callback` for a special request, `?product=<key>` to preselect |
| `/account` | Customers | "My orders": open and past orders, "Order again" |
| `/account/orders/:id` | Customers | Order details, delivery date, invoice (plus a message thread when messaging is on) |
| `/settings` | Signed in | Profile and language |
| `/forgot-password`, `/reset-password/:uid/:token` | Anyone | Request a reset link; the page the emailed link opens |
| `/claim/:token` | Customers | Attaches a guest order to the signed-in account |
| `/dashboard` | Staff (`is_staff`) | Orders: filters, search, needs-dispatch / rush tiles, scheduled deliveries |
| `/dashboard/orders/:id` | Staff | Status, delivery date and window, dispatch (reassign trucks, re-plan), invoice, notes |
| `/dashboard/dispatch` | Staff | Day-by-day board: each yard's stock, each truck's loads and booked time, loads with no truck |

Make yourself staff with `python manage.py createsuperuser` (or tick `is_staff` in the
Django admin). Customers create accounts at `/register`. Yards, trucks and which products
each yard carries are set up in the Django admin; daily switches (in/out of stock, truck
in service, truck off for a day) are on the dispatch board.

### Django admin address

The Django admin lives at `ADMIN_URL` (env or keychain, e.g. `back-office-7f3k2q/`).
Set it to something hard to guess in each environment. Unset, the address is random
and changes every time the server starts; it's printed in the server log
("Django admin for this run: /admin-…/"). With several server processes (gunicorn
workers) each picks its own random address, so set `ADMIN_URL` wherever you actually
use the admin. In development the Vite proxy forwards `/admin*`, which covers the
random default; a custom `ADMIN_URL` is reachable on the backend port directly
(e.g. `http://localhost:8800/back-office-7f3k2q/`).

### Passkeys

Any account can be made to require a passkey after its password. Tick
**Passkey required** on the user in the Django admin (Sign-in security), or:

```bash
python manage.py reset_passkeys you@example.com --on    # require a passkey
python manage.py reset_passkeys you@example.com         # lost it: delete passkeys, set up a new one at next sign-in
python manage.py reset_passkeys you@example.com --off   # delete passkeys and stop requiring one
```

- **First sign-in after turning it on:** password as usual, then a "Set up your passkey"
  page. Nothing else works until a passkey is saved (the API enforces this too).
- **After that:** password, then the passkey prompt (Bitwarden, a phone, a security
  key). No session is issued until the passkey checks out. Settings → Passkeys adds a
  backup or removes one; the last one can't be removed while it's required.
- **Each environment has its own passkeys.** A passkey belongs to the site's domain
  (`PASSKEY_RP_ID`, taken from `SITE_URL`) and that environment's database, so you save
  one for localhost, one for staging and one for production. Bitwarden shows the
  domain on each.
- **Off switch:** `PASSKEYS_ENABLED=False` ignores the requirement site-wide (e.g. if it
  gives you grief in development). Per-user flags and saved passkeys are kept.
- `SITE_URL` must be the exact address you open the site at (scheme, host and port),
  or passkeys won't verify. Override with `PASSKEY_RP_ID` / `PASSKEY_ORIGINS` if needed.
- The Django admin login is still password-only; keep `ADMIN_URL` hard to guess.
- Code: `backend/apps/users/passkeys.py`, `frontend/src/services/passkeys.ts`.

Every page shares one header (`SiteHeader.vue`) and footer, signed in or not. Signed-in
people get an account menu; staff see "Dashboard" where customers see "My orders". A guest
who taps "My orders" gets a dialog explaining accounts, with buttons to create one or
sign in (both come back to their orders afterwards).

### Ordering

1. **Where:** address and ZIP code. The ZIP is looked up in the service-area table as
   it's typed: served ZIPs show "We deliver to {city}"; special-request and unlisted ZIPs
   turn the form into a special request (staff quote those by hand).
2. **What:** products by the cubic yard, with a "How much do I need?" calculator
   (length × width × depth → yards, rounded up). Fill dirt has a 5-yard minimum.
3. **When:** a delivery date (Monday–Saturday) and morning/afternoon/any. If trucks are
   full that day the form says so and offers the next open date.
4. **Drop spot:** where to dump it, with access tips.
5. The sidebar shows the price: material, one delivery line per truckload, rush fee,
   which yard(s) it ships from.

Submitting books the order's loads on the requested date (so the next quote sees those
trucks as busier) and emails you and the customer. Nothing is charged online. If routing
found no truck or no stock, the order is still taken and flagged for staff.

### Pricing

Pricing lives in `backend/apps/intake/pricing.py`: per-yard product prices at the top,
then the delivery rules. With the defaults, each truckload costs $75 for the first 10 miles
from the yard it ships from plus $3.50 a mile after that (rounded up to $5), delivery today
or tomorrow adds a $50 rush fee per order, and sales tax (`SALES_TAX_RATE`) is 0 until you
set it. Which yard and how many loads come from dispatch, so the price follows the
routing.

### Dispatch

`backend/apps/intake/dispatch.py` splits each product into truckloads and picks a yard and
truck for each: yards listed for the ZIP that stock the product, trucks running that day
with enough time left, preferring the least total truck time. Staff can move any load to
another truck, or re-plan after fixing stock or trucks. Changing an order's delivery date
moves its loads (and their trucks) to that day. The full rules, the zip-table workflow
(`build_service_area`, `check_service_area`, locked entries) and the deferred scheduler
plan are in `docs/scheduling-and-dispatch.md`.

### Saved order drafts

The order form saves itself in the browser as it's filled in (address, ZIP, products,
date, drop spot, contact details and notes), so a refresh, a trip to another page or
closing the tab doesn't lose it. It's stored in `localStorage` on that device only,
removed once the order is sent, and expires after 14 days. The form shows "Picked up where
you left off" with a "Clear the form" button when it restores one. Code:
`utils/orderDraft.ts`. Signed-in customers can also start from an earlier order ("Order
again" → `/order?from=<id>`).

### Invoices

On an order's dashboard page, the **Invoice** section builds the final bill:

- **Material delivered:** cubic yards that actually went out, at catalog prices (order
  minimums don't apply).
- **Loads:** one row per truck trip with its miles, priced like the quote. They start from
  the dispatched loads; "Reset to dispatched loads" puts them back. A warning shows when
  the loads don't add up to the yards delivered.
- **Other charges:** services (spreading), fees (wait time, a second dump spot) and
  adjustments (a negative price for a discount). You decide whether the rush fee applies.
- **Note to the customer**, shown on the invoice.

A live preview shows exactly what the customer will see. **Save draft** keeps it private;
**Publish to customer** shows it on their order page (optionally emailing it) and sets the
order's final total to the invoice total. Logic: `backend/apps/intake/invoicing.py`.

### Contact consent

Every order needs a phone number and a ticked box agreeing to be contacted by call, text
or email **about that order**. A second, optional box opts in to occasional seasonal deals.
Each order stores `contact_consent`, `marketing_consent`, `consent_at` and
`consent_version`. Staff see both on the order page and in the new-order email; staff
can't change them.

- **Changing the checkbox wording:** edit `order-consent__*` in both
  `frontend/src/i18n/locales/*.json` and bump `CONSENT_VERSION` in
  `backend/apps/intake/serializers.py`, so each order records which wording it agreed to.
- **Promotions list:** Django admin → Orders → filter "Marketing consent: Yes" → select all
  → action "Export contacts (CSV)". Only text or email people who opted in, and honor STOP
  replies.

### Messaging (off for launch)

The message thread on order pages, and the live-update polling that comes with it, is
**off by default**: customers call or text instead, and emails cover confirmations, status
changes and invoices. To turn it on, set `INTAKE_MESSAGING_ENABLED=1` (env or keychain)
and restart. The threads, the dashboard's "Unread messages" tile and the polling then
reappear on their own. `docs/realtime-messaging.md` covers the polling and instant
alternatives.

### How orders reach a customer's account

Orders placed while signed in go straight to the customer's account. Guest orders get a
one-time claim link (on the confirmation screen and in the confirmation email). Opening it
while signed in moves the order into that account. Orders are deliberately *not* linked by
email address, because signup doesn't verify email and anyone could otherwise register
with someone else's address to see their history.

### Email

| Event | Goes to |
|-------|---------|
| New order / special request | `INTAKE_NOTIFY_EMAILS` (you, with the dispatch plan; subject flags `[RUSH]` and `[NEEDS DISPATCH]`) and the customer (confirmation + claim link) |
| Customer adds a note (messaging on) | `INTAKE_NOTIFY_EMAILS` |
| You reply (messaging on) | The customer |
| You change status/date/window with "Email the customer" ticked | The customer |
| You publish an invoice with "Email the invoice" ticked | The customer |
| Someone requests a password reset | That account's email (in the language they used) |

Local development prints emails to the backend console. For production, set `SITE_URL`,
`BUSINESS_NAME`, `INTAKE_NOTIFY_EMAILS`, `DEFAULT_FROM_EMAIL`,
`EMAIL_HOST`/`EMAIL_PORT`/`EMAIL_HOST_USER` and put `EMAIL_HOST_PASSWORD` in the keychain
(see `backend/.env.example`). Set `TIME_ZONE` (e.g. `America/Denver`) so "today" and rush
dates follow the yard's clock. Emails are sent inline and failures are logged, never shown
to the customer.

### Spam protection

- A hidden honeypot field rejects simple bots (always on).
- [Cloudflare Turnstile](https://developers.cloudflare.com/turnstile/) captcha for guest
  submissions, on when both keys are set: `TURNSTILE_SECRET_KEY` (backend keychain) and
  `VITE_TURNSTILE_SITE_KEY` (frontend `.env`). Signed-in customers skip it.
- Per-IP rate limits: 10 submissions/hour, 120 estimates/hour.

## Translations (English / Spanish)

Customers can use the site in English or Spanish. What's translated:

- **Customer pages:** landing page, order form, my orders, order pages, invoices,
  sign in/up, profile & settings, header/footer.
- **Server text:** product names and descriptions, error messages, email subjects.
- **Customer emails:** sent in the language the customer ordered in.

Your side stays English: the staff dashboard, your notification emails (which say which
language the customer used), and the Django admin. Messages customers type, and the
invoice lines and notes you type, are shown as written.

### Where the text lives

| What | File(s) |
|------|---------|
| Page text | `frontend/src/i18n/locales/en.json`, `es.json` |
| Server text (products, errors, email subjects) | `backend/apps/intake/text/en.json`, `es.json` |
| Customer email bodies | `backend/apps/intake/templates/intake/email/customer_*.txt` (English) and `customer_*.es.txt` (Spanish) |
| Business name, phone, email (not translated) | `frontend/src/config/business.ts`, `BUSINESS_NAME` setting |

### Key names (BEM)

Keys say where the text appears: `block__element--modifier`.

- **block:** the page section or component, e.g. `landing-hero`, `order-location`,
  `account-order`, `site-header`. Page sections carry the block as a CSS class
  (`<section class="landing-hero">`), so inspecting an element in the browser tells you
  which keys it uses.
- **element:** the piece of text inside it, e.g. `title`, `zip-label`, `cta`.
- **modifier** (optional): a variant, e.g. `--primary`, `--delivery` / `--callback`, or a
  data value like `--fill_dirt` or `--scheduled`.

Examples: `order-location__zip-label`, `landing-hero__cta--primary`,
`request-status__label--scheduled`, `product__name--fill_dirt` (server).

Common blocks: `site-header`, `site-footer`, `app-nav`, `language-toggle`, `landing-*`,
`order-*` (order form sections), `account-*` (customer account), `auth-login`,
`auth-register`, `quote-breakdown`, `invoice-card`, `message-thread`, `request-status`,
`page-meta` (browser titles and descriptions).
Server side: `product`, `delivery-window`, `validation`, `email`, `email-status`,
`email-invoice`.

**Placeholders** use braces in both languages and must match: `"Hi {name}"` /
`"Hola {name}"`. **Plurals** (page text only) are separated by `" | "`:
`"{count} new reply | {count} new replies"`.

### Common changes

- **Reword something:** edit the value in both `en.json` and `es.json`. Not sure which key
  it is? Search the JSON for the English text.
- **Add text to a page:** add a key to both files and use `t('your-block__element')` in the
  component (`const { t } = useI18n()`).
- **Add a product:** add it to `PRODUCTS` in `pricing.py`, then `product__name--<key>` and
  `product__description--<key>` to both server text files, and a migration (the product
  choices on `YardStock`/`OrderLoad` change). Then mark which yards carry it in the admin.
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
in it. Each order records its language (`Order.language`), and customer emails use that
language. Saved quotes store keys rather than text, so the same order reads in Spanish
for the customer and English for you.

### Spanish addresses (`/es/`) and search engines

The landing page and order form have Spanish addresses: `/es` and `/es/order`. Spanish
visitors on `/` or `/order` are redirected to them, and the toggle switches between the
two. Each page adds `hreflang` links (`en`, `es`, `x-default`) and a translated `<title>`
and description, so search engines can index both versions. Signed-in pages (orders)
don't need separate addresses; they follow the saved language.

When you deploy:

- **Serve the app for `/es` paths.** The host must return `index.html` for `/es` and
  `/es/*`, the same single-page-app fallback every other route needs (e.g. Netlify
  `/* /index.html 200`, nginx `try_files $uri /index.html`).
- **Add both versions to your sitemap**: `/`, `/es`, `/order`, `/es/order`.
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
