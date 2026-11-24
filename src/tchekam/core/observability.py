from typing import Any

import sentry_sdk

from tchekam.core.redact import mask_phones

# Event sections that carry free text. Others (event_id, timestamp, release...) are left alone:
# their digit runs would otherwise be mistaken for phone numbers.
_TEXT_SECTIONS = ("message", "logentry", "exception", "breadcrumbs", "extra", "request")
# Webhook bodies are user messages and headers carry the webhook secret.
_REQUEST_KEEP = ("url", "method")


def _mask(value: Any) -> Any:
    if isinstance(value, str):
        return mask_phones(value)
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return value


def scrub_event(event: dict, hint: dict) -> dict:
    """Sentry `before_send`: strip request data and locals, mask phone numbers in free text."""
    if "request" in event:
        event["request"] = {k: v for k, v in event["request"].items() if k in _REQUEST_KEEP}
    # Frame locals can hold message text or numbers.
    for exc in event.get("exception", {}).get("values", []):
        for frame in exc.get("stacktrace", {}).get("frames", []):
            frame.pop("vars", None)
    event.pop("user", None)
    for section in _TEXT_SECTIONS:
        if section in event:
            # Mask only, as the logging filter does: truncating would destroy tracebacks.
            event[section] = _mask(event[section])
    return event


def init_sentry(
    *,
    dsn: str,
    environment: str,
    release: str,
    # Off by default: spans and transactions bypass before_send, so they are not scrubbed.
    traces_sample_rate: float = 0.0,
    transport=None,
) -> bool:
    """Start Sentry when a DSN is configured. Returns whether it was started."""
    if not dsn:
        return False
    # Needs sentry-sdk 2.x (pinned <3): 3.x dropped send_default_pii and include_local_variables.
    sentry_sdk.init(
        transport=transport,
        dsn=dsn,
        environment=environment,
        release=release or None,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        before_send=scrub_event,
    )
    return True
