"""Production settings for config project."""

from .base import *  # noqa: F401,F403

DEBUG = False
# Closed unless the environment says otherwise (ALLOW_REGISTRATION=True).
ALLOW_REGISTRATION = env.bool("ALLOW_REGISTRATION", default=False)

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")  # required in production, no default

# nginx terminates TLS and tells Django via this header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = False                # nginx already redirects 80 -> 443
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
SECURE_HSTS_SECONDS = 31536000             # turn on only after https works

# Send app logs (including tracebacks) to stdout -> systemd journal
LOGGING = {
   "version": 1,
   "disable_existing_loggers": False,
   "formatters": {"plain": {"format": "%(levelname)s %(name)s %(message)s"}},
   "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
   "root": {"handlers": ["console"], "level": "INFO"},
}
