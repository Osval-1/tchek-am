"""Failed-login counters in the shared cache, per username and per client IP.

Counters hold only a hash of the username and a number: never passwords or tokens.
"""

import hashlib
import hmac
import unicodedata

from django.conf import settings
from django.core.cache import cache

WINDOW_SECONDS = 15 * 60
LOCK_SECONDS = 15 * 60
MAX_PER_USERNAME = 5
# Higher: one office or carrier NAT may hide several moderators behind one address.
MAX_PER_IP = 20

LOCKED_MESSAGE = "Too many attempts, try again later."


def normalise_username(username: str) -> str:
    # Same NFKC as Django's UsernameField, so every spelling that logs in as one account shares
    # one counter; invisible characters are dropped so they cannot split it either.
    text = unicodedata.normalize("NFKC", username)
    text = "".join(c for c in text if unicodedata.category(c) not in ("Cc", "Cf"))
    return text.strip().casefold()


def username_digest(username: str) -> str:
    # Keyed, so a leaked cache or audit row cannot be reversed by hashing a username list.
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, normalise_username(username).encode(), hashlib.sha256).hexdigest()


def ip_digest(ip: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), ip.encode(), hashlib.sha256).hexdigest()


def _keys(username: str, ip: str | None):
    yield "login_throttle:u:" + username_digest(username), MAX_PER_USERNAME
    if ip:
        yield "login_throttle:ip:" + ip, MAX_PER_IP  # IPs are validated by client_ip()


def is_locked(username: str, ip: str | None) -> bool:
    return any(cache.get(key + ":lock") for key, _ in _keys(username, ip))


def record_failure(username: str, ip: str | None) -> None:
    for key, limit in _keys(username, ip):
        cache.add(key, 0, WINDOW_SECONDS)
        try:
            count = cache.incr(key)
        except ValueError:  # expired between add and incr
            cache.set(key, 1, WINDOW_SECONDS)
            count = 1
        if count >= limit:
            cache.set(key + ":lock", True, LOCK_SECONDS)


def _delete(key: str) -> None:
    cache.delete_many([key, key + ":lock"])


def reset(username: str) -> None:
    """A success clears the user's own counter only; the IP counter must keep running."""
    _delete("login_throttle:u:" + username_digest(username))


def unlock_ip(ip: str) -> None:
    _delete("login_throttle:ip:" + ip)
