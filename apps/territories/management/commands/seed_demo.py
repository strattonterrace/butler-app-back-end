"""Seed demo accounts + sample requests so the owner can test every role
without Stripe. Run once via Render Shell: `python manage.py seed_demo`.

Idempotent. Creates a client WITH an active subscription so the request
lifecycle is testable without going through Stripe checkout. Clearly-labelled
demo accounts — remove before real launch.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.territories.models import Territory, TerritoryStatus
from apps.drivers.models import ApprovalStatus, DriverProfile
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.requests.models import RequestStatus, ServiceRequest

from django.core.management.base import BaseCommand

PW = "ButlerDemo2026!"


class Command(BaseCommand):
    help = "Seed demo accounts + sample requests for owner testing (no Stripe needed)."

    @transaction.atomic
    def handle(self, *args, **options):
        terr, _ = Territory.objects.get_or_create(
            name="Orange County, CA",
            defaults={"status": TerritoryStatus.ACTIVE},
        )

        def mk(email, name, role, territory=None):
            u = User.objects.filter(email=email).first()
            if u:
                return u
            return User.objects.create_user(
                email=email, password=PW, full_name=name, role=role,
                phone="+1 (949) 555-0100", territory=territory,
            )

        admin = mk("demo.admin@butlertest.com", "Demo Admin", Role.ADMIN)
        operator = mk("demo.operator@butlertest.com", "Demo Operator", Role.OPERATOR, terr)
        client = mk("demo.client@butlertest.com", "Demo Client", Role.CLIENT, terr)
        driver = mk("demo.driver@butlertest.com", "Demo Driver", Role.DRIVER, terr)
        pending = mk("demo.pending@butlertest.com", "Demo PendingDriver", Role.DRIVER, terr)

        # Active membership so the client can post requests WITHOUT Stripe.
        Subscription.objects.update_or_create(
            user=client,
            defaults={
                "status": SubscriptionStatus.ACTIVE,
                "plan_amount": Decimal("199.00"),
                "current_period_start": timezone.now(),
                "current_period_end": timezone.now() + timezone.timedelta(days=30),
            },
        )

        DriverProfile.objects.update_or_create(
            user=driver,
            defaults={
                "vehicle_make": "Toyota", "vehicle_model": "Camry", "vehicle_year": 2022,
                "license_plate": "DEMO123", "available_days": ["mon", "tue", "wed", "thu", "fri"],
                "approval_status": ApprovalStatus.APPROVED, "territory": terr,
                "approved_at": timezone.now(),
            },
        )
        DriverProfile.objects.update_or_create(
            user=pending,
            defaults={
                "vehicle_make": "Honda", "vehicle_model": "Civic", "vehicle_year": 2023,
                "license_plate": "DEMO456", "available_days": ["sat", "sun"],
                "approval_status": ApprovalStatus.PENDING, "territory": terr,
            },
        )

        # Sample requests across the lifecycle so every dashboard has content.
        samples = [
            ("grocery", "Weekly groceries from Trader Joe's", RequestStatus.SUBMITTED, None),
            ("pharmacy", "Pick up prescription at CVS", RequestStatus.REVIEWED, None),
            ("food_pickup", "Dinner pickup from Nobu", RequestStatus.ASSIGNED, driver),
            ("package", "Drop Amazon return at UPS", RequestStatus.IN_PROGRESS, driver),
            ("dry_cleaning", "Suits to Newport Cleaners", RequestStatus.COMPLETED, driver),
        ]
        for service_type, title, status, drv in samples:
            ServiceRequest.objects.get_or_create(
                client=client, title=title,
                defaults={
                    "service_type": service_type,
                    "description": "Demo request for owner testing.",
                    "pickup_location": "Fashion Island, Newport Beach, CA",
                    "dropoff_location": "1 Demo Way, Irvine, CA 92618",
                    "urgency": "today",
                    "status": status,
                    "operator": operator if status != RequestStatus.SUBMITTED else None,
                    "driver": drv,
                    "completed_at": timezone.now() if status == RequestStatus.COMPLETED else None,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"Demo data seeded. Password for all demo accounts: {PW}\n"
            f"  admin:    demo.admin@butlertest.com\n"
            f"  operator: demo.operator@butlertest.com\n"
            f"  client:   demo.client@butlertest.com (active membership)\n"
            f"  driver:   demo.driver@butlertest.com (approved)\n"
            f"  pending:  demo.pending@butlertest.com (awaiting approval)"
        ))
