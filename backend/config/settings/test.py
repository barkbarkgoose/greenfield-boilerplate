"""Test settings for config project."""

from .local import *  # noqa: F401,F403

# Deterministic secret so the suite runs without a developer-specific .env or
# an initialized keychain. Never use this value outside of tests.
SECRET_KEY = "test-secret-key-not-for-production"

DEBUG = True

# Run fast password hashing and keep the test database in memory.
# Estimate parts synchronously (the VIN decode is mocked in tests).
PARTS_ESTIMATE_ASYNC = False

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Message threads are off by default for launch; the tests cover them on, and
# turn them off explicitly where that's what's being tested.
INTAKE_MESSAGING_ENABLED = True

ADMIN_URL = "admin/"
ADMIN_URL_IS_RANDOM = False

SITE_URL = "https://shop.example"
PASSKEY_RP_ID = "shop.example"
PASSKEY_ORIGINS = ["https://shop.example"]
