import logging
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils import timezone

from unpod.common.helpers.service_helper import send_email
from unpod.common.utils import get_app_info
from unpod.email_journey import catalog
from unpod.email_journey.models import (
    FINAL_EMAIL_STATUSES,
    JourneyEmail,
    JourneyEmailStatus,
    JourneyStatus,
    OrgEmailJourney,
)

logger = logging.getLogger(__name__)

UNSUBSCRIBE_SALT = "email_journey.unsubscribe"
COMPLETED_CALL_STATUSES = ("completed", "success", "ANSWERED")


def journey_enabled():
    return bool(getattr(settings, "EMAIL_JOURNEY_ENABLED", False))


def _setting(name, default=""):
    return getattr(settings, name, default)


# --------------------------------------------------------------------------
# Start
# --------------------------------------------------------------------------
def start_journey(organization, user, product_id):
    """Start the journey for a freshly created org. Only the creating owner is
    ever a recipient; one journey per user; never for existing orgs (no backfill
    - this is only called from org create)."""
    if not journey_enabled():
        return None
    if not user or not user.is_active or not user.email:
        return None
    if product_id not in _setting("EMAIL_JOURNEY_PRODUCT_IDS", []):
        return None
    if organization.created_by != user.id:
        return None
    if OrgEmailJourney.objects.filter(recipient=user).exists():
        return None
    if OrgEmailJourney.objects.filter(organization=organization).exists():
        return None
    try:
        with transaction.atomic():
            journey = OrgEmailJourney.objects.create(
                organization=organization,
                recipient=user,
                product_id=product_id,
                started_at=timezone.now(),
            )
    except IntegrityError:
        return None
    # Day 1 is due immediately; send it once the org-create transaction commits.
    transaction.on_commit(lambda: _safe_process(journey.id))
    return journey


def _safe_process(journey_id, only_keys=None):
    try:
        process_journey(journey_id, only_keys=only_keys)
    except Exception:
        logger.exception("email_journey: processing journey %s failed", journey_id)


# --------------------------------------------------------------------------
# Live product state (R2)
# --------------------------------------------------------------------------
def org_state(organization):
    from unpod.core_components.models import Pilot
    from unpod.documents.models import Document
    from unpod.common.enum import DocumentStatus
    from unpod.metrics.models import CallLog

    agent = Pilot.objects.filter(owner=organization).order_by("-created").first()
    has_first_call = CallLog.objects.filter(
        organization=organization, call_status__in=COMPLETED_CALL_STATUSES
    ).exists()

    required_docs = set(_setting("EMAIL_JOURNEY_KYC_REQUIRED_DOCS", []))
    docs = Document.objects.filter(
        organization=organization, document_type__in=required_docs
    )
    first_doc = docs.order_by("uploaded_at").first()
    approved = set(
        docs.filter(status=DocumentStatus.approve.name).values_list(
            "document_type", flat=True
        )
    )
    return {
        "agent": agent,
        "has_agent": agent is not None,
        "has_first_call": has_first_call,
        "kyc_started": first_doc is not None,
        "kyc_started_at": first_doc.uploaded_at if first_doc else None,
        "kyc_completed": bool(required_docs) and required_docs <= approved,
    }


def evaluate_condition(spec, state, now):
    """Returns (SEND | SKIP | WAIT, reason)."""
    cond = spec.condition
    if cond == catalog.ALWAYS:
        return catalog.SEND, ""
    if cond == catalog.NO_AGENT:
        if state["has_agent"]:
            return catalog.SKIP, "agent_exists"
        return catalog.SEND, ""
    if cond == catalog.HAS_AGENT:
        if state["has_agent"]:
            return catalog.SEND, ""
        return catalog.WAIT, "waiting_for_agent"
    if cond == catalog.FIRST_CALL:
        if state["has_first_call"]:
            return catalog.SEND, ""
        return catalog.WAIT, "waiting_for_first_call"
    if cond == catalog.KYC_INCOMPLETE:
        if state["kyc_completed"]:
            return catalog.SKIP, "kyc_completed"
        if not state["kyc_started"]:
            return catalog.WAIT, "kyc_not_started"
        delay = timedelta(hours=_setting("EMAIL_JOURNEY_KYC_REMINDER_DELAY_HOURS", 24))
        if now < state["kyc_started_at"] + delay:
            return catalog.WAIT, "kyc_recently_started"
        return catalog.SEND, ""
    raise ValueError(f"Unknown condition {cond}")


