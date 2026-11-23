"""Pseudonymous reporter key: one person stays one person after their account is erased.

Kept out of models.py so migrations can import it without importing the live models.
"""

import hashlib
import hmac

from django.conf import settings


def reporter_key_for(wa_phone: str) -> str:
    """HMAC-SHA256 of the reporter's WhatsApp number (hex). Not reversible without the secret."""
    secret = settings.REPORTER_KEY_SECRET.encode()
    return hmac.new(secret, wa_phone.encode(), hashlib.sha256).hexdigest()
