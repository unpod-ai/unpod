"""Onboarding email journey - PRD v1.0 test cases (TCn in each docstring)."""

from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from unpod.common.enum import DocumentStatus
from unpod.core_components.models import Pilot
from unpod.documents.models import Document
from unpod.email_journey import catalog, services
from unpod.email_journey.admin import OrgEmailJourneyAdmin
from unpod.email_journey.cron import EmailJourneyCronJob
from unpod.email_journey.models import JourneyEmail, OrgEmailJourney
from unpod.email_journey.tests.conftest import day, make_org, make_user
from unpod.metrics.models import CallLog

pytestmark = pytest.mark.django_db

KYC_DOCS = ["GST_CERTIFICATE", "COMPANY_PAN", "INCORPORATION_CERTIFICATE", "ID_PROOF"]


def run(journey, n, hours=1):
    return services.process_journey(journey.id, now=day(journey, n, hours))


def row(journey, key):
    return JourneyEmail.objects.filter(journey=journey, email_key=key).first()


def status(journey, key):
    r = row(journey, key)
    return r.status if r else None


def make_agent(org, handle="sales-bot"):
    return Pilot.objects.create(owner=org, name="Sales Bot", handle=handle)


def make_call(org, call_status="completed", offset=0):
    start = timezone.now() + timedelta(minutes=offset)
    return CallLog.objects.create(
        organization=org,
        call_status=call_status,
        start_time=start,
        end_time=start + timedelta(minutes=2),
        source_number="100",
        destination_number="200",
    )


def make_doc(org, doc_type, doc_status=DocumentStatus.review.name, uploaded_at=None):
    # bulk_create: Document.save() insists on an uploaded file (S3 storage).
    (doc,) = Document.objects.bulk_create([
        Document(
            organization=org,
            module_type="organization",
            module_object_id=str(org.id),
            document_type=doc_type,
            status=doc_status,
        )
    ])
    if uploaded_at:
        Document.objects.filter(id=doc.id).update(uploaded_at=uploaded_at)
    return doc


def sent_subjects():
    return [m.subject for m in mail.outbox]