def has_feature_access(journey, feature):
    """Single hook point for feature-gated emails (R10). Product decided v1 sends
    feature emails to everyone; plug a real entitlement check in here later."""
    return True


def promo_allowed(user):
    """R10 / TC26: promotional and product-update emails must not interrupt an
    unfinished onboarding journey unless Product/Growth approved it."""
    if _setting("EMAIL_JOURNEY_PROMO_APPROVED", False):
        return True
    return not OrgEmailJourney.objects.filter(
        recipient=user, status=JourneyStatus.active.name
    ).exists()


# --------------------------------------------------------------------------
# Unsubscribe (R14)
# --------------------------------------------------------------------------
def make_unsubscribe_token(journey):
    return signing.dumps({"j": journey.id}, salt=UNSUBSCRIBE_SALT)


def unsubscribe_url(journey):
    base = (_setting("BASE_URL", "") or "").rstrip("/")
    if not base:
        return ""
    return f"{base}/api/v1/email-journey/unsubscribe/{make_unsubscribe_token(journey)}/"


def unsubscribe_by_token(token):
    try:
        data = signing.loads(token, salt=UNSUBSCRIBE_SALT)
    except signing.BadSignature:
        return None
    journey = OrgEmailJourney.objects.filter(id=data.get("j")).first()
    if journey and not journey.unsubscribed_at:
        journey.unsubscribed_at = timezone.now()
        journey.save(update_fields=["unsubscribed_at", "modified"])
    return journey


# --------------------------------------------------------------------------
# Caps (R4)
# --------------------------------------------------------------------------
def _capped_keys():
    return [spec.key for spec in catalog.CATALOG if spec.capped]


def cap_reason(journey, now):
    sent = JourneyEmail.objects.filter(
        journey=journey,
        status=JourneyEmailStatus.sent.name,
        email_key__in=_capped_keys(),
    )
    if sent.filter(sent_at__gt=now - timedelta(hours=24)).count() >= _setting(
        "EMAIL_JOURNEY_MAX_PER_24H", 1
    ):
        return "cap_24h"
    if sent.filter(sent_at__gt=now - timedelta(days=7)).count() >= _setting(
        "EMAIL_JOURNEY_MAX_PER_7D", 3
    ):
        return "cap_7d"
    return None


# --------------------------------------------------------------------------
# Personalisation (R8, R9)
# --------------------------------------------------------------------------
def _time_since(started_at, now):
    days = (now - started_at).days
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day"
    return f"{days} days"


def build_context(journey, state, now):
    app = get_app_info(journey.product_id)
    app_url = (app.get("APP_URL") or "").rstrip("/")
    user = journey.recipient
    agent = state.get("agent")
    return {
        **app,
        "first_name": (user.first_name or "").strip() or "there",
        "time_since_signup": _time_since(journey.started_at, now),
        "sender_name": _setting("EMAIL_JOURNEY_SENDER_NAME"),
        "supported_languages": _setting("EMAIL_JOURNEY_SUPPORTED_LANGUAGES"),
        "agent_builder_name": _setting("EMAIL_JOURNEY_AGENT_BUILDER_NAME"),
        "auto_build_feature_name": _setting("EMAIL_JOURNEY_AUTO_BUILD_FEATURE_NAME"),
        "kyc_completion_time": _setting("EMAIL_JOURNEY_KYC_COMPLETION_TIME"),
        "welcome_credits": _setting("EMAIL_JOURNEY_WELCOME_CREDITS"),
        "create_agent_url": f"{app_url}/ai-studio/new/" if app_url else "",
        "agent_setup_url": (
            f"{app_url}/ai-studio/{agent.handle}/"
            if app_url and agent and agent.handle
            else ""
        ),
        "kyc_url": f"{app_url}{_setting('EMAIL_JOURNEY_KYC_PATH')}" if app_url else "",
        "sales_url": _setting("EMAIL_JOURNEY_SALES_URL"),
        "workflow_tutorial_url": _setting("EMAIL_JOURNEY_WORKFLOW_TUTORIAL_URL"),
        "playground_url": _setting("EMAIL_JOURNEY_PLAYGROUND_URL"),
        "unsubscribe_url": unsubscribe_url(journey),
    }


def missing_placeholders(spec, context):
    return [name for name in spec.required if not str(context.get(name) or "").strip()]


