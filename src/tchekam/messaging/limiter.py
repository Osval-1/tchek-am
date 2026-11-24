"""Outbound send limits shared by every worker, kept in Postgres.

Two limits, both checked and charged under one advisory lock so concurrent workers cannot
overshoot: a global token bucket (SEND_RATE_PER_MINUTE) and a per-recipient sliding log
(RECIPIENT_MAX_SENDS in RECIPIENT_WINDOW_SECONDS). Hitting either raises `Deferred(retry_after)`.
"""

import hashlib
import hmac
import math
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from .channel import Deferred
from .models import RecipientSend, SendBucket

RECIPIENT_MAX_SENDS = 6
RECIPIENT_WINDOW_SECONDS = 30
# Arbitrary constant; distinct from the per-poster locks used by tchekam.groups.
_LOCK_KEY = 0x7C4E_0023


def recipient_hash(to: str) -> str:
    # Keyed, so a leaked table cannot be reversed by hashing the small space of phone numbers.
    return hmac.new(settings.SECRET_KEY.encode(), to.encode(), hashlib.sha256).hexdigest()


def acquire(to: str) -> None:
    """Charge one send to `to` or raise Deferred. A raise leaves the counters unchanged."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_KEY])
        now = timezone.now()
        window = timedelta(seconds=RECIPIENT_WINDOW_SECONDS)
        # A log, not a bucket: the 7th send inside the window is always refused.
        RecipientSend.objects.filter(sent_at__lt=now - window).delete()
        who = recipient_hash(to)
        recent = list(
            RecipientSend.objects.filter(recipient_hash=who).order_by("sent_at")[
                :RECIPIENT_MAX_SENDS
            ]
        )
        if len(recent) >= RECIPIENT_MAX_SENDS:
            wait = (recent[0].sent_at + window - now).total_seconds()
            raise Deferred(max(1, math.ceil(wait)))

        capacity = settings.SEND_RATE_PER_MINUTE
        per_second = capacity / 60
        bucket = SendBucket.objects.filter(pk=1).first() or SendBucket(
            pk=1, tokens=capacity, updated_at=now
        )
        tokens = min(
            capacity, bucket.tokens + (now - bucket.updated_at).total_seconds() * per_second
        )
        if tokens < 1:
            raise Deferred(max(1, math.ceil((1 - tokens) / per_second)))
        bucket.tokens, bucket.updated_at = tokens - 1, now
        bucket.save()
        RecipientSend.objects.create(recipient_hash=who, sent_at=now)
