from django.apps import AppConfig


class RequestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.requests"
    label = "service_requests"  # avoids clashing with the `requests` Python library
    verbose_name = "Service Requests"
