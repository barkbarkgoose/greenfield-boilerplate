"""Production settings for config project."""

from .base import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = ["*"]

CORS_ALLOWED_ORIGINS = []  # Configure appropriately for production

# Use PostgreSQL/MySQL in production
# DATABASES = {
#     'default': env.db('DATABASE_URL')
# }

# Security settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# HTTPS/SSL (enable on hosting platform)
# SECURE_SSL_REDIRECT = True
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True
