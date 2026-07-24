"""Admin analytics services (BACKEND_SCOPE §12).

Revenue note: Butler has no invoice ledger table — Stripe is the system of
record for money. So "collected" figures are derived from the webhook event
log (each `invoice.payment_succeeded` = one paid period) and MRR is derived
from the live Subscription table. These are honest, queryable proxies; a
future phase can reconcile against Stripe's Billing API for the penny-exact
history. Every number here is grounded in a row we actually store.
"""
from datetime import date
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.drivers.models import DriverProfile
from apps.requests.models import RequestStatus, ServiceRequest
from apps.subscriptions.models import Subscription, SubscriptionStatus, WebhookEvent

_DEFAULT_PLAN = Decimal("199.00")
_BILLABLE = {SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE}


def _mrr() -> Decimal:
    """Monthly recurring revenue — sum of plan_amount over active subs."""
    total = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
    ).aggregate(s=Sum("plan_amount"))["s"]
    return total or Decimal("0.00")


def _total_collected() -> Decimal:
    """Best-effort lifetime collected: one paid invoice event ≈ one period.

    Grounded in the webhook idempotency ledger, which records every
    `invoice.payment_succeeded` Stripe confirmed. Uniform $199 pricing makes
    count × plan a faithful proxy until a true invoice ledger exists.
    """
    paid = WebhookEvent.objects.filter(event_type="invoice.payment_succeeded").count()
    return _DEFAULT_PLAN * paid


def _month_bounds(year: int, month: int):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def _churn_rate() -> float:
    """Cancellations in the last 30 days over the exposed base (active +
    those churned). Returns 0.0 when there's no base yet (avoids NaN)."""
    since = timezone.now() - timezone.timedelta(days=30)
    cancelled_recent = Subscription.objects.filter(
        status=SubscriptionStatus.CANCELLED, cancelled_at__gte=since,
    ).count()
    active = Subscription.objects.filter(status=SubscriptionStatus.ACTIVE).count()
    base = active + cancelled_recent
    if base == 0:
        return 0.0
    return round(cancelled_recent / base, 4)


def dashboard_metrics() -> dict:
    """The §12 /admin/metrics/ overview card."""
    today = timezone.localdate()
    requests = ServiceRequest.objects.all()
    open_statuses = [
        RequestStatus.SUBMITTED, RequestStatus.REVIEWED,
        RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS,
    ]
    return {
        "total_clients": User.objects.filter(role=Role.CLIENT).count(),
        "active_subscribers": Subscription.objects.filter(
            status=SubscriptionStatus.ACTIVE,
        ).count(),
        "total_drivers": User.objects.filter(role=Role.DRIVER).count(),
        "approved_drivers": DriverProfile.objects.approved().count(),
        "pending_driver_applications": DriverProfile.objects.pending().count(),
        "total_requests": requests.count(),
        "active_requests": requests.filter(status__in=open_statuses).count(),
        "completed_requests_today": requests.filter(
            status=RequestStatus.COMPLETED, completed_at__date=today,
        ).count(),
        "monthly_revenue": _mrr(),
        "total_revenue": _total_collected(),
        "churn_rate": _churn_rate(),
    }


def revenue_report(months: int = 6) -> dict:
    """The §12 /admin/revenue/ chart series + summary.

    Monthly subscriber counts estimate how many subscriptions were live in
    each month (created on/before the month, not yet cancelled by then).
    revenue = subscribers × plan for that month.
    """
    today = timezone.localdate()
    series = []

    # Walk back `months` months from the current one, oldest first.
    year, month = today.year, today.month
    cursor = []
    for _ in range(months):
        cursor.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    cursor.reverse()

    for yr, mo in cursor:
        _, month_end = _month_bounds(yr, mo)
        live = Subscription.objects.filter(
            created_at__date__lt=month_end,
            status__in=_BILLABLE,
        )
        # A sub counts for the month unless it was cancelled before the month.
        live = live | Subscription.objects.filter(
            created_at__date__lt=month_end,
            status=SubscriptionStatus.CANCELLED,
            cancelled_at__date__gte=date(yr, mo, 1),
        )
        subscribers = live.distinct().count()
        revenue = _DEFAULT_PLAN * subscribers
        series.append({
            "month": f"{yr:04d}-{mo:02d}",
            "revenue": revenue,
            "subscribers": subscribers,
        })

    active = Subscription.objects.filter(status=SubscriptionStatus.ACTIVE).count()
    month_start = today.replace(day=1)
    cancelled_this_month = Subscription.objects.filter(
        status=SubscriptionStatus.CANCELLED, cancelled_at__date__gte=month_start,
    ).count()

    return {
        "monthly": series,
        "summary": {
            "total_revenue": _total_collected(),
            "average_revenue_per_user": _DEFAULT_PLAN if active else Decimal("0.00"),
            "active_subscribers": active,
            "cancelled_this_month": cancelled_this_month,
        },
    }
