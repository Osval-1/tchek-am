from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

SECRET_KEY = env("SECRET_KEY", default="insecure-local-dev-key-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    # Before apps that define tasks, so the Procrastinate app is ready when they register.
    "procrastinate.contrib.django",
    "tchekam.core",
    "tchekam.messaging",
    "tchekam.identifiers",
    "tchekam.conversations",
    "tchekam.imaging",
    "tchekam.reports",
    "tchekam.reputation",
    "tchekam.checks",
    "tchekam.ai",
    "tchekam.speech",
    "tchekam.moderation",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "tchekam.urls"
WSGI_APPLICATION = "tchekam.wsgi.application"
ASGI_APPLICATION = "tchekam.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://tchekam:tchekam@localhost:5432/tchekam")
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Douala"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# Shared cache (reputation bands, 1 h) in Postgres, so an invalidation made by the web process
# (moderation) is seen by the worker (checks) at once. The table is created by the
# reputation migration 0001_cache_table. Test settings use LocMem.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "tchekam_cache",
    }
}

# HMAC key for Report.reporter_key (pseudonymous reporter identity that survives erasure).
# Never change it once reports exist: existing keys are kept, new ones would differ.
REPORTER_KEY_SECRET = env("REPORTER_KEY_SECRET", default="insecure-local-reporter-key")

# Background tasks: run inline when True (test settings); otherwise deferred to the worker.
TASKS_EAGER = env.bool("TASKS_EAGER", default=False)

# "s3" or "memory" (tests).
OBJECT_STORE_BACKEND = env("OBJECT_STORE_BACKEND", default="s3")
S3_ENDPOINT_URL = env("S3_ENDPOINT_URL", default="http://localhost:8333")
S3_BUCKET = env("S3_BUCKET", default="tchekam-evidence")
S3_ACCESS_KEY = env("S3_ACCESS_KEY", default="minioadmin")
S3_SECRET_KEY = env("S3_SECRET_KEY", default="minioadmin")
# SeaweedFS ignores the region; R2 accepts "auto" but boto3 SigV4 also accepts it.
S3_REGION = env("S3_REGION", default="us-east-1")
# Off by default: local SeaweedFS may not support SSE. Prod turns it on.
S3_SSE = env.bool("S3_SSE", default=False)

# Messaging: "wasender" (real provider) or "fake" (tests, offline dev).
MESSAGING_CHANNEL = env("MESSAGING_CHANNEL", default="wasender")
WASENDER_API_KEY = env("WASENDER_API_KEY", default="")
WASENDER_BASE_URL = env("WASENDER_BASE_URL", default="https://www.wasenderapi.com/api")
# Empty means the webhook rejects every request (fail closed).
WASENDER_WEBHOOK_SECRET = env("WASENDER_WEBHOOK_SECRET", default="")

# Linked from the main menu as the privacy policy and terms of use.
TERMS_URL = env("TERMS_URL", default="https://tchek-am.example/terms")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact": {"()": "tchekam.core.RedactingFilter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "filters": ["redact"]}},
    "root": {"handlers": ["console"], "level": "INFO"},
    # httpx logs every request URL at INFO, and URLs can carry message ids (WaSender media).
    "loggers": {
        "httpx": {"level": "WARNING"},
        "httpx2": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}

# Per user and local day, across all kinds of check.
CHECKS_PER_DAY = env.int("CHECKS_PER_DAY", default=30)

# Reports a user may submit per local day (withdrawn ones do not count).
REPORTS_PER_DAY = env.int("REPORTS_PER_DAY", default=3)
# Review time quoted to reporters, in hours.
REVIEW_ETA_HOURS = env.int("REVIEW_ETA_HOURS", default=24)

# AI (Claude): "anthropic" (real API) or "fake" (tests, offline dev).
AI_BACKEND = env("AI_BACKEND", default="anthropic")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
# Haiku for routing and classification; Sonnet only for screenshot extraction.
AI_MODEL_FAST = env("AI_MODEL_FAST", default="claude-haiku-5-5")
AI_MODEL_VISION = env("AI_MODEL_VISION", default="claude-sonnet-5-5")
# Server-side refusal fallback on extraction calls (Sonnet only; Haiku has none).
AI_REFUSAL_FALLBACK = env.bool("AI_REFUSAL_FALLBACK", default=True)

# Speech-to-text: "groq" (Whisper API) or "fake" (tests, offline dev).
SPEECH_BACKEND = env("SPEECH_BACKEND", default="groq")
GROQ_API_KEY = env("GROQ_API_KEY", default="")
GROQ_BASE_URL = env("GROQ_BASE_URL", default="https://api.groq.com/openai/v1")
SPEECH_MODEL = env("SPEECH_MODEL", default="whisper-large-v3")

# Trust the first X-Forwarded-For hop as the client IP (audit logs). Only enable behind a proxy
# that overwrites the header; otherwise anyone could forge the IP written to the audit log.
TRUST_PROXY_HEADERS = env.bool("TRUST_PROXY_HEADERS", default=False)
