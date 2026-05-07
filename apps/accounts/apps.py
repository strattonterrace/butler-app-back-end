from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Accounts"

    def ready(self):
        # Wire post-save welcome-email signal (no-op in M1; real send in M3)
        from . import signals  # noqa: F401
