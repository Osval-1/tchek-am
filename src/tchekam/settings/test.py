from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "test-only-key"
ALLOWED_HOSTS = ["testserver", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
TASKS_EAGER = True
OBJECT_STORE_BACKEND = "memory"
MESSAGING_CHANNEL = "fake"
WASENDER_WEBHOOK_SECRET = "test-webhook-secret"
