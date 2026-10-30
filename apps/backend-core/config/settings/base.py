"""
Base settings to build other settings files upon.
"""

# flake8: noqa
import os
import datetime
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    message="app_settings.USERNAME_REQUIRED is deprecated",
    category=UserWarning,
)

warnings.filterwarnings(
    "ignore",
    message="app_settings.EMAIL_REQUIRED is deprecated",
    category=UserWarning,
)

from django.conf import settings

import environ

ROOT_DIR = Path(__file__).resolve(strict=True).parent.parent.parent
# unpod/
APPS_DIR = ROOT_DIR / "unpod"
MONOREPO_ROOT = ROOT_DIR.parent.parent  # project root (apps/backend-core/ → apps/ → root)
env = environ.Env()

# Determine which .env file to load based on DJANGO_SETTINGS_MODULE
READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=True)
if READ_DOT_ENV_FILE:
    # Determine environment from DJANGO_SETTINGS_MODULE
    settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")

    if "qa" in settings_module:
        env_file = MONOREPO_ROOT / ".env.qa"
    elif "production" in settings_module:
        env_file = MONOREPO_ROOT / ".env.production"
    elif "local" in settings_module:
        env_file = MONOREPO_ROOT / ".env"
    else:
        env_file = MONOREPO_ROOT / ".env"

    # Load the appropriate .env file if it exists
    if env_file.exists():
        env.read_env(str(env_file))
        print(f"Loaded environment from: {env_file}")
    else:
        # Fallback to service-local .env for backwards compatibility
        local_env_file = ROOT_DIR / ".env"
        if local_env_file.exists():
            env.read_env(str(local_env_file))
            print(f"Warning: {env_file} not found, falling back to: {local_env_file}")
        else:
            print(f"Warning: {env_file} not found, using system environment variables")

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = env.bool("DJANGO_DEBUG", False)
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY", default="django-insecure-base-key-override-in-production"
)
ENABLE_DEBUG_TOOLBAR = env.bool("ENABLE_DEBUG_TOOLBAR", default=False)
# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# though not all of them may be available with every OS.
# In Windows, this must be set to your system time zone.
TIME_ZONE = "UTC"
# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = "en-us"
# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
SITE_ID = 1
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True
# https://docs.djangoproject.com/en/dev/ref/settings/#locale-paths
LOCALE_PATHS = [str(ROOT_DIR / "locale")]

# Tax Settings
# Default tax rate (18%)
DEFAULT_TAX_RATE = env.float("DEFAULT_TAX_RATE", default=0.18)

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres:///unpod",  # Changed from postgres to sqlite for base compatibility
    ),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
# https://docs.djangoproject.com/en/stable/ref/settings/#std:setting-DEFAULT_AUTO_FIELD
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = "config.urls"
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.application"

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # "django.contrib.humanize", # Handy template tags
    "django.contrib.admin",
    "django.forms",
]
# add provides
THIRD_PARTY_APPS = [
    "crispy_forms",
    "crispy_bootstrap5",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "allauth.socialaccount.providers.google",
    "dj_rest_auth",
    "import_export",
    "cloudinary",
    "django_cron",
]

LOCAL_APPS = [
    "unpod.users",
    "unpod.apiV1.apps.Apiv1Config",
    "unpod.space",
    "unpod.roles",
    "unpod.thread",
    "unpod.core_components",
    "unpod.notification",
    "unpod.knowledge_base",
    "unpod.documents",
    "unpod.metrics",
    "unpod.dynamic_forms",
    "unpod.email_journey",
    # Your stuff: custom apps go here
]
# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIGRATIONS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#migration-modules
MIGRATION_MODULES = {"sites": "unpod.contrib.sites.migrations"}

# AUTHENTICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#authentication-backends
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-user-model
AUTH_USER_MODEL = "users.User"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-redirect-url
LOGIN_REDIRECT_URL = "users:redirect"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-url
LOGIN_URL = "account_login"

ADMIN_LOGIN_TEMPLATE = "admin/admin-login.html"

SESSION_COOKIE_AGE = 1 * 12 * 60 * 60  # 12 Hours

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = [
    # https://docs.djangoproject.com/en/dev/topics/auth/passwords/#using-argon2-with-django
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",  # Required by django-allauth 0.63.0+
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.common.BrokenLinkEmailsMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Custom Middlewares
    "unpod.common.middleware.CheckHeaderMiddleware",
    "unpod.common.middleware.ChecksumValidationMiddleware",  # HMAC-SHA256 checksum validation
    "unpod.users.middleware.BlackListTokenCheckerMiddleware",
]

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(ROOT_DIR / "staticfiles")
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(APPS_DIR / "static")]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = str(APPS_DIR / "media")
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "/media/"

