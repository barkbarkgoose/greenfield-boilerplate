"""Base settings for config project."""

import os
import sys
from datetime import timedelta
from pathlib import Path

import environ

env = environ.Env()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Make the `keychain` package importable when settings load through a plain
# `python manage.py` invocation (dev.sh already adds backend/ to sys.path).
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

environ.Env.read_env(BASE_DIR / ".env")

from keychain import (  # noqa: E402
    KeychainNotInitializedError,
    get as keychain_get,
    get_int as keychain_get_int,
    get_list as keychain_get_list,
)


def _env_or_keychain(key: str, env_var: str, default: str | None = None) -> str | None:
    """Resolve a scalar setting: environment / `.env` first, then the keychain.

    The environment always wins, so a value can be overridden on any machine
    without touching the encrypted keychain. The keychain is optional: if it has
    not been initialized, it is simply skipped.
    """
    value = env(env_var, default=None)
    if value is not None:
        return value
    try:
        value = keychain_get(key)
    except KeychainNotInitializedError:
        value = None
    return value if value is not None else default


def _env_or_keychain_list(
    key: str, env_var: str, default: list[str] | None = None
) -> list[str]:
    """Resolve a comma-separated list setting: environment first, then the keychain."""
    if env_var in os.environ:
        return env.list(env_var)
    try:
        value = keychain_get_list(key)
    except KeychainNotInitializedError:
        value = None
    if value is not None:
        return value
    return default if default is not None else []


SECRET_KEY = _env_or_keychain("SECRET_KEY", "SECRET_KEY")

DEBUG = env.bool("DEBUG", default=False)

ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "apps.organizations",
    "apps.users",
    "apps.passkeys",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

APPEND_SLASH = False

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL everywhere. The dev default is a local database named after the repo folder
# (greenfield-boilerplate -> greenfield_boilerplate) over the local socket; dev.sh creates
# it. Servers set DATABASE_URL in /srv/NAME/.env. Tests use test_<name>, made and dropped.
_DEFAULT_DB = "".join(c if c.isalnum() else "_" for c in BASE_DIR.parent.name.lower())
DATABASE_URL = _env_or_keychain(
    "DATABASE_URL", "DATABASE_URL", default=f"postgres:///{_DEFAULT_DB}"
)
DATABASES = {"default": env.db_url_config(DATABASE_URL)}

AUTH_USER_MODEL = "users.User"

# Open sign-up. On by default for dev/tests; production.py turns it off.
ALLOW_REGISTRATION = env.bool("ALLOW_REGISTRATION", default=True)

# Site-wide login. True (the default): every page and API view needs a session, apart
# from signing in. False: views marked PublicReadOnly (and routes marked public in the
# frontend) can be read anonymously; writes always need a session.
REQUIRE_LOGIN = env.bool("REQUIRE_LOGIN", default=True)

# Where the Django admin lives, kept off the /admin/ every scanner tries. Production gets a
# random one from hosting/provision.sh. Staff reach it by signing in with a passkey.
ADMIN_URL = env("ADMIN_URL", default="django-admin/").strip("/") + "/"

# Passkeys (WebAuthn). The relying party ID is the hostname the browser is on unless set
# here; it must be that hostname or a parent domain of it, and passkeys only work for it.
PASSKEY_RP_ID = env("PASSKEY_RP_ID", default="")
PASSKEY_RP_NAME = env("PASSKEY_RP_NAME", default="App")

# Sessions are only used by the Django admin (the app uses JWTs), so keep them short.
SESSION_COOKIE_AGE = 12 * 60 * 60

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = _env_or_keychain_list(
    "CORS_ALLOWED_ORIGINS", "CORS_ALLOWED_ORIGINS"
)

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
}


def _jwt_lifetimes() -> tuple[timedelta, timedelta]:
    """Resolve JWT lifetimes: environment first, then the keychain, then defaults.

    Falls back to 60 minutes / 7 days when neither is set or the keychain has not
    been initialized yet (e.g. during the first migration).
    """

    def _resolve(name: str, default: int) -> int:
        value = env.int(name, default=None)
        if value is None:
            try:
                value = keychain_get_int(name, default=None)
            except KeychainNotInitializedError:
                value = None
        return value or default

    return (
        timedelta(minutes=_resolve("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", 60)),
        timedelta(days=_resolve("JWT_REFRESH_TOKEN_LIFETIME_DAYS", 7)),
    )


_ACCESS_LIFETIME, _REFRESH_LIFETIME = _jwt_lifetimes()

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": _ACCESS_LIFETIME,
    "REFRESH_TOKEN_LIFETIME": _REFRESH_LIFETIME,
}

# User settings / secrets-at-rest encryption. Optional: when unset, the users
# crypto helper falls back to keychain.key and then to a SHA-256 derivation of
# SECRET_KEY (see apps/users/crypto.py).
SETTINGS_ENCRYPTION_KEY = env("SETTINGS_ENCRYPTION_KEY", default="")
