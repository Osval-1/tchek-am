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

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact": {"()": "tchekam.core.RedactingFilter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "filters": ["redact"]}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
