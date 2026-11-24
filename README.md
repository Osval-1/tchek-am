# Tchek-Am

**Tchek am before you pay.** A WhatsApp bot that helps buyers in Cameroon check a seller's number, product photo or message before paying by MoMo / Orange Money, and lets scam victims report with evidence (AI-assisted, human-reviewed).

## Docs
- [MVP PRD v1.0](docs/features/tchek-am-mvp/PRD.md): the build spec
- [PRD background](docs/prd.md): rationale and detail
- [Architecture](docs/architecture.md): how (draft)
- [Decision record (ADR)](docs/ADR.md): every decision, with the question and the answer
- [Glossary](docs/CONTEXT.md): domain terms
- [Idea brief](docs/idea-brief.md): market research and original ideas

Status: pre-MVP, planning.


## Getting started

Prerequisites: [uv](https://docs.astral.sh/uv/) (installs Python 3.13 for you) and Docker.

```bash
docker compose up -d        # Postgres 16 + pgvector, S3 (SeaweedFS, http://localhost:8333)
cp .env.example .env
uv sync
uv run python src/manage.py migrate
uv run python src/manage.py runserver
uv run pytest               # needs the db service running
```

Health check: `GET http://localhost:8000/healthz`. Deployment (Docker image, `render.yaml`, backups): see [docs/runbook.md](docs/runbook.md).

## Background tasks

Tasks are registered with `tchekam.core.tasks.register("name")` in an app's `tasks.py` and
enqueued with `tchekam.core.tasks.enqueue("name", **kwargs)` (Procrastinate under the hood;
set `TASKS_EAGER=True` to run inline, as the test settings do). Run the worker with:

```bash
uv run python src/manage.py procrastinate worker
```

## Tests

`uv run pytest` runs everything; S3 contract tests are marked `integration` and skip if the
S3 endpoint is unreachable. Run only them with `uv run pytest -m integration`.

## Moderator setup

Every staff login (admin and `/moderation/`) needs a password and a TOTP token. There is no
web enrolment: you enrol a user from the server shell.

```bash
uv run python src/manage.py createsuperuser
uv run python src/manage.py add_totp <username>
```

`add_totp` prints, once, the base32 secret, the `otpauth://` URI, a QR code and 8 one-time
recovery tokens. Scan the QR with an authenticator app and store the recovery tokens offline.
Then log in at `/admin/` with password + token (pick the device in the list if asked; a
recovery token is entered in the same field, with the "recovery" device).
Lost phone: `add_totp <username> --replace` (also issues new recovery tokens).

**Do not redirect `add_totp` output to a file or log:** it contains the secret and recovery
tokens. Read them from the terminal and close it.

Sessions end after 8 h idle. Five failed logins for a username (or 20 from one IP) lock
sign-in for 15 minutes.

### If you are locked out

```bash
uv run python src/manage.py unlock_login <username>
uv run python src/manage.py unlock_login --ip <address>
```

Each clears that counter and lock and writes a `moderator.login_unlocked` audit row. There is
no `--all`: the shared database cache cannot list keys by prefix. Behind a proxy, set
`TRUSTED_PROXY_COUNT` (Render: 1, verify at deploy) so the client IP is the real one.
