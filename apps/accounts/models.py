"""User model — UUID PK, email-based auth, role-aware."""
import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class Role(models.TextChoices):
    CLIENT = "client", "Client"
    OPERATOR = "operator", "Operator"
    DRIVER = "driver", "Driver"
    ADMIN = "admin", "Admin"


class Status(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True, default="")

    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.CLIENT, db_index=True
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )

    avatar_url = models.URLField(max_length=500, blank=True, default="")

    # Territory — clients and operators can be territory-scoped (Phase 1.5).
    # String reference to avoid circular imports with the territories app.
    territory = models.ForeignKey(
        "territories.Territory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
    )

    # Onboarding — set true once a client finishes the signup wizard
    # (territory assigned + home address + preferences captured).
    onboarding_completed = models.BooleanField(default=False)
    preferred_services = models.JSONField(
        default=list, blank=True,
        help_text="Service types the client expects to use most, e.g. ['grocery'].",
    )

    # Django auth flags
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Updated by LastActiveMiddleware (throttled ~1/min per user). Powers
    # MOCK_CLIENT_DETAILS.lastActivity in the operator client list.
    last_active_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "accounts_user"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    # ── Convenience role flags ─────────────────────
    @property
    def is_client(self):
        return self.role == Role.CLIENT

    @property
    def is_operator(self):
        return self.role == Role.OPERATOR

    @property
    def is_driver(self):
        return self.role == Role.DRIVER

    @property
    def is_admin_role(self):
        # `is_admin` is reserved by Django's user system in some contexts
        return self.role == Role.ADMIN

    @property
    def is_suspended(self):
        return self.status == Status.SUSPENDED


class SavedAddress(models.Model):
    """Address book for clients — powers the Saved Addresses section in
    SettingsPage.jsx. CRUD endpoints land in M3; the model exists in M1
    so the data shape is locked before Stripe / requests start referencing
    it (e.g. defaulting a request's dropoff_location to the user's default).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="saved_addresses",
    )
    label = models.CharField(
        max_length=50,
        help_text="Free-form label: Home, Work, Parents, etc.",
    )
    address = models.CharField(max_length=500)
    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_savedaddress"
        ordering = ["-is_default", "-created_at"]
        constraints = [
            # At most one default per user. Postgres partial unique index
            # treats `is_default=False` rows as unconstrained.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="unique_default_address_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user.email} — {self.label}"

    def save(self, *args, **kwargs):
        # If this address is being set as default, unset any existing default
        # for the user atomically.
        if self.is_default:
            SavedAddress.objects.filter(
                user=self.user, is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)
