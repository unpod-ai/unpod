import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from unpod.metrics.models import CallLog

logger = logging.getLogger(__name__)


@receiver(post_save, sender=CallLog, dispatch_uid="email_journey_call_logged")
def call_log_saved(sender, instance, **kwargs):
    # Best-effort: a journey problem must never break call logging.
    try:
        from unpod.email_journey.services import on_call_logged

        on_call_logged(instance)
    except Exception:
        logger.exception("email_journey: call log hook failed for %s", instance.pk)
