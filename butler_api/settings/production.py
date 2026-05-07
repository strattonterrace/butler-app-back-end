"""Production settings — Render.

Fails fast at import time if any required environment variable is missing.
That guarantees a broken deploy is rejected by Render's health gate, rather
than silently booting and 500'ing on the first real request.
"""
from django.core.exceptions import ImproperlyConfigured

import dj_database_url
from decouple import config

from .base import *  # noqa: F401,F403


# ─────────────────────────────────────────────
# Required environment variables — fail fast
# ─────────────────────────────────────────────
_REQUIRED = ("SECRET_KEY", "DATABASE_URL", "ALLOWED_HOSTS")
_missing = [name for name in _REQUIRED if not config(name, default="")]
if _missing:
    raise ImproperlyConfigured(
        f"Missing required production env vars: {', '.join(_missing)}. "
        "Set them in the Render dashboard (Service → Environment) before deploy."
    )

DEBUG = False

# Render injects RENDER_EXTERNAL_HOSTNAME automatically
RENDER_EXTERNAL_HOSTNAME = config("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)  # noqa: F405

# Force SSL on Postgres connections in production
DATABASES["default"] = dj_database_url.config(  # noqa: F405
    default=config("DATABASE_URL"),
    conn_max_age=600,
    ssl_require=True,
)

# Security headers — Render terminates SSL at the proxy
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days; ramp up after verifying it's stable
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Email — Resend SMTP relay (M3 wires keys; until then console)
if config("RESEND_API_KEY", default=""):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "smtp.resend.com"
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = "resend"
    EMAIL_HOST_PASSWORD = config("RESEND_API_KEY")

# ─────────────────────────────────────────────
# Sentry — optional, env-driven (M1+)
# ─────────────────────────────────────────────
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration()],
            traces_sample_rate=config("SENTRY_TRACES_SAMPLE_RATE", default=0.1, cast=float),
            send_default_pii=False,
            environment=config("SENTRY_ENV", default="production"),
        )
    except ImportError:
        # sentry_sdk not installed — production deploy should `pip install sentry-sdk`
        # before setting SENTRY_DSN. Skip silently in dev / tests.
        pass
