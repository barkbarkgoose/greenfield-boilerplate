# Boilerplate

Ready-to-use Django + Vue 3 project boilerplate with JWT auth.

## Quick Start

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

```bash
cd boilerplate/frontend

# Install dependencies
npm install

# Copy and edit environment
cp .env.example .env

# Run dev server
npm run dev
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
- **Custom User Model** with Organization FK
- **CORS configured** for frontend at localhost:5177
- **APPEND_SLASH=False** for clean API URLs

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/auth/register/` | POST | No | Register user + org |
| `/api/v1/auth/login/` | POST | No | Get JWT tokens |
| `/api/v1/auth/refresh/` | POST | No | Refresh access token |

## Add New Apps

```bash
cd backend
source venv/bin/activate
uv run python manage.py startapp myapp
```

Then add to `INSTALLED_APPS` in `config/settings/base.py`.
