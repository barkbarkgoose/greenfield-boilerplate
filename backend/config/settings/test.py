"""Test settings for config project."""

from .local import *  # noqa: F401,F403

# Deterministic secret so the suite runs without a developer-specific .env or
# an initialized keychain. Never use this value outside of tests.
SECRET_KEY = "test-secret-key-not-for-production"

DEBUG = True

# Run fast password hashing and keep the test database in memory.
# Never call the real model from tests; estimate synchronously when enabled.
ANTHROPIC_API_KEY = ""
PARTS_ESTIMATE_ASYNC = False

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
