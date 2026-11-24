# Runbook

Operational procedures for Tchek-Am. Sections marked **TODO (Issue 25)** are placeholders for the deploy work.

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

## TODO (Issue 25): deploy

Render deploy, roll back, environment variables.

## TODO (Issue 25): backup and restore

Render Postgres PITR, monthly `pg_dump` to R2.

## TODO (Issue 25): moderator access

`add_totp`, `unlock_login`, `TRUSTED_PROXY_COUNT=1` behind Render's proxy.

## TODO (Issue 25): keys and secrets

`REPORTER_KEY_SECRET` (never rotate, see ADR-013), `SECRET_KEY` (rotation resets login counters), R2 server-side encryption (`S3_SSE`), rotating the WaSender keys.

## Retention

The nightly job `retention.run` (02:00 Africa/Douala, on the `default` queue) applies the retention schedule (ADR-013, ADR-022) and writes one `retention.run` audit row with a count per rule and the class name of any rule that failed.

- See what is due without changing anything: `uv run python src/manage.py run_retention --dry-run` (prints one `rule: count` line per rule; writes no audit row).
- Run it now: `uv run python src/manage.py run_retention`. Safe to repeat: every rule is idempotent and works in batches.
- A rule that failed is listed under `errors` in the audit row and in the worker log (class name only); the other rules still ran, and the next night retries it.
- Legal hold (police or court request): in the admin, select the report, the number (Phone numbers) or the user (Bot users, searched by exact number) and use "Place on legal hold" (superusers, or staff given the `retention | Can place or release a legal hold` permission). Nothing about it is deleted until "Release legal hold". Both are audit-logged. A held user cannot be deleted.
- Never rotate `REPORTER_KEY_SECRET`: reporter identities, the trust kept after erasure and the subject references of old rejected reports are keyed by it.
