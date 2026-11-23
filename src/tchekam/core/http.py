import ipaddress

from django.conf import settings
from django.http import HttpRequest


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None  # never store an unvalidated header value


def client_ip(request: HttpRequest) -> str | None:
    """REMOTE_ADDR, or the N-th X-Forwarded-For entry from the right behind N trusted proxies."""
    remote = _valid_ip(request.META.get("REMOTE_ADDR", ""))
    trusted = settings.TRUSTED_PROXY_COUNT
    if trusted <= 0:
        return remote
    hops = [h for h in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if h.strip()]
    # Counting from the right: left-hand entries are client-supplied and can be forged.
    if len(hops) < trusted:
        return remote
    return _valid_ip(hops[-trusted]) or remote
