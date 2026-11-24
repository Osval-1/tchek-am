import hmac
import json
import logging

from django.conf import settings
from django.db import DataError, transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tchekam.core import tasks

from . import outbox
from .models import InboundEvent
from .parser import parse_wasender_payload, storable_payload

logger = logging.getLogger(__name__)


def _signature_ok(request: HttpRequest) -> bool:
    # WaSender sends the configured secret verbatim (not an HMAC). Fail closed if unset.
    # Either session's secret is accepted: after a failover, late events from the old one count.
    given = request.headers.get("X-Webhook-Signature", "")
    if not given:
        return False
    secrets = [settings.WASENDER_WEBHOOK_SECRET, settings.WASENDER_BACKUP_WEBHOOK_SECRET]
    # No short circuit: every configured secret is compared.
    matches = [hmac.compare_digest(given.encode(), s.encode()) for s in secrets if s]
    return any(matches)


@csrf_exempt
@require_POST
def whatsapp_webhook(request: HttpRequest) -> JsonResponse:
    """Authenticate, store once, enqueue. No network I/O here: the provider wants a fast 200."""
    if not _signature_ok(request):
        return JsonResponse({"ok": False}, status=401)
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False}, status=400)

    msg = parse_wasender_payload(payload)
    if msg is None:
        return JsonResponse({"ok": True})
    try:
        # Savepoint so a rejected row does not poison an enclosing transaction.
        with transaction.atomic():
            # Group payloads lose all text here, before anything touches the database.
            event, created = InboundEvent.record(msg, storable_payload(payload, msg))
    except DataError as exc:
        # e.g. a NUL character Postgres refuses in jsonb/text. A retry would fail the same
        # way, so acknowledge it rather than make the provider redeliver forever.
        logger.warning("webhook: unstorable %s payload (%s)", msg.raw_event, type(exc).__name__)
        return JsonResponse({"ok": True, "ignored": True})
    if created:
        key = msg.sender_phone or msg.sender_jid or msg.group_jid or ""
        # Same recipient, same lock: their messages are processed one after another.
        transaction.on_commit(
            lambda: tasks.enqueue(
                "messaging.process_inbound",
                queue=outbox.QUEUE,
                lock=outbox.lock_for(key),
                event_id=event.pk,
            )
        )
    return JsonResponse({"ok": True})
