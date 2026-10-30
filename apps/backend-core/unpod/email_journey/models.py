from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel

from unpod.common.mixin import ChoiceEnum
from unpod.space.models import SpaceOrganization


class JourneyStatus(ChoiceEnum):
    active = "Active"
    completed = "Completed"
    stopped = "Stopped"


class JourneyEmailStatus(ChoiceEnum):
    sent = "Sent"
    skipped = "Skipped"
    capped = "Capped"
    unsubscribed = "Unsubscribed"
    error = "Error"
    expired = "Expired"


# Statuses after which an email is never evaluated again. "capped" is
# deferred (re-evaluated next run); "error" is final unless it was a
# transient send failure with attempts left (see services).
FINAL_EMAIL_STATUSES = (
    JourneyEmailStatus.sent.name,
    JourneyEmailStatus.skipped.name,
    JourneyEmailStatus.unsubscribed.name,
    JourneyEmailStatus.expired.name,
)


class OrgEmailJourney(TimeStampedModel):
    """One onboarding journey per organization, addressed to its owner only."""

    organization = models.OneToOneField(
        SpaceOrganization, on_delete=models.CASCADE, related_name="email_journey"
    )
    recipient = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_journey",
    )
    product_id = models.CharField(max_length=100, db_index=True)
    started_at = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=20,
        choices=JourneyStatus.choices(),
        default=JourneyStatus.active.name,
        db_index=True,
    )
    stop_reason = models.CharField(max_length=100, blank=True, default="")
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    last_processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "started_at"], name="ej_status_started_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id} - {self.recipient_id} - {self.status}"


class JourneyEmail(TimeStampedModel):
    """Send log: one row per (journey, email_key). The unique constraint is what
    makes a double scheduler run unable to send the same email twice."""

    journey = models.ForeignKey(
        OrgEmailJourney, on_delete=models.CASCADE, related_name="emails"
    )
    email_key = models.CharField(max_length=50)
    status = models.CharField(
        max_length=20, choices=JourneyEmailStatus.choices(), db_index=True
    )
    reason = models.CharField(max_length=255, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    due_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["journey", "email_key"], name="uq_journey_email_key"
            ),
        ]
        indexes = [
            models.Index(fields=["journey", "sent_at"], name="ej_email_sent_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.journey_id} - {self.email_key} - {self.status}"