# STORAGES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/5.2/ref/settings/#storages
STORAGES = {
    "default": {
        "BACKEND": "unpod.common.storage_backends.PrivateMediaStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # https://docs.djangoproject.com/en/dev/ref/settings/#dirs
        "DIRS": [str(APPS_DIR / "templates")],
        # https://docs.djangoproject.com/en/dev/ref/settings/#app-dirs
        "APP_DIRS": True,
        "OPTIONS": {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-context-processors
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                "unpod.users.context_processors.allauth_settings",
            ],
        },
    }
]

# https://docs.djangoproject.com/en/dev/ref/settings/#form-renderer
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs
CRISPY_TEMPLATE_PACK = "bootstrap5"
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-httponly
SESSION_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-httponly
CSRF_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-browser-xss-filter
SECURE_BROWSER_XSS_FILTER = True
# https://docs.djangoproject.com/en/dev/ref/settings/#x-frame-options
X_FRAME_OPTIONS = "DENY"

# CHECKSUM VALIDATION
# ------------------------------------------------------------------------------
# HMAC-SHA256 checksum validation for API requests and responses
# Provides data integrity validation and replay attack prevention
# SECURITY: Credentials loaded from environment variables
# Generate secret with: openssl rand -base64 32
ENABLE_CHECKSUM = env.bool("ENABLE_CHECKSUM", default=False)
CHECKSUM_SECRET = env("CHECKSUM_SECRET", default="")
CHECKSUM_MAX_TIMESTAMP_AGE = env.int(
    "CHECKSUM_MAX_TIMESTAMP_AGE", default=300
)  # 5 minutes
# If True, only validate browser/web requests (skip mobile apps)
# If False, validate ALL requests including mobile apps
CHECKSUM_BROWSER_ONLY = env.bool("CHECKSUM_BROWSER_ONLY", default=True)
# If True, requests WITHOUT checksum headers will be REJECTED
# If False, requests without checksums are allowed (graceful degradation)
CHECKSUM_REQUIRED = env.bool("CHECKSUM_REQUIRED", default=False)

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL.
ADMIN_URL = "unpod-admin/"
# https://docs.djangoproject.com/en/dev/ref/settings/#admins
ADMINS = []
# https://docs.djangoproject.com/en/dev/ref/settings/#managers
MANAGERS = ADMINS

# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s "
            "%(process)d %(thread)d %(message)s"
        }
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        }
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}

# Store Service Configuration (now served via API_SERVICE_URL)

# django-allauth
# ------------------------------------------------------------------------------

ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
# https://docs.allauth.org/en/latest/account/configuration.html
# New django-allauth 0.60+ configuration format
ACCOUNT_LOGIN_METHODS = {"username"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# https://django-allauth.readthedocs.io/en/latest/configuration.html
ACCOUNT_ADAPTER = "unpod.users.adapters.AccountAdapter"
# https://django-allauth.readthedocs.io/en/latest/forms.html
ACCOUNT_FORMS = {"signup": "unpod.users.forms.UserSignupForm"}
# https://django-allauth.readthedocs.io/en/latest/configuration.html
SOCIALACCOUNT_ADAPTER = "unpod.users.adapters.SocialAccountAdapter"
# https://django-allauth.readthedocs.io/en/latest/forms.html
SOCIALACCOUNT_FORMS = {"signup": "unpod.users.forms.UserSocialSignupForm"}

# django-rest-framework
# -------------------------------------------------------------------------------
# django-rest-framework - https://www.django-rest-framework.org/api-guide/settings/
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # Dual authentication during Django 4.2 migration
        # Supports both old JWT and new simplejwt tokens
        "unpod.common.authentication.DualJWTAuthentication",
        # Old authentication (will be removed after migration):
        # "unpod.common.authentication.UnpodJSONWebTokenAuthentication",
        # 'rest_framework.authentication.SessionAuthentication',
        # 'rest_framework.authentication.BasicAuthentication',
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # 'EXCEPTION_HANDLER': 'unpod.common.exception.UnpodExceptionHandler',
}

