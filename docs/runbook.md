# Runbook

Operational procedures for Tchek-Am: running the worker, deploying, backups, access and keys.

## Running the worker

One Procrastinate worker process handles every queue. WhatsApp sends use the `whatsapp` queue, which is
limited to 3 concurrent sends by three lock names (`whatsapp-0`..`whatsapp-2`, chosen from a hash of the
recipient, so sends to one person stay in order).

```bash
uv run python src/manage.py procrastinate worker -q default,whatsapp --concurrency 8
```

- `-q` takes a comma-separated list; name every queue the worker should serve (an empty value means all). Jobs on a queue nobody listens to never run.
- The periodic job `messaging.recover_stuck_events` (every 5 minutes) is deferred by the worker itself. Procrastinate de-duplicates periodic jobs, so more than one worker is safe.
- Delivery is at-least-once. If a worker dies after WhatsApp accepted a message but before the event was marked `processed`, the recovery job (events stuck in `processing` for more than 10 minutes) runs the event again and the reply can be sent twice.

## What to do when the WhatsApp number is banned

Symptoms: sends fail for every user, WaSender shows the session as disconnected or banned, `outbox: gave up` warnings in the worker log.

1. Switch to the backup number (this takes effect on the next send, no restart):
   ```bash
   uv run python src/manage.py switch_channel backup
   ```
   It refuses if `WASENDER_BACKUP_API_KEY` is not set. It writes a `channel.switched` audit row.
2. In the WaSender dashboard, set the backup session's webhook URL to `/webhooks/whatsapp` with the secret in `WASENDER_BACKUP_WEBHOOK_SECRET` (the webhook accepts either secret).
3. Post the backup number to the partner group admins (the people who run the WhatsApp groups where the bot listens), so they can add it to their groups and tell members.
4. When the primary number is usable again: `switch_channel primary`.

The bot only answers people who wrote to it in the last 24 hours (`REPLY_WINDOW_HOURS`). After a switch, users who talk to the old number are not reachable from the new one until they write to it.

Settings: `WASENDER_API_KEY`, `WASENDER_BACKUP_API_KEY`, `WASENDER_BACKUP_WEBHOOK_SECRET`, `WASENDER_ACTIVE_SESSION` (the default before any switch; `switch_channel` overrides it from then on).

## Outbound limits

- Global: `SEND_RATE_PER_MINUTE` (default 20) across all workers.
- Per recipient: 6 sends in 30 seconds.
- Over a limit the send is not dropped: it is re-queued on the `whatsapp` queue after the wait. After 20 deferrals, or 3 transient errors, it is abandoned and logged by class name.
- `CHANNEL_SAFEGUARDS=false` turns the safeguards off (tests only; never in production).

## Deploy

Everything runs on Render (Frankfurt): `render.yaml` defines the web service, the worker and the
Postgres database. Both services build the same `Dockerfile`; the worker overrides the command to
`python src/manage.py procrastinate worker -q default,whatsapp --concurrency 8` (the command from
"Running the worker" above). Evidence and backups live in a Cloudflare R2 bucket (EU jurisdiction).

### First deploy checklist

1. **R2**: create a private bucket in the EU jurisdiction and an API token limited to it (object read and write). The endpoint looks like `https://<account>.eu.r2.cloudflarestorage.com`.
2. **Sentry** (optional but recommended): create a project and copy its DSN.
3. **Render**: New > Blueprint, pick this repository. Render lists every problem in `render.yaml` before it creates anything (this is the documented manual validation; `tests/deploy/test_render_blueprint.py` covers the structure in CI). It then asks for the secrets marked `sync: false`.
4. **Fill the variables** (table below). `SECRET_KEY` is generated for you; `DATABASE_URL` is wired to the blueprint database.
5. **Wait for the first deploy.** The pre-deploy command runs `migrate`, which also enables the `vector` extension (Render Postgres allows `CREATE EXTENSION vector`) and creates the Procrastinate tables and the cache table. The health check is `GET /healthz`.
6. **Create the first moderator** from the web service's Render shell (see "Moderator access").
7. **WaSender**: set the primary session's webhook URL to `https://<your host>/webhooks/whatsapp` and its secret to the same value as `WASENDER_WEBHOOK_SECRET`. Do the same for the backup session with `WASENDER_BACKUP_WEBHOOK_SECRET` (ban procedure above).
8. **Consent first**: for every partner group, record the admin's consent in the admin (Groups > Partner groups: admin number, when the notice was confirmed) **before** adding the bot's number to that group. The bot leaves groups that have no consent record.
9. **Verify** `TRUSTED_PROXY_COUNT`, R2 encryption and a test backup (sections below), and trigger a Sentry test event (see "Monitoring").

