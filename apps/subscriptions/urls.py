"""Subscription URL routes — mounted at /api/v1/subscriptions/."""
from django.urls import path

from .views import (
    CancelSubscriptionView,
    CreateCheckoutView,
    PortalSessionView,
    ReactivateSubscriptionView,
    StripeWebhookView,
    SubscriptionStatusView,
)

urlpatterns = [
    path("status/", SubscriptionStatusView.as_view(), name="subscription-status"),
    path("create-checkout/", CreateCheckoutView.as_view(), name="subscription-checkout"),
    path("cancel/", CancelSubscriptionView.as_view(), name="subscription-cancel"),
    path("reactivate/", ReactivateSubscriptionView.as_view(), name="subscription-reactivate"),
    path("portal-session/", PortalSessionView.as_view(), name="subscription-portal"),
    path("webhook/", StripeWebhookView.as_view(), name="subscription-webhook"),
]
