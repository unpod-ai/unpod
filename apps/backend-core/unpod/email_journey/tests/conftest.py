from datetime import timedelta

import pytest
from django.utils import timezone

from unpod.email_journey.models import OrgEmailJourney
from unpod.roles.models import Roles
from unpod.space.models import OrganizationMemberRoles, SpaceOrganization
from unpod.users.models import User


@pytest.fixture(autouse=True)
def journey_settings(settings):
    settings.EMAIL_JOURNEY_ENABLED = True
    settings.EMAIL_JOURNEY_PRODUCT_IDS = ["unpod.ai"]
    settings.EMAIL_JOURNEY_WORKFLOW_TUTORIAL_URL = "https://unpod.ai/tutorials/workflows"
    settings.EMAIL_JOURNEY_SALES_URL = "https://unpod.ai/contact-us"
    settings.EMAIL_FROM_ADDRESS = "hello@unpod.ai"
    settings.BASE_URL = "http://localhost:8000"
    settings.BASE_FRONTEND_URL = "http://localhost:3000"
    return settings


def make_user(email="owner@acme.com", first_name="Asha", **kwargs):
    return User.objects.create(
        username=email, email=email, first_name=first_name, is_active=True, **kwargs
    )


def make_org(owner, name="Acme", handle="acme"):
    org = SpaceOrganization.objects.create(
        name=name, domain_handle=handle, created_by=owner.id, updated_by=owner.id
    )
    role, _ = Roles.objects.get_or_create(role_code="owner", role_type="organization")
    OrganizationMemberRoles.objects.create(
        user=owner, organization=org, role=role, grant_by=owner.id
    )
    return org


@pytest.fixture
def owner(db):
    return make_user()


@pytest.fixture
def org(owner):
    return make_org(owner)


@pytest.fixture
def started_at():
    return timezone.now() - timedelta(days=100)


@pytest.fixture
def journey(org, owner, started_at):
    return OrgEmailJourney.objects.create(
        organization=org, recipient=owner, product_id="unpod.ai", started_at=started_at
    )


def day(journey, n, hours=1):
    """A moment on Day n of the journey (Day 1 == started_at)."""
    return journey.started_at + timedelta(days=n - 1, hours=hours)
