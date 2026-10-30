"""
Onboarding email catalog (PRD v1.0, schedule confirmed by Product).

Day N is due at ``started_at + (N - 1) days``. ``expire_day`` is the day after
which a still-unsent email is given up (logged as ``expired``), so a deferred or
waiting email can never arrive months late. Day 63 is intentionally absent
until Product supplies its copy.
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple

# Kinds
TIME = "time"
EVENT = "event"

# Condition results
SEND = "send"
SKIP = "skip"
WAIT = "wait"

# Conditions (evaluated against live org state at send time, see services.org_state)
ALWAYS = "always"
NO_AGENT = "no_agent"
HAS_AGENT = "has_agent"
FIRST_CALL = "first_call"
KYC_INCOMPLETE = "kyc_incomplete"


@dataclass(frozen=True)
class JourneyEmailSpec:
    key: str
    kind: str
    template: str
    subject: str
    condition: str
    cta_label: str
    cta_placeholder: Optional[str] = None
    day: Optional[int] = None
    expire_day: Optional[int] = None
    # Placeholders that must resolve to a non-empty value, else the email is
    # blocked and logged as an error (first_name always resolves: fallback "there").
    required: Tuple[str, ...] = field(default_factory=tuple)
    # Placeholders whose absence means "not ready yet" (hold, don't error).
    hold_until: Tuple[str, ...] = field(default_factory=tuple)
    # Feature-access hook key (services.has_feature_access).
    feature: Optional[str] = None
    # Onboarding/recovery emails count toward and obey the 24h / 7d caps.
    # Success/outcome emails (first call) do neither.
    capped: bool = True
    # Event emails that still apply after the first call (target action) is done.
    survives_completion: bool = False


BASE_REQUIRED = ("first_name", "sender_name", "unsubscribe_url")

CATALOG = (
    JourneyEmailSpec(
        key="welcome",
        kind=TIME,
        day=1,
        expire_day=3,
        template="emails/journey/welcome.html",
        subject="Welcome to {{APP_NAME}}, {{first_name}} - your 5 welcome credits are ready",
        condition=ALWAYS,
        cta_label="Create your agent",
        cta_placeholder="create_agent_url",
        required=BASE_REQUIRED + ("create_agent_url", "welcome_credits"),
    ),
    JourneyEmailSpec(
        key="templates",
        kind=TIME,
        day=3,
        expire_day=5,
        template="emails/journey/templates.html",
        subject="Not sure what to build? Start from a template",
        condition=NO_AGENT,
        cta_label="Create your first agent",
        cta_placeholder="create_agent_url",
        required=BASE_REQUIRED + ("create_agent_url", "agent_builder_name"),
    ),
    JourneyEmailSpec(
        key="personalise",
        kind=TIME,
        day=5,
        expire_day=14,
        template="emails/journey/personalise.html",
        subject="Make your agent sound like you",
        condition=HAS_AGENT,
        cta_label="Set up now",
        cta_placeholder="agent_setup_url",
        required=BASE_REQUIRED + ("agent_setup_url", "supported_languages"),
    ),
    JourneyEmailSpec(
        key="beyond_calls",
        kind=TIME,
        day=7,
        expire_day=14,
        template="emails/journey/beyond_calls.html",
        subject="Your agents can do more than calls",
        condition=ALWAYS,
        cta_label="Contact sales",
        cta_placeholder="sales_url",
        required=BASE_REQUIRED + ("sales_url",),
        feature="multichannel",
    ),
    JourneyEmailSpec(
        key="no_agent_14",
        kind=TIME,
        day=14,
        expire_day=21,
        template="emails/journey/no_agent_14.html",
        subject="Still haven't built your first agent?",
        condition=NO_AGENT,
        cta_label="Try Playground",
        cta_placeholder="playground_url",
        required=BASE_REQUIRED + ("playground_url", "auto_build_feature_name"),
    ),
    JourneyEmailSpec(
        key="workflows",
        kind=TIME,
        day=21,
        expire_day=42,
        template="emails/journey/workflows.html",
        subject="Automate your customer journeys with workflows",
        condition=ALWAYS,
        cta_label="Watch tutorial",
        cta_placeholder="workflow_tutorial_url",
        required=BASE_REQUIRED + ("workflow_tutorial_url",),
        hold_until=("workflow_tutorial_url",),
        feature="workflows",
    ),
    JourneyEmailSpec(
        key="no_agent_42",
        kind=TIME,
        day=42,
        expire_day=63,
        template="emails/journey/no_agent_42.html",
        subject="Need help building your first agent?",
        condition=NO_AGENT,
        cta_label="Try Playground",
        cta_placeholder="playground_url",
        required=BASE_REQUIRED + ("playground_url",),
    ),
    JourneyEmailSpec(
        key="first_call",
        kind=EVENT,
        template="emails/journey/first_call.html",
        subject="Congrats on your first call, {{first_name}}!",
        condition=FIRST_CALL,
        cta_label="Reply with feedback",
        required=BASE_REQUIRED,
        capped=False,
    ),
    JourneyEmailSpec(
        key="kyc_incomplete",
        kind=EVENT,
        template="emails/journey/kyc_incomplete.html",
        subject="Finish your verification to go live",
        condition=KYC_INCOMPLETE,
        cta_label="Finish KYC",
        cta_placeholder="kyc_url",
        required=BASE_REQUIRED + ("kyc_url", "kyc_completion_time"),
        survives_completion=True,
    ),
)

CATALOG_BY_KEY = {spec.key: spec for spec in CATALOG}
