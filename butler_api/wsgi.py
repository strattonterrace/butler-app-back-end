"""WSGI config for butler_api."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "butler_api.settings.production"
)

application = get_wsgi_application()
