"""Subscription views — thin wrappers over services + webhook intake.

Pattern matches apps.accounts: parse → delegate to services → serialize.
Stripe/network failures surface as 502 PAYMENT_SERVICE_ERROR so the
frontend can show "payment service unavailable" rather than a validation
error.
"""
import logging

import stripe
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClient

from . import services, webhooks
from .models import WebhookEvent
from .serializers import SubscriptionSerializer
from .services import StripeNotConfigured

logger = logging.getLogger("butler.subscriptions")


def _payment_service_error(exc) -> Response:
    logger.error("stripe call failed: %s", exc)
    return Response(
        {
            "status": "error",
            "message": "Payment service is temporarily unavailable. Please try again.",
            "code": "PAYMENT_SERVICE_ERROR",
        },
        status=status.HTTP_502_BAD_GATEWAY,
    )


class SubscriptionStatusView(APIView):
    """GET /api/v1/subscriptions/status/ — current client's billing state."""
    permission_classes = [IsAuthenticated, IsClient]

    def get(self, request):
        sub = services.get_or_create_subscription(request.user)
        return Response(SubscriptionSerializer(sub).data)


class CreateCheckoutView(APIView):
    """POST /api/v1/subscriptions/create-checkout/ → { checkoutUrl }"""
    permission_classes = [IsAuthenticated, IsClient]

    def post(self, request):
        sub = services.get_or_create_subscription(request.user)
        if sub.is_active:
            return Response(
                {
                    "status": "error",
                    "message": "You already have an active subscription.",
                    "code": "SUB_ALREADY_ACTIVE",
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            checkout_url = services.create_checkout_session(request.user)
        except (StripeNotConfigured, stripe.StripeError) as exc:
            return _payment_service_error(exc)
        return Response({"checkout_url": checkout_url})


class CancelSubscriptionView(APIView):
    """POST /api/v1/subscriptions/cancel/ — cancel at period end."""
    permission_classes = [IsAuthenticated, IsClient]

    def post(self, request):
        try:
            sub = services.cancel_subscription(request.user)
        except (StripeNotConfigured, stripe.StripeError) as exc:
            return _payment_service_error(exc)
        return Response(SubscriptionSerializer(sub).data)


class ReactivateSubscriptionView(APIView):
    """POST /api/v1/subscriptions/reactivate/ — undo a pending cancel."""
    permission_classes = [IsAuthenticated, IsClient]

    def post(self, request):
        try:
            sub = services.reactivate_subscription(request.user)
        except (StripeNotConfigured, stripe.StripeError) as exc:
            return _payment_service_error(exc)
        return Response(SubscriptionSerializer(sub).data)


class PortalSessionView(APIView):
    """POST /api/v1/subscriptions/portal-session/ → { portalUrl }"""
    permission_classes = [IsAuthenticated, IsClient]

    def post(self, request):
        try:
            portal_url = services.create_portal_session(request.user)
        except (StripeNotConfigured, stripe.StripeError) as exc:
            return _payment_service_error(exc)
        return Response({"portal_url": portal_url})


class StripeWebhookView(APIView):
    """POST /api/v1/subscriptions/webhook/ — Stripe event intake.

    Machine-to-machine endpoint: no JWT, auth is the webhook signature.
    Reads the raw body (never request.data) because signature verification
    hashes the exact bytes Stripe sent — any parser re-encoding breaks it.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        from django.conf import settings as dj_settings

        payload = request.body
        signature = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, dj_settings.STRIPE_WEBHOOK_SECRET,
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            logger.warning("webhook rejected: %s", exc)
            return Response(
                {"status": "error", "message": "Invalid webhook signature.",
                 "code": "WEBHOOK_INVALID"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Idempotency: the ledger insert and the handler's writes share one
        # transaction — a handler crash rolls back the ledger row so
        # Stripe's retry reprocesses cleanly; a duplicate delivery hits the
        # unique constraint and no-ops.
        try:
            with transaction.atomic():
                _, created = WebhookEvent.objects.get_or_create(
                    stripe_event_id=event["id"],
                    defaults={"event_type": event["type"]},
                )
                if not created:
                    return Response({"received": True, "duplicate": True})
                handled = webhooks.process_event(event)
        except IntegrityError:
            # Concurrent duplicate delivery lost the insert race
            return Response({"received": True, "duplicate": True})

        return Response({"received": True, "handled": handled})
