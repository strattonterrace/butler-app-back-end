"""HTTP middleware for production observability.

RequestIDMiddleware  — every request gets an X-Request-ID. Use the inbound
                      header if the client (or upstream proxy) supplied one;
                      otherwise generate a UUID. The ID is bound to a
                      contextvar so the JSON log formatter can include it on
                      every log line emitted while handling that request.

LastActiveMiddleware — touches User.last_active_at on authenticated requests.
                      Throttled to once per ~60 s per user to avoid hot-row
                      contention; otherwise every authenticated GET would
                      issue an UPDATE.
"""
import contextvars
import logging
import time
import uuid

from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger("butler.request")

# Bound at request-start, read by the log filter.
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "butler_request_id", default="-",
)


class RequestIDMiddleware(MiddlewareMixin):
    HEADER_IN = "HTTP_X_REQUEST_ID"
    HEADER_OUT = "X-Request-ID"

    def process_request(self, request):
        rid = request.META.get(self.HEADER_IN) or uuid.uuid4().hex[:16]
        request.id = rid
        request_id_ctx.set(rid)

    def process_response(self, request, response):
        if hasattr(request, "id"):
            response[self.HEADER_OUT] = request.id
        return response


class RequestIDLogFilter(logging.Filter):
    """Attaches the current request_id to every log record."""
    def filter(self, record):
        record.request_id = request_id_ctx.get()
        return True


# ─────────────────────────────────────────────
# Last-active tracking
# ─────────────────────────────────────────────
# In-memory cache of "last write timestamp per user_id" — keeps writes throttled
# to roughly once per LAST_ACTIVE_THROTTLE_SECONDS regardless of request volume.
# Acceptable to lose this on restart — last_active_at will just be slightly stale.
LAST_ACTIVE_THROTTLE_SECONDS = 60
_last_active_writes: dict[str, float] = {}


class LastActiveMiddleware(MiddlewareMixin):
    """Updates request.user.last_active_at on authenticated requests.

    Throttled per-user to avoid hot-row UPDATEs on every API call. If the
    user hasn't been touched in the throttle window, write; otherwise skip.
    """
    def process_response(self, request, response):
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return response

        now = time.monotonic()
        last_write = _last_active_writes.get(str(user.id), 0.0)
        if now - last_write < LAST_ACTIVE_THROTTLE_SECONDS:
            return response

        _last_active_writes[str(user.id)] = now
        try:
            from django.utils import timezone

            type(user).objects.filter(pk=user.pk).update(
                last_active_at=timezone.now(),
            )
        except Exception:  # pragma: no cover — never break a request on telemetry
            logger.exception("LastActiveMiddleware failed for user=%s", user.pk)
        return response
