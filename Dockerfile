# syntax=docker/dockerfile:1
# One image for web (default CMD) and worker (command override, see render.yaml).

FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.4 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Set to 1 to include the `ml` extra (torch + open_clip, roughly 1 GB). Needed when
# EMBEDDER_BACKEND=openclip, which is the default; see docs/runbook.md.
ARG WITH_ML=0
# Dependencies first, so this layer is cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN if [ "$WITH_ML" = "1" ]; then EXTRA="--extra ml"; fi; \
    uv sync --locked --no-dev --no-install-project $EXTRA

FROM python:3.13-slim AS runtime
# pg_dump for the monthly backup task (core.backup_database).
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=tchekam.settings.prod
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src ./src
# collectstatic loads the prod settings, which refuse to start without these. The values are
# throwaway and set for this one command only: they are not stored in the image.
RUN SECRET_KEY=build-only ALLOWED_HOSTS=localhost DATABASE_URL=postgres://u:p@localhost/x \
    S3_ENDPOINT_URL=http://localhost S3_BUCKET=x S3_ACCESS_KEY=x S3_SECRET_KEY=x \
    WASENDER_API_KEY=x WASENDER_WEBHOOK_SECRET=x TERMS_URL=http://localhost REPORTER_KEY_SECRET=x \
    ANTHROPIC_API_KEY=x GROQ_API_KEY=x SERPAPI_API_KEY=x EMBEDDER_BACKEND=fake \
    python src/manage.py collectstatic --noinput
USER app
EXPOSE 8000
# Render sets PORT. No access log: request paths and query strings stay out of the logs.
CMD ["sh", "-c", "exec gunicorn tchekam.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 60"]