# ---------------------------------------------------------------------------
# Start (R1, R12, R15)
# ---------------------------------------------------------------------------
class TestStart:
    def test_start_creates_journey_and_sends_welcome_on_commit(
        self, org, owner, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            journey = services.start_journey(org, owner, "unpod.ai")
        assert journey.recipient == owner
        assert status(journey, "welcome") == "sent"
        assert len(mail.outbox) == 1

    def test_start_skips_inactive_user(self, org, owner):
        """TC1: a visitor who never completed signup gets nothing."""
        owner.is_active = False
        owner.save()
        assert services.start_journey(org, owner, "unpod.ai") is None
        assert not OrgEmailJourney.objects.exists()
        assert mail.outbox == []

    def test_start_skips_when_disabled(self, org, owner, settings):
        settings.EMAIL_JOURNEY_ENABLED = False
        assert services.start_journey(org, owner, "unpod.ai") is None
        assert not OrgEmailJourney.objects.exists()

    def test_disabled_flag_is_default(self):
        from config.settings import base

        assert base.EMAIL_JOURNEY_ENABLED is False

    def test_start_skips_other_product(self, org, owner):
        assert services.start_journey(org, owner, "unpod.dev") is None

    def test_start_skips_user_who_is_not_creator(self, org):
        """R12: invited members never get journey emails."""
        member = make_user("member@acme.com")
        assert services.start_journey(org, member, "unpod.ai") is None

    def test_one_journey_per_user(self, org, owner):
        assert services.start_journey(org, owner, "unpod.ai") is not None
        second_org = make_org(owner, name="Acme 2", handle="acme2")
        assert services.start_journey(second_org, owner, "unpod.ai") is None
        assert OrgEmailJourney.objects.count() == 1


class TestOrgCreateHook:
    payload = {"name": "Acme", "domain_handle": "acme", "account_type": "x", "color": "#AABBCC"}

    def _post(self, user, **headers):
        client = APIClient()
        client.force_authenticate(user)
        with mock.patch("unpod.space.views.createSpace"):
            return client.post("/api/v1/organization/", self.payload, format="json", **headers)

    def test_org_create_starts_journey(self, db, django_capture_on_commit_callbacks):
        user = make_user("founder@acme.com")
        with django_capture_on_commit_callbacks(execute=True):
            res = self._post(user, HTTP_PRODUCT_ID="unpod.ai")
        assert res.status_code == 200, res.content
        journey = OrgEmailJourney.objects.get(recipient=user)
        assert journey.organization.created_by == user.id
        assert status(journey, "welcome") == "sent"

    def test_org_create_never_fails_when_journey_errors(self, db):
        user = make_user("founder@acme.com")
        with mock.patch(
            "unpod.space.views.start_journey", side_effect=RuntimeError("boom")
        ):
            res = self._post(user, HTTP_PRODUCT_ID="unpod.ai")
        assert res.status_code == 200
        assert not OrgEmailJourney.objects.exists()


# ---------------------------------------------------------------------------
# Time-based emails (R6, R7, R3)
# ---------------------------------------------------------------------------
class TestSchedule:
    def test_day1_welcome_sent_with_name_credits_cta_and_unsubscribe(self, journey):
        """TC2"""
        run(journey, 1)
        assert status(journey, "welcome") == "sent"
        msg = mail.outbox[0]
        assert msg.to == ["owner@acme.com"]
        assert "Asha" in msg.subject
        assert "5 welcome credits" in msg.body
        assert "Create your agent" in msg.body
        assert "http://localhost:3000/ai-studio/new/" in msg.body
        assert "/api/v1/email-journey/unsubscribe/" in msg.body
        assert msg.extra_headers["List-Unsubscribe"].startswith("<http://localhost:8000/")

    def test_nothing_sent_before_due(self, journey):
        services.process_journey(journey.id, now=journey.started_at - timedelta(hours=1))
        assert mail.outbox == []
        assert not JourneyEmail.objects.exists()

    def test_day3_sent_without_agent(self, journey):
        """TC3"""
        run(journey, 1)
        run(journey, 3)
        assert status(journey, "templates") == "sent"
        assert "http://localhost:3000/ai-studio/new/" in mail.outbox[-1].body

    def test_day3_skipped_when_agent_exists(self, journey, org):
        """TC4: skip is logged with a reason."""
        run(journey, 1)
        make_agent(org)
        run(journey, 3)
        r = row(journey, "templates")
        assert (r.status, r.reason) == ("skipped", "agent_exists")
        assert len(mail.outbox) == 1

    def test_day5_waits_for_agent_then_links_to_it(self, journey, org):
        """TC5 / TC6: no agent -> not sent (waits); agent later -> sent with setup link."""
        run(journey, 1)
        run(journey, 3)
        run(journey, 5)
        assert row(journey, "personalise") is None
        make_agent(org, handle="my-agent")
        run(journey, 6)
        assert status(journey, "personalise") == "sent"
        body = mail.outbox[-1].body
        assert "http://localhost:3000/ai-studio/my-agent/" in body
        for text in ("Custom variables", "First message", "Knowledge base"):
            assert text in body

    def test_day5_expires_at_day14_without_agent(self, journey):
        """TC6"""
        run(journey, 14)
        r = row(journey, "personalise")
        assert (r.status, r.reason) == ("expired", "send_window_passed")
        assert not any("sound like you" in s for s in sent_subjects())

    def test_day7_beyond_calls_with_sales_url(self, journey):
        """TC7"""
        run(journey, 7)
        assert status(journey, "beyond_calls") == "sent"
        body = mail.outbox[-1].body
        for text in ("Chat", "WhatsApp", "Email", "Workflows", "https://unpod.ai/contact-us"):
            assert text in body

    def test_day14_sent_without_agent_says_two_weeks(self, journey):
        """TC8"""
        run(journey, 14)
        assert status(journey, "no_agent_14") == "sent"
        body = mail.outbox[-1].body
        assert "two weeks ago" in body
        assert "Try Playground" in body

    def test_day14_skipped_when_agent_exists(self, journey, org):
        """TC9"""
        make_agent(org)
        run(journey, 14)
        assert status(journey, "no_agent_14") == "skipped"

    def test_day21_workflows_with_tutorial_url(self, journey):
        """TC10"""
        run(journey, 21)
        assert status(journey, "workflows") == "sent"
        assert "https://unpod.ai/tutorials/workflows" in mail.outbox[-1].body

    def test_day21_held_while_tutorial_url_empty(self, journey, settings):
        settings.EMAIL_JOURNEY_WORKFLOW_TUTORIAL_URL = ""
        run(journey, 21)
        assert row(journey, "workflows") is None
        settings.EMAIL_JOURNEY_WORKFLOW_TUTORIAL_URL = "https://unpod.ai/t"
        run(journey, 23)
        assert status(journey, "workflows") == "sent"

    def test_day21_skipped_without_feature_access(self, journey):
        """TC11: feature-access hook point."""
        with mock.patch.object(services, "has_feature_access", return_value=False):
            run(journey, 21)
        r = row(journey, "workflows")
        assert (r.status, r.reason) == ("skipped", "no_feature_access:workflows")

    def test_day42_sent_without_agent(self, journey):
        """TC12"""
        run(journey, 42)
        assert status(journey, "no_agent_42") == "sent"
        assert "Need help building your first agent?" in sent_subjects()

    def test_day42_skipped_when_agent_exists(self, journey, org):
        """TC13"""
        make_agent(org)
        run(journey, 42)
        assert status(journey, "no_agent_42") == "skipped"

    def test_day63_not_in_catalog(self):
        assert all(spec.day != 63 for spec in catalog.CATALOG)
        assert [s.day for s in catalog.CATALOG if s.kind == catalog.TIME] == [1, 3, 5, 7, 14, 21, 42]

    def test_sequence_stops_after_first_call(self, journey, org):
        """R3: once the target action is done, the time-based sequence stops."""
        run(journey, 1)
        make_call(org)
        run(journey, 3)
        assert status(journey, "first_call") == "sent"
        r = row(journey, "templates")
        assert (r.status, r.reason) == ("skipped", "target_action_done")


# ---------------------------------------------------------------------------
# Event emails (R5, R7)
# ---------------------------------------------------------------------------
class TestEvents:
    @pytest.fixture
    def live_journey(self, journey):
        journey.started_at = timezone.now() - timedelta(minutes=5)
        journey.save()
        return journey

    def test_first_call_sent_once_immediately_via_signal(
        self, live_journey, org, django_capture_on_commit_callbacks
    ):
        """TC14 / TC15"""
        with django_capture_on_commit_callbacks(execute=True):
            make_call(org)
        assert status(live_journey, "first_call") == "sent"
        congrats = [s for s in sent_subjects() if s.startswith("Congrats")]
        assert congrats == ["Congrats on your first call, Asha!"]
        with django_capture_on_commit_callbacks(execute=True):
            make_call(org, offset=10)
        assert [s for s in sent_subjects() if s.startswith("Congrats")] == congrats

    def test_first_call_bypasses_24h_cap(
        self, live_journey, org, django_capture_on_commit_callbacks
    ):
        """TC16"""
        services.process_journey(live_journey.id)
        assert status(live_journey, "welcome") == "sent"
        with django_capture_on_commit_callbacks(execute=True):
            make_call(org)
        assert status(live_journey, "first_call") == "sent"
        assert len(mail.outbox) == 2

    def test_failed_call_does_not_trigger(
        self, live_journey, org, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            make_call(org, call_status="failed")
        assert row(live_journey, "first_call") is None

    def test_call_hook_never_breaks_call_logging(self, live_journey, org):
        with mock.patch.object(services, "on_call_logged", side_effect=RuntimeError("x")):
            make_call(org)
        assert CallLog.objects.count() == 1

    def test_kyc_incomplete_reminder(self, journey, org):
        """TC17: started, not finished -> reminder with link and completion time."""
        run(journey, 1)
        make_doc(org, "GST_CERTIFICATE", uploaded_at=day(journey, 1, hours=2))
        run(journey, 2, hours=1)  # less than 24h after upload: wait
        assert row(journey, "kyc_incomplete") is None
        run(journey, 2, hours=3)
        assert status(journey, "kyc_incomplete") == "sent"
        body = mail.outbox[-1].body
        assert "http://localhost:3000/org/settings/" in body
        assert "a few minutes" in body

    def test_kyc_not_started_waits(self, journey):
        run(journey, 10)
        assert row(journey, "kyc_incomplete") is None

    def test_kyc_completed_is_skipped(self, journey, org):
        """TC18"""
        for doc_type in KYC_DOCS:
            make_doc(org, doc_type, DocumentStatus.approve.name, uploaded_at=day(journey, 1))
        run(journey, 3)
        r = row(journey, "kyc_incomplete")
        assert (r.status, r.reason) == ("skipped", "kyc_completed")

    def test_kyc_three_of_four_approved_is_incomplete(self, journey, org):
        for doc_type in KYC_DOCS[:3]:
            make_doc(org, doc_type, DocumentStatus.approve.name, uploaded_at=day(journey, 1))
        make_doc(org, KYC_DOCS[3], DocumentStatus.reject.name, uploaded_at=day(journey, 1))
        state = services.org_state(org)
        assert state["kyc_started"] and not state["kyc_completed"]


# ---------------------------------------------------------------------------
# Caps (R4)
# ---------------------------------------------------------------------------
class TestCaps:
    def test_24h_cap_defers_second_email(self, journey, org):
        """TC19: two due on the same day -> one sent, the other capped and sent later."""
        run(journey, 1)
        make_doc(org, "GST_CERTIFICATE", uploaded_at=day(journey, 1, hours=2))
        run(journey, 3)  # templates + KYC reminder both eligible
        assert status(journey, "templates") == "sent"
        r = row(journey, "kyc_incomplete")
        assert (r.status, r.reason) == ("capped", "cap_24h")
        assert len(mail.outbox) == 2
        run(journey, 4, hours=2)
        assert status(journey, "kyc_incomplete") == "sent"
        assert len(mail.outbox) == 3

    def test_7day_cap(self, journey, org):
        """TC20: 4 eligible within 7 days -> max 3 sent in the rolling window."""
        run(journey, 1)
        run(journey, 3)
        make_agent(org)
        run(journey, 5)
        assert len(mail.outbox) == 3
        run(journey, 7)
        r = row(journey, "beyond_calls")
        assert (r.status, r.reason) == ("capped", "cap_7d")
        assert len(mail.outbox) == 3
        run(journey, 8, hours=2)
        assert status(journey, "beyond_calls") == "sent"

    def test_capped_email_expires_if_window_passes(self, journey):
        with mock.patch.object(services, "cap_reason", return_value="cap_24h"):
            run(journey, 3)
        assert status(journey, "templates") == "capped"
        run(journey, 5)
        assert status(journey, "templates") == "expired"


# ---------------------------------------------------------------------------
# Placeholders and links (R8, R9)
# ---------------------------------------------------------------------------
class TestPlaceholders:
    def test_first_name_falls_back_to_there(self, journey, owner):
        """TC21"""
        owner.first_name = ""
        owner.save()
        run(journey, 1)
        msg = mail.outbox[0]
        assert "Hi there," in msg.body
        assert "there" in msg.subject
        assert "{{" not in msg.body and "first_name" not in msg.body

    def test_unresolved_placeholder_blocks_send(self, journey, settings, caplog):
        """TC22"""
        settings.EMAIL_JOURNEY_SALES_URL = ""
        run(journey, 7)
        r = row(journey, "beyond_calls")
        assert r.status == "error"
        assert r.reason == "unresolved_placeholder:sales_url"
        assert mail.outbox == []
        assert any(rec.levelname == "ERROR" and "beyond_calls" in rec.getMessage() for rec in caplog.records)
        # not retried
        run(journey, 8)
        assert mail.outbox == []

    def test_raw_placeholder_in_value_blocks_send(self, journey, settings):
        settings.EMAIL_JOURNEY_SENDER_NAME = "{{sender}}"
        run(journey, 1)
        assert row(journey, "welcome").reason == "unresolved_placeholder:raw_placeholder_in_output"
        assert mail.outbox == []

    def test_missing_unsubscribe_base_url_blocks_send(self, journey, settings):
        settings.BASE_URL = ""
        run(journey, 1)
        assert row(journey, "welcome").reason == "unresolved_placeholder:unsubscribe_url"

    def test_deep_links_point_into_own_workspace(self, journey, org):
        """TC23"""
        make_agent(org, handle="acme-agent")
        ctx = services.build_context(journey, services.org_state(org), timezone.now())
        assert ctx["create_agent_url"] == "http://localhost:3000/ai-studio/new/"
        assert ctx["agent_setup_url"] == "http://localhost:3000/ai-studio/acme-agent/"
        assert ctx["kyc_url"] == "http://localhost:3000/org/settings/"

    def test_all_templates_render_without_raw_placeholders(self, journey, org):
        make_agent(org)
        ctx = services.build_context(journey, services.org_state(org), timezone.now())
        for spec in catalog.CATALOG:
            assert services.missing_placeholders(spec, ctx) == [], spec.key
            subject, body = services.render_email(spec, ctx)
            assert "{{" not in subject + body, spec.key
            for typo in ("custoemr", "Play ground", "immidately"):
                assert typo not in subject + body, spec.key


# ---------------------------------------------------------------------------
# Idempotency, unsubscribe, promo, log (R10, R11, R13, R14)
# ---------------------------------------------------------------------------
class TestLogAndSuppression:
    def test_scheduler_twice_sends_once(self, journey):
        """TC24"""
        run(journey, 1)
        run(journey, 1)
        services.process_due_journeys(now=day(journey, 1))
        assert len(mail.outbox) == 1

    def test_unique_constraint_on_journey_email_key(self, journey):
        JourneyEmail.objects.create(journey=journey, email_key="welcome", status="sent")
        with pytest.raises(IntegrityError), transaction.atomic():
            JourneyEmail.objects.create(journey=journey, email_key="welcome", status="sent")

    def test_unsubscribed_user_gets_nothing_and_is_logged(self, journey):
        """TC25 via the link carried in every email."""
        run(journey, 1)
        token = services.make_unsubscribe_token(journey)
        res = APIClient().get(f"/api/v1/email-journey/unsubscribe/{token}/")
        assert res.status_code == 200
        journey.refresh_from_db()
        assert journey.unsubscribed_at is not None
        run(journey, 3)
        r = row(journey, "templates")
        assert (r.status, r.reason) == ("unsubscribed", "recipient_unsubscribed")
        assert len(mail.outbox) == 1

    def test_unsubscribe_bad_token(self, db):
        res = APIClient().get("/api/v1/email-journey/unsubscribe/not-a-token/")
        assert res.status_code == 400

    def test_promo_blocked_during_onboarding(self, journey, owner, settings):
        """TC26"""
        assert services.promo_allowed(owner) is False
        settings.EMAIL_JOURNEY_PROMO_APPROVED = True
        assert services.promo_allowed(owner) is True
        settings.EMAIL_JOURNEY_PROMO_APPROVED = False
        journey.status = "completed"
        journey.save()
        assert services.promo_allowed(owner) is True

    def test_full_journey_send_log(self, journey, org):
        """TC27: every send/skip has key, status, reason and timestamps; journey completes."""
        for n in range(1, 65):
            run(journey, n)
            if n == 4:
                make_agent(org)
        journey.refresh_from_db()
        assert journey.status == "completed"
        rows = {r.email_key: r for r in journey.emails.all()}
        assert set(rows) == set(catalog.CATALOG_BY_KEY)
        expected = {
            "welcome": "sent",
            "templates": "sent",
            "personalise": "sent",
            "beyond_calls": "sent",
            "no_agent_14": "skipped",
            "workflows": "sent",
            "no_agent_42": "skipped",
            "first_call": "expired",
            "kyc_incomplete": "expired",
        }
        assert {k: r.status for k, r in rows.items()} == expected
        for r in rows.values():
            assert r.created and r.modified
            if r.status == "sent":
                assert r.sent_at is not None
            else:
                assert r.reason

    def test_owner_no_longer_active_stops_journey(self, journey, owner):
        owner.is_active = False
        owner.save()
        run(journey, 1)
        journey.refresh_from_db()
        assert (journey.status, journey.stop_reason) == ("stopped", "recipient_not_active_owner")
        assert mail.outbox == []

    def test_send_failure_is_retried_then_final(self, journey, settings):
        settings.EMAIL_JOURNEY_MAX_SEND_ATTEMPTS = 2
        with mock.patch.object(services, "send_email", return_value=(0, "smtp down")):
            run(journey, 1)
            assert (status(journey, "welcome"), row(journey, "welcome").attempts) == ("error", 1)
            run(journey, 1, hours=2)
            assert row(journey, "welcome").attempts == 2
            run(journey, 1, hours=3)
            assert row(journey, "welcome").attempts == 2
        assert row(journey, "welcome").reason == "send_failed:smtp down"

    def test_kill_switch_stops_processing(self, journey, settings):
        settings.EMAIL_JOURNEY_ENABLED = False
        assert run(journey, 1) == []
        assert services.process_due_journeys() == "email journey disabled"
        assert mail.outbox == []

    def test_cron_job_processes_active_journeys(self, journey):
        journey.started_at = timezone.now() - timedelta(hours=1)
        journey.save()
        assert EmailJourneyCronJob().do() == "processed 1/1 journeys"
        assert status(journey, "welcome") == "sent"

    def test_cron_registered(self, settings):
        assert "unpod.email_journey.cron.EmailJourneyCronJob" in settings.CRON_CLASSES

    def test_admin_is_read_only(self, rf):
        from django.contrib.admin.sites import site

        model_admin = OrgEmailJourneyAdmin(OrgEmailJourney, site)
        request = rf.get("/")
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request)
        assert not model_admin.has_delete_permission(request)
