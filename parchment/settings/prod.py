"""Production settings."""

from .base import *  # noqa: F403
from .base import LOGGING, env

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
# HTMX reads the CSRF token from the page, so no JavaScript needs the cookie.
CSRF_COOKIE_HTTPONLY = True
SECURE_REFERRER_POLICY = "same-origin"

# Used for password reset emails, e.g. smtp+tls://user:password@smtp.example.com:587
vars().update(env.email_url("EMAIL_URL", default="smtp://localhost:25"))

# Rate limits must be shared by every gunicorn worker, so they live in the database
# (the table is created by `manage.py createcachetable` at startup).
CACHES = {"default": env.cache("CACHE_URL", default="dbcache://parchment_cache")}

LOG_FORMAT = env("DJANGO_LOG_FORMAT", default="json")
LOGGING["handlers"]["console"]["formatter"] = LOG_FORMAT