### Environment variables

Prod settings (`tchekam.settings.prod`, selected by `DJANGO_SETTINGS_MODULE`) refuse to start when a required one is missing.

| Variable | Notes |
| --- | --- |
| `SECRET_KEY` | Required. Generated by the blueprint, shared by web and worker. |
| `ALLOWED_HOSTS` | Required. Comma-separated hostnames, e.g. `tchekam-web.onrender.com,bot.example.org`. |
| `DATABASE_URL` | Required. Wired to the blueprint database. |
| `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Required. R2. `S3_REGION=auto` and `S3_SSE=true` come from the blueprint. |
| `WASENDER_API_KEY`, `WASENDER_WEBHOOK_SECRET` | Required. Primary WhatsApp number. |
| `WASENDER_BACKUP_API_KEY`, `WASENDER_BACKUP_WEBHOOK_SECRET` | Needed for failover (`switch_channel backup`, `WASENDER_ACTIVE_SESSION=backup`). |
| `TERMS_URL` | Required. Privacy policy and terms page. |
| `HELP_URL` | Optional. Empty omits the "More help" line. Add it in the dashboard if wanted. |
| `REPORTER_KEY_SECRET` | Required. Set once, never rotate (see "Keys and secrets"). |
| `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `SERPAPI_API_KEY` | Required. Claude, Whisper, Google Lens search. |
| `TRUSTED_PROXY_COUNT` | `1`, from the blueprint. |
| `CHANNEL_SAFEGUARDS` | `true`, from the blueprint. Prod refuses to start with `false`. |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE`, `SENTRY_TRACES_SAMPLE_RATE` | Sentry is off when `SENTRY_DSN` is empty. Release defaults to Render's commit hash. Tracing is off (`SENTRY_TRACES_SAMPLE_RATE` defaults to 0) because spans bypass the scrubber; do not enable it without reading "Monitoring". |
| `EMBEDDER_BACKEND` | Required in practice: `openclip` (needs the image built with `WITH_ML=1`) or `fake`. Prod refuses to start on `openclip` without torch. Declared `sync: false` so you must choose; see "Image embeddings". |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | Defaults: redirect on, HSTS 3600 s. `/healthz` is exempt from the redirect. |
| `SEND_RATE_PER_MINUTE`, `CHECKS_PER_DAY`, `WEB_SEARCH_*`, ... | Tuning knobs; see `.env.example`. |

Never set the `*_BACKEND` variables (`AI_BACKEND`, `SPEECH_BACKEND`, `WEB_SEARCH_BACKEND`, `MESSAGING_CHANNEL`, `OBJECT_STORE_BACKEND`) to `fake` or `memory` in production; their defaults are the real providers.

Both services need the full list (the worker calls Claude, Whisper, SerpAPI and WaSender too). Because Render does not support `sync: false` in env groups, the secret list is repeated on web and worker; a test keeps the two identical. When you add a required variable to `settings/prod.py`, add it to `render.yaml` (a test fails otherwise) and to Render's dashboard.

### Image embeddings (`ml` extra)  [DECIDE before the pilot]

The image is built **without** the heavy `ml` extra (torch and open_clip, around 1 GB larger). `EMBEDDER_BACKEND` defaults to `openclip`, so prod settings **refuse to start** (`EMBEDDER_BACKEND=openclip needs the image built with WITH_ML=1`) on the default image, instead of failing at the first photo check. Choose one and set `EMBEDDER_BACKEND` on both services:

- `openclip`: build with `docker build --build-arg WITH_ML=1 .`. On Render, declare `WITH_ML=1` as an environment variable on both services (Render makes service variables available to Docker builds; confirm on the first build log). Model weights are downloaded on first use and are not baked into the image, so each fresh container downloads them again. **Plan size is part of this decision:** the `starter` plan (512 MB) is very likely too small for torch plus ViT-B-32 on the worker; plan for a larger worker plan and watch memory after the first image check.
- `fake`: pHash-derived vectors only. It works on `starter`, but real near-duplicate image matching (the embedding path) is disabled, so photo and report-image similarity is weaker. Not recommended for production unless the founder accepts that.

CI and the image build use `EMBEDDER_BACKEND=fake` only so they do not need torch.

### Routine deploys

Services auto-deploy when CI passes on the tracked branch (`autoDeployTrigger: checksPass`). For each deploy Render builds the image, runs `python src/manage.py migrate --noinput` on it, and only then switches traffic once `/healthz` answers. A failing migration leaves the previous version running. The worker restarts on its own as part of the same sync; it is not covered by the pre-deploy command, so for a migration that changes tables the worker uses, check the worker log after the deploy and restart it if it errors. Jobs are at-least-once, so a restart is safe.

Local check of the image against the compose database:

```bash
docker build -t tchekam .
docker run --rm --network host --env-file .env.prod-test tchekam python src/manage.py migrate --noinput
docker run -d --network host --env-file .env.prod-test tchekam
curl http://localhost:8000/healthz
```

(`.env.prod-test` holds dummy values for every required variable; CI does the same in the `image` job.)

### Roll back

1. **Code**: Render dashboard > the service > Events > pick the last good deploy > Rollback. Do this for web and worker.
2. **Database**: rollbacks do not undo migrations. Migrations in this project add tables and columns, so the previous code normally runs on the newer schema. If a migration must be undone, run the specific reverse migration from the Render shell (`python src/manage.py migrate <app> <previous migration>`) **before** rolling the code back, only after a fresh `backup_database`. For data damage, use point-in-time recovery (next section).
3. Re-check `/healthz` and the worker log.

## Backup and restore

Two layers:

1. **Render Postgres point-in-time recovery (PITR)** is the first line for "undo the last hour". Availability and the recovery window depend on the database plan; confirm in the dashboard (database > Recovery) that it is enabled for the plan in `render.yaml`.
2. **Monthly logical dump to R2**: the periodic job `core.backup_database` (03:00 UTC on the 1st, deferred by the worker like `messaging.recover_stuck_events`) runs `pg_dump --format=custom` (the image includes `postgresql-client`) and stores it in the evidence bucket as `backups/tchekam-YYYY-MM-DD.dump`. The database password reaches `pg_dump` through the environment, never the command line, and a failure logs only a masked message. A failed run shows up as a failed job and a Sentry event.

Run one by hand, for instance right after the first deploy and before a risky migration:

```bash
python src/manage.py backup_database
```

It prints the key and fails with an error otherwise. The dump is held in memory while uploading, which is fine at pilot size; revisit when the database reaches a few hundred MB.

**Set an R2 lifecycle rule on the `backups/` prefix** (for example delete after 90 days). Backups contain personal data, and a copy that never expires would defeat the retention schedule.

### Restore drill (do it before launch, then every quarter)

1. Create a scratch database: a new Render Postgres, or locally `docker compose up -d db`.
2. Download the dump from R2 (dashboard or `aws s3 cp --endpoint-url <S3_ENDPOINT_URL> s3://<bucket>/backups/<file> .`).
3. Enable the extension and restore:
   ```bash
   psql "$SCRATCH_URL" -c 'CREATE EXTENSION IF NOT EXISTS vector'
   pg_restore --no-owner --no-acl --dbname "$SCRATCH_URL" tchekam-YYYY-MM-DD.dump
   ```