def render_email(spec, context):
    ctx = {**context, "cta_label": spec.cta_label}
    ctx["cta_url"] = context.get(spec.cta_placeholder, "") if spec.cta_placeholder else ""
    subject = Template("{% autoescape off %}" + spec.subject + "{% endautoescape %}")
    subject = subject.render(Context(ctx)).strip()
    body = render_to_string(spec.template, ctx)
    return subject, body


def _has_raw_placeholder(*texts):
    return any("{{" in text or "}}" in text for text in texts)


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------
def _due_at(journey, day):
    return journey.started_at + timedelta(days=day - 1)


def _record(journey, existing, spec, status, reason="", due_at=None, **extra):
    row = existing.get(spec.key)
    if row is None:
        row = JourneyEmail(journey=journey, email_key=spec.key)
    row.status = status
    row.reason = reason[:255]
    row.due_at = due_at
    for name, value in extra.items():
        setattr(row, name, value)
    row.save()
    existing[spec.key] = row
    log = logger.error if status == JourneyEmailStatus.error.name else logger.info
    log(
        "email_journey: journey=%s org=%s email=%s status=%s reason=%s",
        journey.id,
        journey.organization_id,
        spec.key,
        status,
        reason,
    )
    return row


def _is_final(row):
    if row is None:
        return False
    if row.status in FINAL_EMAIL_STATUSES:
        return True
    if row.status == JourneyEmailStatus.error.name:
        return row.attempts >= _setting("EMAIL_JOURNEY_MAX_SEND_ATTEMPTS", 3)
    return False


def _owner_ok(journey):
    from unpod.space.models import OrganizationMemberRoles

    user = journey.recipient
    if not user.is_active:
        return False
    return OrganizationMemberRoles.objects.filter(
        user=user,
        organization=journey.organization,
        role__role_code="owner",
        is_active=True,
    ).exists()


def _ordered_specs(only_keys=None):
    # Outcome email first (it bypasses caps), then the day schedule, then KYC.
    specs = sorted(
        catalog.CATALOG,
        key=lambda s: (0 if not s.capped else 1, s.day if s.day is not None else 10**6),
    )
    if only_keys:
        specs = [s for s in specs if s.key in only_keys]
    return specs


