from django.apps import AppConfig


class EmailJourneyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "unpod.email_journey"
    verbose_name = "Email Journey"

    def ready(self):
        from unpod.email_journey import signals  # noqa: F401
