"""Rate limiting — verifies the global throttle actually enforces limits.

Dev/test settings set throttle rates to None (disabled), so this overrides the
user rate low and clears the throttle cache to prove the global throttle
classes (added in base.py) are wired and firing in production.
"""
import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolate_throttle_cache():
    """Throttle history lives in the cache; clear it around the test so
    rate-limit state never leaks."""
    cache.clear()
    yield
    cache.clear()


def _rf_with_rates(**rates):
    base_rates = dict(settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {}))
    base_rates.update(rates)
    return {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": base_rates}


def test_authenticated_requests_are_rate_limited(auth_client, client_user):
    """With the user rate capped at 3/min, the 4th+ request is throttled (429).

    This proves DEFAULT_THROTTLE_CLASSES is applied to ordinary data endpoints
    (not just the auth endpoints), which was the gap this change closes.
    """
    with override_settings(REST_FRAMEWORK=_rf_with_rates(user="3/min")):
        client = auth_client(client_user)
        codes = [client.get("/api/v1/requests/stats/").status_code for _ in range(5)]

    assert codes[:3] == [200, 200, 200], codes   # first 3 allowed
    assert 429 in codes[3:], codes                # the cap kicks in after that
