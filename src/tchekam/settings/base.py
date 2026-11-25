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
    # Custom config swaps in the OTP-enforcing admin site (core/admin_site.py).
    "tchekam.core.apps.TchekAdminConfig",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    # Before apps that define tasks, so the Procrastinate app is ready when they register.
    "procrastinate.contrib.django",
    "tchekam.core",
    "tchekam.messaging",
    "tchekam.identifiers",
    "tchekam.conversations",
    "tchekam.imaging",
    "tchekam.groups",
    "tchekam.reports",
    "tchekam.reputation",
    "tchekam.checks",
    "tchekam.ai",
    "tchekam.speech",
    "tchekam.moderation",
    "tchekam.appeals",
    # Last: depends on every app holding personal data, and nothing depends on it.
    "tchekam.retention",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
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
# Failover (ISSUES.md Issue 23): a second WhatsApp number. `switch_channel` overrides the
# active session in the database; this setting is the default before any switch.
WASENDER_ACTIVE_SESSION = env("WASENDER_ACTIVE_SESSION", default="primary")  # primary | backup
WASENDER_BACKUP_API_KEY = env("WASENDER_BACKUP_API_KEY", default="")
WASENDER_BACKUP_WEBHOOK_SECRET = env("WASENDER_BACKUP_WEBHOOK_SECRET", default="")
# Wrap the channel in SafeChannel (rate limits, typing, reply-only). Tests turn it off.
CHANNEL_SAFEGUARDS = env.bool("CHANNEL_SAFEGUARDS", default=True)
# Global outbound budget across all workers; the per-recipient limit is fixed in messaging.limiter.
SEND_RATE_PER_MINUTE = env.int("SEND_RATE_PER_MINUTE", default=20)

# Linked from the main menu as the privacy policy and terms of use.
TERMS_URL = env("TERMS_URL", default="https://tchek-am.example/terms")
# Appended to the reporter's next-steps message when non-empty.
HELP_URL = env("HELP_URL", default="https://tchek-am.example/help")
# Bot messages outside a reply are only sent this long after the user's last message (ADR-011).
REPLY_WINDOW_HOURS = env.int("REPLY_WINDOW_HOURS", default=24)

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
# New appeals a user may submit per local day.
APPEALS_PER_DAY = env.int("APPEALS_PER_DAY", default=2)
# Review time quoted to reporters, in hours.
REVIEW_ETA_HOURS = env.int("REVIEW_ETA_HOURS", default=24)

# Image embeddings: "openclip" (needs the `ml` extra) or "fake" (tests, CI, offline dev).
EMBEDDER_BACKEND = env("EMBEDDER_BACKEND", default="openclip")

# Conversational agent. Missing policy, budgets, keys or runtime cohort fail closed.
AGENT_ENABLED = env.bool("AGENT_ENABLED", default=False)
AGENT_LANGUAGES = env.list("AGENT_LANGUAGES", default=["fr", "en"])
AGENT_VISION_ENABLED = env.bool("AGENT_VISION_ENABLED", default=False)
OPENROUTER_MODEL = env("OPENROUTER_MODEL", default="deepseek/deepseek-v4.1-flash-1017")
OPENROUTER_ENDPOINTS = env.list("OPENROUTER_ENDPOINTS", default=["together/us"])
OPENROUTER_TIMEOUT_SECONDS = env.float("OPENROUTER_TIMEOUT_SECONDS", default=30)
AGENT_CHAT_MODEL = env("AGENT_CHAT_MODEL", default=OPENROUTER_MODEL)
AGENT_VISION_MODEL = env("AGENT_VISION_MODEL", default=OPENROUTER_MODEL)
AGENT_ROLE_POLICIES = env.json("AGENT_ROLE_POLICIES", default={})
OPENROUTER_API_KEY = env("OPENROUTER_API_KEY", default="")
AGENT_MEMORY_KEY_VERSION = env("AGENT_MEMORY_KEY_VERSION", default="v1")
AGENT_MEMORY_KEYS = env.json("AGENT_MEMORY_KEYS", default={})
AGENT_OPERATION_KEY = env("AGENT_OPERATION_KEY", default="")
AGENT_MAX_MODEL_CALLS = env.int("AGENT_MAX_MODEL_CALLS", default=6)
AGENT_MAX_TOOL_CALLS = env.int("AGENT_MAX_TOOL_CALLS", default=8)
AGENT_MAX_PENDING = env.int("AGENT_MAX_PENDING", default=3)
AGENT_MAX_OUTPUT_TOKENS = env.int("AGENT_MAX_OUTPUT_TOKENS", default=1024)
AGENT_CONTEXT_BYTES = env.int("AGENT_CONTEXT_BYTES", default=32000)
AGENT_DEADLINE_SECONDS = env.int("AGENT_DEADLINE_SECONDS", default=60)
AGENT_REQUEST_TIMEOUT = env.int("AGENT_REQUEST_TIMEOUT", default=20)
AGENT_HISTORY_MESSAGES = env.int("AGENT_HISTORY_MESSAGES", default=20)
AGENT_HISTORY_HOURS = env.int("AGENT_HISTORY_HOURS", default=24)
AGENT_HISTORY_TOKENS = env.int("AGENT_HISTORY_TOKENS", default=6000)
AGENT_DAILY_BUDGET_MICROUSD = env.int("AGENT_DAILY_BUDGET_MICROUSD", default=0)
AGENT_MONTHLY_BUDGET_MICROUSD = env.int("AGENT_MONTHLY_BUDGET_MICROUSD", default=0)
LANGFUSE_BASE_URL = env("LANGFUSE_BASE_URL", default="http://localhost:3100")
AGENT_TRACE_SYNTHETIC = env.bool("AGENT_TRACE_SYNTHETIC", default=False)
LANGFUSE_PUBLIC_KEY = env("LANGFUSE_PUBLIC_KEY", default="")
LANGFUSE_SECRET_KEY = env("LANGFUSE_SECRET_KEY", default="")