# JWT settings
JWT_AUTH = {
    "JWT_ENCODE_HANDLER": "rest_framework_jwt.utils.jwt_encode_handler",
    "JWT_DECODE_HANDLER": "rest_framework_jwt.utils.jwt_decode_handler",
    "JWT_PAYLOAD_HANDLER": "rest_framework_jwt.utils.jwt_payload_handler",
    "JWT_PAYLOAD_GET_USER_ID_HANDLER": "rest_framework_jwt.utils.jwt_get_user_id_from_payload_handler",
    "JWT_RESPONSE_PAYLOAD_HANDLER": "rest_framework_jwt.utils.jwt_response_payload_handler",
    "JWT_GET_USER_SECRET_KEY": None,
    "JWT_PUBLIC_KEY": None,
    "JWT_PRIVATE_KEY": None,
    "JWT_ALGORITHM": "HS256",
    "JWT_VERIFY": True,
    "JWT_VERIFY_EXPIRATION": True,
    "JWT_LEEWAY": 0,
    "JWT_EXPIRATION_DELTA": datetime.timedelta(days=180),
    "JWT_AUDIENCE": None,
    "JWT_ISSUER": None,
    "JWT_ALLOW_REFRESH": False,
    "JWT_REFRESH_EXPIRATION_DELTA": datetime.timedelta(days=7),
    "JWT_AUTH_HEADER_PREFIX": "JWT",
    "JWT_AUTH_COOKIE": None,
}

# Simple JWT settings (Django 4.x compatible)
# Configuration matches old JWT_AUTH behavior for seamless migration
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": datetime.timedelta(days=180),  # Match JWT_EXPIRATION_DELTA
    "REFRESH_TOKEN_LIFETIME": datetime.timedelta(
        days=7
    ),  # Match JWT_REFRESH_EXPIRATION_DELTA
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",  # Match JWT_ALGORITHM
    "SIGNING_KEY": SECRET_KEY,
    "VERIFYING_KEY": None,
    "AUDIENCE": None,
    "ISSUER": None,
    "AUTH_HEADER_TYPES": ("JWT",),  # Match JWT_AUTH_HEADER_PREFIX
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "JTI_CLAIM": "jti",
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": datetime.timedelta(days=180),
    "SLIDING_TOKEN_REFRESH_LIFETIME": datetime.timedelta(days=7),
}

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4200",
    "http://127.0.0.1:4200",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3002",
    "https://qa1.unpod.tv",
    "https://qa2.unpod.tv",
    "https://qa3.unpod.tv",
    "https://unpod.ai",
    "https://unpod.tv",
    "https://www.unpod.tv",
    "https://www.unpod.ai",
    "https://unpod.dev",
    "https://www.unpod.dev",
    "https://up-call.web.app",
]

from corsheaders.defaults import default_headers

CORS_ALLOW_HEADERS = default_headers + (
    "Org-Handle",
    "AppType",
    "Product-Id",
    "UP-Checksum",  # Allow checksum validation headers
    "UP-Timestamp",  # Allow timestamp headers for replay attack prevention
)

# Expose checksum headers in responses so frontend can read them
CORS_EXPOSE_HEADERS = [
    "UP-Checksum",
    "UP-Timestamp",
]

# django-cors-headers - https://github.com/adamchainz/django-cors-headers#setup
# CORS_URLS_REGEX = r"^/api/.*$"

# Your stuff...
# ------------------------------------------------------------------------------
CRON_CLASSES = [
    "unpod.thread.cron.CreateCronPost",
    "unpod.core_components.cron.EventTriggerCron",
    "unpod.email_journey.cron.EmailJourneyCronJob",
]

