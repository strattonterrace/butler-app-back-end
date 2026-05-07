"""Global DRF exception handler — uniform error envelope.

Format:
    {
      "status": "error",
      "message": "Human-readable",
      "errors": { ... }      // validation errors only
      "code": "ERROR_CODE"   // machine-readable
    }
"""
import logging

from django.core.exceptions import (
    PermissionDenied,
    ValidationError as DjangoValidationError,
)
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("butler")


def custom_exception_handler(exc, context):
    # Translate Django's ValidationError → DRF's ValidationError. Lets
    # services.py raise framework-agnostic Django ValidationError without
    # every view having to translate manually.
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            detail = exc.message_dict
        elif hasattr(exc, "messages"):
            detail = exc.messages
        else:
            detail = str(exc)
        django_code = getattr(exc, "code", None)
        exc = exceptions.ValidationError(detail)
        if django_code:
            exc._butler_code = django_code  # noqa: SLF001 — preserve service-level code

    response = exception_handler(exc, context)

    if response is None:
        # Unhandled — log and return a generic 500
        logger.exception("Unhandled exception in %s", context.get("view"))
        return Response(
            {
                "status": "error",
                "message": "An unexpected error occurred.",
                "code": "INTERNAL_SERVER_ERROR",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    payload = {"status": "error"}

    if isinstance(exc, exceptions.ValidationError):
        payload["message"] = "Validation failed."
        payload["errors"] = response.data
        payload["code"] = getattr(exc, "_butler_code", None) or "VALIDATION_ERROR"
    elif isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        payload["message"] = str(exc.detail) if hasattr(exc, "detail") else "Authentication required."
        payload["code"] = "AUTH_REQUIRED"
    elif isinstance(exc, (exceptions.PermissionDenied, PermissionDenied)):
        payload["message"] = str(getattr(exc, "detail", exc)) or "Permission denied."
        payload["code"] = getattr(exc, "code", "PERMISSION_DENIED") or "PERMISSION_DENIED"
    elif isinstance(exc, (exceptions.NotFound, Http404)):
        payload["message"] = "Resource not found."
        payload["code"] = "NOT_FOUND"
    elif isinstance(exc, exceptions.Throttled):
        payload["message"] = "Too many requests. Please try again later."
        payload["code"] = "RATE_LIMITED"
    else:
        payload["message"] = str(getattr(exc, "detail", exc))
        payload["code"] = "REQUEST_ERROR"

    response.data = payload
    return response
