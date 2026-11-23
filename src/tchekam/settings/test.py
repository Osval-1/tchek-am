from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "test-only-key"
ALLOWED_HOSTS = ["testserver", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
TASKS_EAGER = True
OBJECT_STORE_BACKEND = "memory"
MESSAGING_CHANNEL = "fake"
AI_BACKEND = "fake"
ANTHROPIC_API_KEY = ""
SPEECH_BACKEND = "fake"
GROQ_API_KEY = ""
WASENDER_WEBHOOK_SECRET = "test-webhook-secret"
REPORTER_KEY_SECRET = "test-reporter-key"
# Fast and per-test isolated; base/prod use the shared DatabaseCache.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