# Onboarding email journey (UP-61)
# ------------------------------------------------------------------------------
# Kill switch: sends emails to real users, so it stays OFF unless enabled per env.
EMAIL_JOURNEY_ENABLED = env.bool("EMAIL_JOURNEY_ENABLED", default=False)
EMAIL_JOURNEY_PRODUCT_IDS = env.list("EMAIL_JOURNEY_PRODUCT_IDS", default=["unpod.ai"])
EMAIL_JOURNEY_MAX_PER_24H = env.int("EMAIL_JOURNEY_MAX_PER_24H", default=1)
EMAIL_JOURNEY_MAX_PER_7D = env.int("EMAIL_JOURNEY_MAX_PER_7D", default=3)
EMAIL_JOURNEY_MAX_SEND_ATTEMPTS = env.int("EMAIL_JOURNEY_MAX_SEND_ATTEMPTS", default=3)
EMAIL_JOURNEY_MAX_AGE_DAYS = env.int("EMAIL_JOURNEY_MAX_AGE_DAYS", default=63)
EMAIL_JOURNEY_KYC_REMINDER_DELAY_HOURS = env.int(
    "EMAIL_JOURNEY_KYC_REMINDER_DELAY_HOURS", default=24
)
EMAIL_JOURNEY_KYC_REQUIRED_DOCS = env.list(
    "EMAIL_JOURNEY_KYC_REQUIRED_DOCS",
    default=["GST_CERTIFICATE", "COMPANY_PAN", "INCORPORATION_CERTIFICATE", "ID_PROOF"],
)
EMAIL_JOURNEY_PROMO_APPROVED = env.bool("EMAIL_JOURNEY_PROMO_APPROVED", default=False)
EMAIL_JOURNEY_WELCOME_CREDITS = env("EMAIL_JOURNEY_WELCOME_CREDITS", default="5")
EMAIL_JOURNEY_SENDER_NAME = env("EMAIL_JOURNEY_SENDER_NAME", default="Team Unpod AI")
EMAIL_JOURNEY_SUPPORTED_LANGUAGES = env(
    "EMAIL_JOURNEY_SUPPORTED_LANGUAGES", default="English, Hindi and more"
)
EMAIL_JOURNEY_AGENT_BUILDER_NAME = env("EMAIL_JOURNEY_AGENT_BUILDER_NAME", default="AI Studio")
EMAIL_JOURNEY_AUTO_BUILD_FEATURE_NAME = env(
    "EMAIL_JOURNEY_AUTO_BUILD_FEATURE_NAME", default="Auto Build"
)
EMAIL_JOURNEY_KYC_COMPLETION_TIME = env(
    "EMAIL_JOURNEY_KYC_COMPLETION_TIME", default="a few minutes"
)
EMAIL_JOURNEY_KYC_PATH = env("EMAIL_JOURNEY_KYC_PATH", default="/org/settings/")
EMAIL_JOURNEY_SALES_URL = env("EMAIL_JOURNEY_SALES_URL", default="https://unpod.ai/contact-us")
EMAIL_JOURNEY_PLAYGROUND_URL = env(
    "EMAIL_JOURNEY_PLAYGROUND_URL", default="https://playground.unpod.ai/playground"
)
# Empty -> the Day 21 workflows email is held until Product supplies a link.
EMAIL_JOURNEY_WORKFLOW_TUTORIAL_URL = env("EMAIL_JOURNEY_WORKFLOW_TUTORIAL_URL", default="")

# AWS S3 Configuration
# SECURITY: Credentials loaded from environment variables
# Never hardcode credentials - use .env files
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="unpod")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="ap-south-1")

AWS_S3_CUSTOM_DOMAIN = "%s.s3.amazonaws.com" % AWS_STORAGE_BUCKET_NAME

AWS_S3_OBJECT_PARAMETERS = {
    "CacheControl": "max-age=86400",
}
AWS_EXPIRE_TIME = 3600  # 1 Hour

AWS_PUBLIC_MEDIA_LOCATION = "media"
PUBLIC_FILE_STORAGE = "unpod.common.storage_backends.PublicMediaStorage"

AWS_PRIVATE_MEDIA_LOCATION = "media"
PRIVATE_FILE_STORAGE = "unpod.common.storage_backends.PrivateMediaStorage"

# Cloudinary Configuration
# SECURITY: Credentials loaded from environment variables
# Made optional for backwards compatibility with existing QA environments
CLOUDINARY = {
    "cloud_name": env("CLOUDINARY_CLOUD_NAME", default=""),
    "api_key": env("CLOUDINARY_API_KEY", default=""),
    "api_secret": env("CLOUDINARY_API_SECRET", default=""),
}

# HMS (100ms) Video Platform Configuration
# SECURITY: Credentials loaded from environment variables
# Made optional for backwards compatibility with existing QA environments
HMS = {
    "app_access_key": env("HMS_APP_ACCESS_KEY", default=""),
    "app_secret": env("HMS_APP_SECRET", default=""),
}

HMS_S3_BUCKET = AWS_STORAGE_BUCKET_NAME
HMS_S3_REGION = AWS_S3_REGION_NAME

HMS_AWS_ACCESS_KEY = AWS_ACCESS_KEY_ID
HMS_AWS_SECRET_KEY = AWS_SECRET_ACCESS_KEY

