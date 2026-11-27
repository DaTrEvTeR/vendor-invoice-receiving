from django.apps import AppConfig


class ReceivingConfig(AppConfig):
    """Vendor invoice receiving: extraction, matching, review and stock."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "receiving"