def process_journey(journey_id, now=None, only_keys=None):
    """Evaluate every pending email of one journey. Gate order: kill switch ->
    owner -> expiry window -> target action -> condition -> feature access ->
    unsubscribe -> hold -> caps -> placeholders -> send. Runs under a row lock so
    concurrent scheduler runs / signals can't double-send."""
    if not journey_enabled():
        return []
    now = now or timezone.now()
    with transaction.atomic():
        journey = (
            OrgEmailJourney.objects.select_for_update()
            .select_related("organization", "recipient")
            .filter(id=journey_id, status=JourneyStatus.active.name)
            .first()
        )
        if journey is None:
            return []
        existing = {row.email_key: row for row in journey.emails.all()}
        results = []

        if not _owner_ok(journey):
            journey.status = JourneyStatus.stopped.name
            journey.stop_reason = "recipient_not_active_owner"
            journey.save(update_fields=["status", "stop_reason", "modified"])
            return results

        max_age = timedelta(days=_setting("EMAIL_JOURNEY_MAX_AGE_DAYS", 63))
        past_horizon = now >= journey.started_at + max_age

        state = org_state(journey.organization)
        context = None

        for spec in _ordered_specs(only_keys):
            row = existing.get(spec.key)
            if _is_final(row):
                continue
            due_at = _due_at(journey, spec.day) if spec.kind == catalog.TIME else None

            if spec.kind == catalog.TIME:
                if now < due_at:
                    continue
                if now >= _due_at(journey, spec.expire_day):
                    _record(journey, existing, spec, JourneyEmailStatus.expired.name,
                            "send_window_passed", due_at)
                    results.append((spec.key, JourneyEmailStatus.expired.name))
                    continue
            elif past_horizon:
                _record(journey, existing, spec, JourneyEmailStatus.expired.name,
                        "journey_horizon_passed", due_at)
                results.append((spec.key, JourneyEmailStatus.expired.name))
                continue

            # R3: never continue the sequence once the target action (first call) is done.
            if (
                state["has_first_call"]
                and spec.condition != catalog.FIRST_CALL
                and not spec.survives_completion
            ):
                _record(journey, existing, spec, JourneyEmailStatus.skipped.name,
                        "target_action_done", due_at)
                results.append((spec.key, JourneyEmailStatus.skipped.name))
                continue

            decision, reason = evaluate_condition(spec, state, now)
            if decision == catalog.WAIT:
                continue
            if decision == catalog.SKIP:
                _record(journey, existing, spec, JourneyEmailStatus.skipped.name, reason, due_at)
                results.append((spec.key, JourneyEmailStatus.skipped.name))
                continue

            if spec.feature and not has_feature_access(journey, spec.feature):
                _record(journey, existing, spec, JourneyEmailStatus.skipped.name,
                        f"no_feature_access:{spec.feature}", due_at)
                results.append((spec.key, JourneyEmailStatus.skipped.name))
                continue

            if journey.unsubscribed_at:
                _record(journey, existing, spec, JourneyEmailStatus.unsubscribed.name,
                        "recipient_unsubscribed", due_at)
                results.append((spec.key, JourneyEmailStatus.unsubscribed.name))
                continue

            if context is None:
                context = build_context(journey, state, now)

            if any(not context.get(name) for name in spec.hold_until):
                # Held until Product supplies the value (e.g. workflow tutorial URL).
                logger.info("email_journey: journey=%s email=%s held (missing %s)",
                            journey.id, spec.key, ",".join(spec.hold_until))
                continue

            if spec.capped:
                capped = cap_reason(journey, now)
                if capped:
                    _record(journey, existing, spec, JourneyEmailStatus.capped.name, capped, due_at)
                    results.append((spec.key, JourneyEmailStatus.capped.name))
                    continue

            missing = missing_placeholders(spec, context)
            subject = body = ""
            if not missing:
                subject, body = render_email(spec, context)
                if _has_raw_placeholder(subject, body):
                    missing = ["raw_placeholder_in_output"]
            if missing:
                _record(journey, existing, spec, JourneyEmailStatus.error.name,
                        "unresolved_placeholder:" + ",".join(missing), due_at,
                        attempts=_setting("EMAIL_JOURNEY_MAX_SEND_ATTEMPTS", 3))
                results.append((spec.key, JourneyEmailStatus.error.name))
                continue

            attempts = (row.attempts if row else 0) + 1
            sent_count, error = send_email(
                subject,
                _setting("EMAIL_FROM_ADDRESS", None) or settings.DEFAULT_FROM_EMAIL,
                [journey.recipient.email],
                mail_body=body,
                mail_type="html",
                headers={"List-Unsubscribe": f"<{context['unsubscribe_url']}>"},
            )
            if sent_count:
                _record(journey, existing, spec, JourneyEmailStatus.sent.name, "", due_at,
                        attempts=attempts, sent_at=now)
                results.append((spec.key, JourneyEmailStatus.sent.name))
            else:
                _record(journey, existing, spec, JourneyEmailStatus.error.name,
                        f"send_failed:{error or 'unknown'}", due_at, attempts=attempts)
                results.append((spec.key, JourneyEmailStatus.error.name))

        if all(_is_final(existing.get(spec.key)) for spec in catalog.CATALOG):
            journey.status = JourneyStatus.completed.name
            journey.stop_reason = "all_emails_processed"
        journey.last_processed_at = now
        journey.save(update_fields=["status", "stop_reason", "last_processed_at", "modified"])
        return results


def process_due_journeys(now=None):
    if not journey_enabled():
        return "email journey disabled"
    ids = list(
        OrgEmailJourney.objects.filter(status=JourneyStatus.active.name).values_list(
            "id", flat=True
        )
    )
    processed = 0
    for journey_id in ids:
        try:
            process_journey(journey_id, now=now)
            processed += 1
        except Exception:
            logger.exception("email_journey: processing journey %s failed", journey_id)
    return f"processed {processed}/{len(ids)} journeys"


def on_call_logged(call_log):
    """First completed call -> congrats email right away (R5)."""
    if not journey_enabled() or not call_log.organization_id:
        return
    if call_log.call_status not in COMPLETED_CALL_STATUSES:
        return
    journey_id = (
        OrgEmailJourney.objects.filter(
            organization_id=call_log.organization_id, status=JourneyStatus.active.name
        )
        .values_list("id", flat=True)
        .first()
    )
    if journey_id:
        transaction.on_commit(lambda: _safe_process(journey_id))
