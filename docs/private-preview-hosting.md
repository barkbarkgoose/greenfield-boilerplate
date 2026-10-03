# A private preview site that updates when Claude pushes

Goal: every time Claude pushes to its branch on GitHub, a hosted copy of the site
rebuilds automatically, and you can open it on your phone. Nobody else can see it.

**Short answer:** yes, this can be fully automatic. Your plan (build the Vue app, serve
it from Django, deploy one Python app) is the simplest setup that works, and it's a
common one. The recommended stack:

| Piece | Choice | Why |
|-------|--------|-----|
| Packaging | One Docker image: the Vue build inside the Django app | One thing to deploy, no CORS, one URL |
| Host | [Fly.io](https://fly.io) | Deploys from a GitHub Action, cheap, keeps a small disk for SQLite |
| Trigger | GitHub Action on push to `claude/**` | Claude's branch names change per session; a pattern catches them all |
| Privacy | Cloudflare Access (if you have a domain), or a preview password built into the app | Works on mobile, no VPN app needed |
| Database | SQLite on a Fly volume | No database service to run; it's a preview |

Cost at the time of writing is a few dollars a month (one small machine that sleeps
when idle, plus a 1 GB volume). Check current pricing before signing up.

The rest of this doc covers how the pieces fit, the code changes needed (none are in the
repo yet), the one-time setup, and alternatives with their trade-offs.

---

## 1. How it works

```
Claude pushes to claude/some-branch
        │
        ▼
GitHub Action (.github/workflows/preview.yml)
  - runs the backend and frontend tests
  - flyctl deploy  ──►  Fly.io builds the Dockerfile:
                          stage 1 (node):   pnpm build  → frontend/dist
                          stage 2 (python): Django + gunicorn + whitenoise,
                                            with frontend/dist copied in
        │
        ▼
The new version boots, runs `manage.py migrate`, starts serving
        │
        ▼
https://your-preview.example.com   (behind Cloudflare Access or a preview password)
```

There's one preview site, and the **latest push wins**: if two Claude sessions push to
different branches, the preview shows whichever deployed last. The deploy summary in
GitHub's Actions tab shows which branch and commit are live. Per-branch previews are
possible (see section 6), but they cost more setup for little gain when you're the only
reviewer.

**Do pushes from Claude trigger Actions?** Yes. Claude pushes with your GitHub
credentials or the Claude GitHub App, and both trigger workflows normally. (The only
pushes that don't trigger workflows are ones made with a workflow's own
`GITHUB_TOKEN`.)

---

## 2. Code changes needed

Ask Claude to make these. Each is small.

### 2a. Serve the built frontend from Django

- Add `whitenoise` and `gunicorn` to `backend/requirements.txt`.
- In settings: add `whitenoise.middleware.WhiteNoiseMiddleware` right after
  `SecurityMiddleware`, and set `WHITENOISE_ROOT` to the built frontend folder (e.g.
  `BASE_DIR / "frontend_dist"`). WhiteNoise then serves `/assets/...`,
  `/favicon.ico`, etc. at the site root, so Vite's default `base: '/'` keeps working.
- Add a catch-all URL **last** in `config/urls.py` that returns `frontend_dist/index.html`
  for anything that isn't `api/`, `admin/` or `static/`. That's the "SPA fallback": it
  lets `/book`, `/es/book` and `/account/requests/3` load on refresh. It also covers
  the `/es/*` hosting requirement in the README's Translations section.
- Django admin CSS: run `collectstatic` during the image build (it goes to
  `STATIC_ROOT`, and WhiteNoise serves it at `/static/`).

### 2b. Point the frontend at the same origin

`frontend/src/services/api.ts` currently does
`import.meta.env.VITE_API_URL || 'http://localhost:8800'`, so an empty value falls back
to localhost. Change `||` to `??` and build with `VITE_API_URL=` (empty). API calls then
go to `/api/v1/...` on the same site. There's no CORS to configure and nothing to
change per environment.

### 2c. Production settings from environment variables

In `config/settings/production.py`:

- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` from env (needed for the Django admin login
  over HTTPS), e.g. `your-preview.fly.dev` / `https://your-preview.fly.dev`.
- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`, plus
  `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` on.
- Everything else already reads env vars: `SECRET_KEY`, `DATABASE_URL`, `SITE_URL`,
  `EMAIL_BACKEND`, `INTAKE_NOTIFY_EMAILS`, `TURNSTILE_SECRET_KEY`, `TIME_ZONE`.

### 2d. Keep search engines out

Add an `X-Robots-Tag: noindex, nofollow` header (a 3-line middleware, on when
`PREVIEW=1`), so a preview URL never shows up in Google even if it leaks.

### 2e. `Dockerfile` (repo root), roughly

```dockerfile
# Stage 1: build the Vue app
FROM node:22-slim AS frontend
WORKDIR /app/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
ARG VITE_TURNSTILE_SITE_KEY=""
RUN VITE_API_URL= pnpm build

# Stage 2: Django serves the API, the admin and the built app
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.settings.production
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /app/frontend/dist ./frontend_dist
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput
# start.sh: `python manage.py migrate --noinput && exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 2 --timeout 60`
CMD ["./start.sh"]
```

(Check the `WORKDIR` and lockfile names against the repo when implementing.)

**Gunicorn and the parts-estimate thread:** parts estimates run in a background thread
after a booking (`PARTS_ESTIMATE_ASYNC`). That works under gunicorn's default sync
workers, because the thread finishes on its own after the response. Polling for live
chat (every 10s per open page) is light. Two workers are plenty for a preview.

### 2f. `fly.toml` (repo root), roughly

```toml
app = "wrench-preview"          # your app name
primary_region = "den"          # pick the region nearest you

[build]
  dockerfile = "Dockerfile"

[env]
  PREVIEW = "1"
  DATABASE_URL = "sqlite:////data/db.sqlite3"
  EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
  TIME_ZONE = "America/Denver"

[mounts]
  source = "data"
  destination = "/data"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "stop"   # sleeps when idle; wakes in a second or two on the next visit
  auto_start_machines = true
  min_machines_running = 0
```

**SQLite and the volume:** the database lives on the volume, so it survives deploys.
Keep to one machine (`fly scale count 1`), because SQLite can't be shared between
machines. Migrations run in `start.sh` when the machine boots, not in Fly's
`release_command`: that runs in a temporary machine *without* the volume, so it would
migrate an empty database. With Postgres, `release_command` is the usual choice.

Emails go to the console (`fly logs`) so the preview never mails real people. To get
the invoice and status emails yourself, switch to SMTP and set `INTAKE_NOTIFY_EMAILS` to
your address.

### 2g. GitHub Action: `.github/workflows/preview.yml`

```yaml
name: Preview deploy
on:
  push:
    branches: ["claude/**", "preview"]
  workflow_dispatch: {}         # adds a "Run workflow" button for manual redeploys

concurrency:
  group: preview                # one deploy at a time; a newer push cancels an older one
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv run --with-requirements requirements.txt python -m pytest -q
        working-directory: backend
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: pnpm, cache-dependency-path: frontend/pnpm-lock.yaml }
      - run: pnpm install --frozen-lockfile && pnpm vitest run && pnpm build
        working-directory: frontend

  deploy:
    needs: test                 # a red build never replaces a working preview
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
      - run: |
          echo "### Preview updated" >> $GITHUB_STEP_SUMMARY
          echo "Branch: \`${GITHUB_REF_NAME}\` at \`${GITHUB_SHA::7}\`" >> $GITHUB_STEP_SUMMARY
