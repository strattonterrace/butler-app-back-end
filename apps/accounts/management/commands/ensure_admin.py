"""Management command — create the superuser admin account if it doesn't exist.

Runs in the Render build step so there is no need for shell access.
Safe to run on every deploy — skips silently if the account already exists.

Required env vars:
  ADMIN_EMAIL     e.g. admin@butlerapp.com
  ADMIN_PASSWORD  strong password
  ADMIN_FULL_NAME optional, defaults to "Butler Admin"
"""
import os

from django.core.management.base import BaseCommand

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Create superuser admin from env vars if it does not exist."

    def handle(self, *args, **options):
        email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("ADMIN_PASSWORD", "").strip()
        full_name = os.environ.get("ADMIN_FULL_NAME", "Butler Admin").strip()

        if not email or not password:
            self.stdout.write("ADMIN_EMAIL or ADMIN_PASSWORD not set — skipping admin creation.")
            return

        if User.objects.filter(email=email).exists():
            self.stdout.write(f"Admin {email} already exists — skipping.")
            return

        User.objects.create_superuser(email=email, password=password, full_name=full_name)
        self.stdout.write(self.style.SUCCESS(f"Admin account created: {email}"))
