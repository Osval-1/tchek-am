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