```

Because tests run first, the preview only updates when the branch is green. A side
benefit: CI on every Claude push, which the repo doesn't have yet.

**Who can deploy:** the token sits in GitHub Secrets. Workflows from forks can't read
secrets, so strangers' PRs can't deploy. Keep the repo private, or limit who can push
to `claude/**`.

---

## 3. Keeping it private

A preview shouldn't be public: it has a working booking form, the admin login and
whatever test data you enter. Options, best first:

### Option A: Cloudflare Access (recommended if you have, or will buy, a domain)

Put the domain on Cloudflare (free plan), point `preview.yourdomain.com` at the Fly app,
and add a Cloudflare Zero Trust **Access application** for that hostname with a policy
like "emails equal jake@…". Visitors get a Cloudflare page asking for their email, then
a one-time code (or "Sign in with Google"). The session lasts as long as you choose
(e.g. 30 days), so on your phone you log in once a month.

- Free for small teams (the free tier covered up to 50 users at the time of writing).
- Nothing in the app changes. Access uses its own cookie, so it doesn't clash with the
  app's JWT `Authorization` header (which plain HTTP basic auth would).
- To stop people going around it to `wrench-preview.fly.dev`: either check the
  `Cf-Access-Jwt-Assertion` header in Django (a small middleware), or simply not add the
  fly.dev host to `ALLOWED_HOSTS`.
- You'll need a domain (~$10–15/year). You'll want one for the real site anyway.

This is how many companies protect internal and staging sites ("zero trust" access).

### Option B: a preview password in the app (no domain needed)

A tiny Django middleware, on only when `PREVIEW_PASSWORD` is set. Any request without a
valid signed cookie gets a one-field password page. The right password sets the cookie
(HttpOnly, Secure, 30 days) and redirects back. About 40 lines plus a test. It works
on `*.fly.dev` with no other service, and on mobile it's a one-time password entry.
Use a long random password and rate-limit attempts.

Why not HTTP basic auth? It's the classic quick option, but it uses the same
`Authorization` header the app's API calls use for the login token, so signed-in pages
would break. Basic auth only fits sites with no login of their own.

### Option C: private network (Tailscale)

Install Tailscale on your phone and laptop and expose the app only to your tailnet
(e.g. Fly + Tailscale, or run the preview on a home machine with `tailscale serve`).
It's very secure, but you have to switch the VPN on to look, and you can't send a link
to someone else to try.

---

## 4. One-time setup checklist

1. Have Claude make the code changes in section 2 (on a branch, as usual).
2. Create a Fly.io account and install `flyctl`. Then run:
   - `fly launch --no-deploy` (picks up `fly.toml`; choose the app name and region)
   - `fly volumes create data --size 1`
   - `fly secrets set SECRET_KEY=<long random> SITE_URL=https://<your preview host>`
   - `fly secrets set ALLOWED_HOSTS=<host> CSRF_TRUSTED_ORIGINS=https://<host>`
   - Optional: `PREVIEW_PASSWORD`, `TURNSTILE_SECRET_KEY`
3. `fly tokens create deploy` and add the result to GitHub (repo Settings → Secrets and
   variables → Actions) as `FLY_API_TOKEN`.
4. Push (or click "Run workflow"). Watch it in the Actions tab.
5. Create your staff login once: `fly ssh console -C "python manage.py createsuperuser"`.
6. Load your parts prices: copy the CSV up with `fly ssh sftp`, then run
   `import_part_prices`, or use the Django admin.
7. Privacy: set up Cloudflare Access (option A) or set `PREVIEW_PASSWORD` (option B).
8. On your phone, open the URL and "Add to Home Screen" for one-tap access.

Day to day, there's nothing to do: Claude pushes, and the preview updates a few minutes
later if tests pass. If a deploy fails, the old version keeps running.

---

## 5. Alternatives and why they rank lower

**Render (render.com).** The simplest dashboard setup: connect the repo, pick a branch,
and it auto-deploys on push (from the same Dockerfile). The catch is that a Render
service watches **one fixed branch name**, and Claude's branch names change each
session. You'd need either a fixed `preview` branch that Claude merges into, or a
GitHub Action calling Render's deploy hook (which still builds the one tracked branch).
The free tier sleeps and has no persistent disk, so SQLite resets on every deploy; a
disk or Postgres needs a paid plan. A good choice if you settle on a single `preview`
branch.

**Railway.** Similar to Render, with GitHub auto-deploy and PR environments. Usage-based
pricing.

**Split hosting (static frontend + separate API).** Cloudflare Pages, Netlify or Vercel
give the frontend an automatic URL **per branch**, and Cloudflare Pages previews can be
put behind Access with a toggle. But the backend still needs its own host. You'd then
deal with CORS, a cross-site API URL baked in at build time, and the two halves
drifting out of sync between branches. That's a reasonable production setup at scale
(the frontend on a CDN), but it's more moving parts for a preview. Your one-app plan
avoids all of that.

**A VPS (Hetzner, DigitalOcean, Lightsail) with Docker + Caddy.** The cheapest per
month, and you have full control. But you maintain the server (updates, TLS via Caddy,
backups), and deploys run over SSH from the Action. Worth it later if you host several
projects on one box.

**Your own computer + Cloudflare Tunnel or Tailscale.** Free, but it's only up while
your computer is on, and the Action needs a way to reach it (a self-hosted GitHub
runner).

---

## 6. What's common in industry

- **CI on every push**: tests and a build check. The Action above adds this.
- **A staging environment**: one shared, production-like copy, auto-deployed from a
  branch (often `main` or `staging`). This doc's single preview is this pattern.
- **Preview environments per pull request** ("review apps"): Vercel, Netlify and
  Cloudflare Pages for frontends; Render Preview Environments, Heroku Review Apps and
  Railway PR environments for full stacks. Each PR gets its own URL and usually its own
  throwaway database seeded with test data, torn down when the PR closes. Teams use
  this when several people review several branches at once. With Fly, you can build it
  yourself: name the app after the branch (`wrench-pr-12`) and add a cleanup workflow
  on PR close.
- **Access control on non-production sites**: SSO or zero-trust gateways (Cloudflare
  Access, Google IAP, Vercel Deployment Protection). Basic auth or a shared password
  for small teams; a VPN for internal tools.
- **Never real customer data in previews**: seed fake data, and send emails to a
  sandbox (console, Mailpit, or a test inbox).

For one person reviewing Claude's work on a phone, the shared preview from sections 1–4
is the right size. Move to per-PR previews if you start running several Claude
branches in parallel and want to compare them side by side.

---

## 7. Moving from preview to production later

The same image runs production with different settings: a separate Fly app (say
`wrench-prod`) deployed from `main` only (or on a GitHub release), real SMTP email,
Turnstile keys, your real domain, and probably Postgres (Fly Postgres, Neon or Supabase)
instead of SQLite so you can back it up and scale. Keep the preview app around as
staging.
