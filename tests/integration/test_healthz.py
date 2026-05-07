"""GET /healthz/ — Render's load balancer probe (now with DB check)."""
from unittest.mock import patch

import pytest
from django.db import OperationalError


@pytest.mark.integration
def test_healthz_returns_ok_with_db_status(db, api_client):
    resp = api_client.get("/healthz/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


@pytest.mark.integration
@pytest.mark.edge_case
def test_healthz_returns_503_when_db_unreachable(db, api_client):
    """When Postgres is down, the probe must return 503 so Render takes the
    instance out of rotation. Otherwise it serves 500s to real users."""
    with patch(
        "django.db.backends.utils.CursorWrapper.execute",
        side_effect=OperationalError("db down"),
    ):
        resp = api_client.get("/healthz/")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error"
