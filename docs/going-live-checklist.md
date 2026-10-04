# Going live: what still needs to be set up

Nothing here is broken — these are features and settings that work locally (against
sqlite, with the console email backend) but need real values before the site is used
by actual customers. This is the list to come back to before launch.

## 1. Email (blocks password reset + every customer/owner email)

Password reset, booking confirmations, claim-token emails, staff "new request"
notifications, status-change emails, and invoice emails all go through the same
`_send()` in `apps/intake/notifications.py`. Locally they just print to the terminal
(`config/settings/local.py` sets the console email backend) — nothing is actually
delivered until real SMTP credentials are set:

```bash
cd backend
uv run python -m keychain set "EMAIL_HOST=smtp.yourprovider.com"
uv run python -m keychain set "EMAIL_HOST_USER=you@yourdomain.com"
uv run python -m keychain set "EMAIL_HOST_PASSWORD=..."
uv run python -m keychain set "DEFAULT_FROM_EMAIL=you@yourdomain.com"
uv run python -m keychain set "INTAKE_NOTIFY_EMAILS=you@yourdomain.com"
uv run python -m keychain doctor   # sanity-check the keychain itself
```

Any SMTP provider works (your domain registrar/host, Postmark, SES, etc.) — this repo
has no provider-specific code.

**Also set `SITE_URL`** to the real site URL (e.g. `https://wrenchonwheels.com`) —
it's used to build the links inside password-reset and claim-token emails, and it also
derives the passkey relying-party domain (`PASSKEY_RP_ID`). Left as `localhost`, reset
links in production emails would point at `localhost`.

## 2. Hosting

See [`private-preview-hosting.md`](./private-preview-hosting.md) for the full writeup
(Docker image, Fly.io, GitHub Action) — section 7 ("Moving from preview to production
later") is the short version: same image, a production Fly app (or similar) deployed
from `main`, real SMTP, real Turnstile keys, your real domain, and probably Postgres
instead of SQLite so the database can be backed up and scaled.

Settings that are still placeholder/commented-out in `config/settings/production.py`
and need real values before launch:

- `ALLOWED_HOSTS` — currently `["*"]`, should be your real domain(s).
- `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` — commented out;
  turn on once HTTPS is in place.
- `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` — from the keychain/env, currently
  unset.
- `DATABASE_URL` — defaults to local SQLite; point at Postgres for anything beyond a
  single-machine preview.
- `SECRET_KEY` — must be a real random value in the keychain, not the test default.

## 3. Captcha (Turnstile)

Public booking/contact endpoints only get spam protection (honeypot is always on, but
Turnstile captcha is off) until both `TURNSTILE_SECRET_KEY` (backend keychain) and
`VITE_TURNSTILE_SITE_KEY` (frontend `.env`, build-time) are set.

## 4. Parts price table

The parts-estimate feature silently stays off until `PartPriceExample` rows exist
(see README's "Parts estimates" section). `part_prices_example.csv` has placeholder
demo prices; replace with real ones (or start from `part_prices_template.csv`) before
launch, via the Django admin or `import_part_prices`.