HMS_AWS_RECORDING_FOLDER = env(
    "HMS_AWS_RECORDING_FOLDER", default="recordings-100ms"
)  # "recordings-100ms"

SITEMAP_DIR = ROOT_DIR / "sitemaps"
AWS_SITEMAP_DIR = "sitemaps"

DAILY_REPORT_EMAILS = []

os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

# VAPI Voice AI Platform Configuration
# SECURITY: Credentials loaded from environment variables
# Made optional for backwards compatibility with existing QA environments
VAPI_API_KEY = env("VAPI_API_KEY", default="")
VAPI_URL = env("VAPI_URL", default="https://api.vapi.ai")

APP_NAME = "Unpod.ai"
COMPANY_NAME = "Unpod.ai"
SUPPORT_EMAIL = "info@unpod.ai"
DEFAULT_ORG_HANDLE = "unpod.ai"

# Text-to-Speech / Speech-to-Text Services
# SECURITY: Credentials loaded from environment variables
# Made optional for backwards compatibility with existing QA environments
CARTESIA_API_KEY = env("CARTESIA_API_KEY", default="")

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M:%S"
DATETIME_FORMAT = f"{DATE_FORMAT} {TIME_FORMAT}"
INVOICE_DUE_DAYS = 7

# LiveKit Video Platform Configuration
# SECURITY: Credentials loaded from environment variables
# Made optional for backwards compatibility with existing QA environments
LIVEKIT_URL = env("LIVEKIT_URL", default="")
LIVEKIT_BASE = LIVEKIT_URL.replace("wss://", "").replace("https://", "").rstrip("/") if LIVEKIT_URL else ""
LIVEKIT_API_KEY = env("LIVEKIT_API_KEY", default="")
LIVEKIT_API_SECRET = env("LIVEKIT_API_SECRET", default="")

# Additional TTS/STT Services
# SECURITY: Credentials loaded from environment variables
# Made optional for backwards compatibility with existing QA environments
LMNT_API_KEY = env("LMNT_API_KEY", default="")
SARVAM_API_KEY = env("SARVAM_API_KEY", default="")
INWORLD_API_KEY = env("INWORLD_API_KEY", default="")

# SSE (Server-Sent Events) Configuration
# ------------------------------------------------------------------------------
SSE_HEARTBEAT_INTERVAL = env.int("SSE_HEARTBEAT_INTERVAL", default=30)  # seconds
SSE_RETRY_TIMEOUT = env.int("SSE_RETRY_TIMEOUT", default=3000)  # milliseconds
SSE_CHANNEL_PREFIX = env("SSE_CHANNEL_PREFIX", default="unpod:sse:notifications:")

# Centrifugo Real-time Server Configuration
# ------------------------------------------------------------------------------
# Enable/disable Centrifugo integration (falls back to Redis SSE when disabled)
CENTRIFUGO_ENABLED = env.bool("CENTRIFUGO_ENABLED", default=False)
# Centrifugo server URL (HTTP API endpoint for server-to-server publishing)
CENTRIFUGO_URL = env("CENTRIFUGO_URL", default="")
# Centrifugo WebSocket/SSE URL for frontend clients to connect
# Example: "wss://centrifugo.example.com/connection/websocket" or "/connection/sse"
CENTRIFUGO_WS_URL = env("CENTRIFUGO_WS_URL", default="")
# API key for server-to-server communication
CENTRIFUGO_API_KEY = env("CENTRIFUGO_API_KEY", default="")
# HMAC secret key for JWT token generation (must match Centrifugo config)
CENTRIFUGO_TOKEN_HMAC_SECRET_KEY = env("CENTRIFUGO_TOKEN_HMAC_SECRET_KEY", default="")
# Channel prefix for user personal channels (default: "user" -> "user:123")
CENTRIFUGO_USER_CHANNEL_PREFIX = env("CENTRIFUGO_USER_CHANNEL_PREFIX", default="user")
# Default token expiration in minutes
CENTRIFUGO_TOKEN_EXPIRE_MINUTES = env.int("CENTRIFUGO_TOKEN_EXPIRE_MINUTES", default=60)

DEFAULT_PRODUCT_ID = "unpod.ai"

# Internal API Token
# SECURITY: Optional for QA compatibility, should be set in production
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_API_TOKEN = env("SECRET_API_TOKEN", default="")

PREFECT_API_URL = env("PREFECT_API_URL", default="")

API_SERVICE_URL = env("API_SERVICE_URL", default="http://0.0.0.0:9116/api/v1")
