"""Custom user manager — email-based auth + role-scoped queryset.

Visibility primitives (`in_territory`, `clients()`, `drivers()`, `operators()`)
are defined on the queryset so they chain naturally:

    User.objects.clients().in_territory(t).filter(status="active")
"""
from django.contrib.auth.base_user import BaseUserManager
from django.db import models


class UserQuerySet(models.QuerySet):
    # ── Role filters ───────────────────────────
    def clients(self):
        return self.filter(role="client")

    def operators(self):
        return self.filter(role="operator")

    def drivers(self):
        return self.filter(role="driver")

    def admins(self):
        return self.filter(role="admin")

    def active(self):
        return self.filter(status="active")

    # ── Territory scoping ──────────────────────
    def in_territory(self, territory):
        """Restrict to a single territory. Fail closed on None."""
        if territory is None:
            return self.none()
        # Accept either a Territory instance or its UUID
        territory_id = getattr(territory, "id", territory)
        return self.filter(territory_id=territory_id)

    def for_operator(self, operator):
        """Users visible to a given operator (clients + drivers in their territory)."""
        if operator is None or operator.territory_id is None:
            return self.none()
        return self.in_territory(operator.territory_id)


class UserManager(BaseUserManager):
    """Custom manager — email is the unique identifier; queryset is role-aware."""

    use_in_migrations = True

    def get_queryset(self):
        return UserQuerySet(self.model, using=self._db)

    # ── Manager-level shortcuts (delegate to queryset) ──
    def clients(self):
        return self.get_queryset().clients()

    def operators(self):
        return self.get_queryset().operators()

    def drivers(self):
        return self.get_queryset().drivers()

    def admins(self):
        return self.get_queryset().admins()

    def in_territory(self, territory):
        return self.get_queryset().in_territory(territory)

    def for_operator(self, operator):
        return self.get_queryset().for_operator(operator)

    # ── User creation ──────────────────────────
    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", "client")
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "admin")
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, password, **extra_fields)
