"""Root URL configuration for butler_api."""
import logging

from django.contrib import admin
from django.db import OperationalError, connection
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

logger = logging.getLogger("butler.health")


def healthz(_request):
    """Health probe for Render's load balancer.

    Verifies:
      1. The Django process is responding (we got here).
      2. PostgreSQL is reachable and responsive.

    Returns 503 on DB failure so Render takes the instance out of the
    rotation rather than serving 500s to real users.
    """
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except OperationalError as exc:
        logger.error("healthz db check failed: %s", exc)
        return JsonResponse(
            {"status": "error", "detail": "database unreachable"},
            status=503,
        )

    return JsonResponse({"status": "ok", "database": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),

    # API v1
    path("api/v1/auth/", include("apps.accounts.urls_auth")),
    path("api/v1/users/", include("apps.accounts.urls_users")),

    # OpenAPI schema + Swagger UI — living contract for frontend integration
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/schema/swagger/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="schema-swagger",
    ),
    # Subscriptions, requests, drivers, admin endpoints land in M2/M3.
]
