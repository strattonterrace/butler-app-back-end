"""Local development overrides."""
from .base import *  # noqa: F401,F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "testserver"]

# Looser CORS for local dev — Vite dev server on 5173 by default
CORS_ALLOW_ALL_ORIGINS = True

# Disable throttling in dev / tests — production keeps the base.py rates.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {
        "anon": None,
        "user": None,
        "auth_login": None,
        "auth_register": None,
        "password_reset": None,
    },
}

# Passwords stay validated, but min length relaxed slightly for dev fixtures
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 6}},
]

# Console email backend in dev — see emails in the runserver output
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