# OpenRouter handles all extraction/classification and transcription calls.
AI_BACKEND = env("AI_BACKEND", default="openrouter")
SPEECH_BACKEND = env("SPEECH_BACKEND", default="openrouter")
SPEECH_MODEL = env("SPEECH_MODEL", default="openai/whisper-large-v3")
SPEECH_MAX_AUDIO_BYTES = env.int("SPEECH_MAX_AUDIO_BYTES", default=25 * 1024 * 1024)
AGENT_MAX_AUDIO_SECONDS = env.int("AGENT_MAX_AUDIO_SECONDS", default=120)
SPEECH_MAX_COST_MICROUSD = env.int("SPEECH_MAX_COST_MICROUSD", default=30000)

# Web reverse image search: "serpapi" (Google Lens via SerpAPI) or "fake" (tests, offline dev).
WEB_SEARCH_BACKEND = env("WEB_SEARCH_BACKEND", default="serpapi")
SERPAPI_API_KEY = env("SERPAPI_API_KEY", default="")
# Per user and local day, for photo checks only (report images bypass it).
WEB_SEARCH_PER_USER_DAY = env.int("WEB_SEARCH_PER_USER_DAY", default=5)
# Provider calls per local month, report images included; a cache hit never counts.
WEB_SEARCH_MONTHLY_BUDGET = env.int("WEB_SEARCH_MONTHLY_BUDGET", default=1000)

# Number of trusted reverse proxies in front of Django. 0: ignore X-Forwarded-For and use
# REMOTE_ADDR. N: the client IP is the N-th entry from the RIGHT of X-Forwarded-For (the one our
# outermost proxy appended; anything further left can be forged). Render: set 1 (verify at
# deploy). Never leave 0 behind a proxy: every client would then share the proxy's IP, so
# audit logs and login throttling would treat all users as one.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)

# Moderator security: TOTP 2FA (django-otp). Failed token checks back off exponentially:
# after n consecutive failures a device refuses tokens for 5 * 2**(n-1) seconds.
OTP_TOTP_ISSUER = "Tchek-Am"
OTP_TOTP_THROTTLE_FACTOR = 5

# Sessions: 8 h idle timeout (refreshed on every request), gone when the browser closes.
SESSION_COOKIE_AGE = 8 * 3600
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"

# Typical prices in XAF of common items, used by the message check to spot an amount far below
# the going rate. Keys are lower-case, accent-free words as they appear in messages. Optional.
PRICE_HINTS = {
    "iphone 15": 450000,
    "iphone 14": 350000,
    "iphone 13": 250000,
    "iphone 12": 180000,
    "iphone 11": 130000,
    "ps5": 300000,
    "playstation 5": 300000,
    "macbook": 450000,
    "laptop": 150000,
    "samsung s23": 350000,
    "samsung s22": 250000,
}
# An amount under this share of the hint counts as "far below".
PRICE_HINT_RATIO = 0.4