4. Point a throwaway app at it (`DATABASE_URL=$SCRATCH_URL`, prod-test env) and check that `/healthz` answers and that the admin shows recent reports.
5. Write down how long it took and what you had to fix.

To restore production for real: stop the worker first (so no event is processed against old data), restore into a **new** database, point `DATABASE_URL` at it, redeploy web and worker, then run `unlock_login` for any moderator who is locked out. Evidence files are not in the dump; they stay in R2 and the restored rows point at them.

## Moderator access

`createsuperuser` and `add_totp` are run from the web service's Render shell. Every staff login needs a password and a TOTP token; there is no web enrolment.

```bash
python src/manage.py createsuperuser
python src/manage.py add_totp <username>
```

`add_totp` prints the secret, the `otpauth://` URI, a QR code and 8 recovery tokens once. Do not redirect its output to a file or log, and do not run it where output is captured. For a lost phone: `add_totp <username> --replace`.

When a moderator is locked out (5 failed logins for a username or 20 for one IP, 15 minutes):

```bash
python src/manage.py unlock_login <username>
python src/manage.py unlock_login --ip <address>
```

Each writes a `moderator.login_unlocked` audit row.

### Verify `TRUSTED_PROXY_COUNT=1`

Behind Render's proxy the app must see the real client address, or every login and audit row would carry the proxy's IP and one attacker could lock everyone out. After the first deploy:

1. Log in at `/admin/` from your own machine.
2. In the Render shell, read the IP on the audit row and compare it with your public address (for example from a "what is my IP" page):
   ```bash
   python src/manage.py shell -c "from tchekam.core.models import AuditLog; r = AuditLog.objects.filter(action='moderator.login').latest('pk'); print(r.ip)"
   ```
3. If it shows a private address (10.x, 172.16-31.x), the value is wrong. Check whether another proxy (for example Cloudflare in front of Render) was added: the count must equal the number of proxies that append to `X-Forwarded-For`.

Repeat after any change to what sits in front of the service.

## Keys and secrets

### R2 server-side encryption (`S3_SSE`)

Prod sets `S3_SSE=true`, so every evidence upload asks for `AES256` server-side encryption. After the first deploy confirm that R2 accepted it and reports it:

```bash
python src/manage.py shell -c "
from tchekam.core.storage import get_object_store, new_key
s = get_object_store(); k = new_key('check'); s.put(k, b'x', 'text/plain')
print(s._client.head_object(Bucket=s.bucket, Key=k).get('ServerSideEncryption')); s.delete(k)"
```

Expected output: `AES256`. If it prints `None`, treat the bucket as unencrypted: stop and fix before taking evidence (R2 encrypts objects at rest by default; the check proves that the app and the bucket agree).

### Rotating provider keys

Provider keys can be rotated without downtime. For each: create the new key at the provider, update the variable on **both** web and worker in the Render dashboard (saving triggers a redeploy), check the service works, then revoke the old key.

- `WASENDER_API_KEY` / `WASENDER_BACKUP_API_KEY`: the key for the session. Verify with a message to the bot.
- `WASENDER_WEBHOOK_SECRET` / `WASENDER_BACKUP_WEBHOOK_SECRET`: change it in Render and in the WaSender session's webhook settings at about the same time. The webhook accepts either configured secret, so rotate one session at a time; deliveries signed with the old secret are rejected (fail closed) and WaSender retries them.
- `SERPAPI_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`: swap and redeploy. A bad key shows up as failing checks (Sentry events and worker log lines), not as a startup error.
- `S3_ACCESS_KEY` / `S3_SECRET_KEY`: create a second R2 token, swap, verify with the SSE check above, delete the old token.
- `SENTRY_DSN`: swap and redeploy; the old DSN can be disabled in Sentry.

### Keys that need care

- **`REPORTER_KEY_SECRET`: never rotate.** It is the HMAC key behind the pseudonymous reporter identity (ADR-013). Changing it makes new reports hash to different identities than old ones, which breaks duplicate detection and per-reporter limits. Store a copy offline when you first set it; losing it is as bad as rotating it. It is also required to restore a deployment from backup.
- **`SECRET_KEY`**: changing it signs everyone out (sessions) and resets the failed-login counters. That is acceptable after a suspected leak; do it outside moderation hours and expect each moderator to log in again. Stored data, TOTP devices and reporter keys are not affected.
- **Moderator accounts**: when a moderator leaves, deactivate the user (never delete: consent and audit rows reference staff) and revoke their TOTP devices.

## Monitoring

- **Sentry** receives unhandled errors from web and worker. Events are scrubbed before they leave the process: `send_default_pii` is off, request bodies, headers, cookies, the user and local variables are dropped, and phone numbers in messages, exceptions and breadcrumbs are masked. Do not add `extra` data that contains message text.
- **SDK version**: `sentry-sdk` is pinned to `>=2.0,<3`. Version 3.x removed `send_default_pii` and `include_local_variables` (init raises `TypeError`, which would stop settings loading); moving to 3.x means switching to its `data_collection` API and scrubbing spans with `before_send_span`. Request headers must stay dropped: `X-Webhook-Signature` carries the WaSender secret in plain text and is not on Sentry's sensitive-header list.
- **Tracing is off** (`SENTRY_TRACES_SAMPLE_RATE` = 0). Spans and transactions bypass `before_send`, so they would not be scrubbed.
- **Test event**: in the Render shell run `python src/manage.py shell -c "import sentry_sdk; sentry_sdk.capture_message('deploy test'); sentry_sdk.flush()"` and check it arrives in Sentry with `environment=production` and the release set to the commit.
- **Health**: Render pings `/healthz` (a `SELECT 1`). A failing check blocks a deploy.
- **Worker**: look for `outbox: gave up` warnings (channel trouble, see the ban procedure) and failed `core.backup_database` jobs.

**Summary of what to remember:**
`REPORTER_KEY_SECRET` (never rotate, see ADR-013), `SECRET_KEY` (rotation resets login counters), R2 server-side encryption (`S3_SSE`), rotating the WaSender keys.
