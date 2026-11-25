import importlib.util

from django.core.exceptions import ImproperlyConfigured

from tchekam.core.observability import init_sentry

from .base import *  # noqa: F403
from .base import env

DEBUG = False
# No defaults for these two: prod must fail loudly if they are missing.
SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
DATABASES = {"default": env.db("DATABASE_URL")}
S3_ENDPOINT_URL = env("S3_ENDPOINT_URL")
S3_BUCKET = env("S3_BUCKET")
S3_ACCESS_KEY = env("S3_ACCESS_KEY")
S3_SECRET_KEY = env("S3_SECRET_KEY")
WASENDER_WEBHOOK_SECRET = env("WASENDER_WEBHOOK_SECRET")
WASENDER_API_KEY = env("WASENDER_API_KEY")
# Rate limits, typing delays and the reply-only rule protect the number from a ban.
if not CHANNEL_SAFEGUARDS:  # noqa: F405
    raise ImproperlyConfigured("CHANNEL_SAFEGUARDS must be true in production")
# A failover to a number without a key would silently break every send.
if WASENDER_ACTIVE_SESSION not in ("primary", "backup"):  # noqa: F405
    raise ImproperlyConfigured("WASENDER_ACTIVE_SESSION must be primary or backup")
if WASENDER_ACTIVE_SESSION == "backup" and not WASENDER_BACKUP_API_KEY:  # noqa: F405
    raise ImproperlyConfigured("WASENDER_ACTIVE_SESSION=backup needs WASENDER_BACKUP_API_KEY")
# Linked from the menu; a placeholder URL in prod would send users to a dead page.
TERMS_URL = env("TERMS_URL")
# Empty omits the "More help" line; the placeholder default would point users at a dead page.
HELP_URL = env("HELP_URL", default="")
# Pseudonymous reporter identity; a placeholder would make keys guessable from phone numbers.
REPORTER_KEY_SECRET = env("REPORTER_KEY_SECRET")
# One provider key for chat, classification, evidence extraction and transcription.
OPENROUTER_API_KEY = env("OPENROUTER_API_KEY")
# The default image has no torch; fail at startup, not at the first photo check after a deploy.
if EMBEDDER_BACKEND == "openclip" and importlib.util.find_spec("open_clip") is None:  # noqa: F405
    raise ImproperlyConfigured(
        "EMBEDDER_BACKEND=openclip needs the image built with WITH_ML=1 "
        "(or set EMBEDDER_BACKEND explicitly)"
    )
# Web image search; an empty key would make every search fail without a trace.
SERPAPI_API_KEY = env("SERPAPI_API_KEY")

# Admin assets are served by the app itself (no CDN or nginx in front); right after
# SecurityMiddleware, as WhiteNoise requires. Prod only: dev and tests keep Django's defaults.
# Only prod collects static files (admin assets); base has no staticfiles app, hence no
# `collectstatic` command until this line.
INSTALLED_APPS = [*INSTALLED_APPS, "django.contrib.staticfiles"]  # noqa: F405
STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405
MIDDLEWARE = [  # noqa: F405
    MIDDLEWARE[0],  # noqa: F405
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],  # noqa: F405
]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Errors only: no default PII, request bodies or locals, and events are masked by
# `scrub_event`. Unset DSN means Sentry stays off (e.g. staging without an account).
SENTRY_DSN = env("SENTRY_DSN", default="")
init_sentry(
    dsn=SENTRY_DSN,
    environment=env("SENTRY_ENVIRONMENT", default="production"),
    # Render exposes the deployed commit at runtime.
    release=env("SENTRY_RELEASE", default=env("RENDER_GIT_COMMIT", default="")),
    traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
)

# Render terminates TLS at its proxy, so trust the forwarded proto header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
# Keep the health probe reachable over plain HTTP for the platform's checker.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)

# Deliberately off: 1h HSTS while bootstrapping, and subdomain/preload scope is undecided.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# Evidence must be encrypted at rest in prod; opt out only via env.
S3_SSE = env.bool("S3_SSE", default=True)
