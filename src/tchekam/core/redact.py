import logging
import re

MAX_LEN = 80
# 8+ digits, optionally separated by single spaces/dots/dashes, optional leading "+".
_PHONE = re.compile(r"(\+?)(\d(?:[ .-]?\d){7,})")


# Assumes a 3-digit country code (fits Cameroon's +237); other lengths still keep 3 digits.
def _mask(match: re.Match) -> str:
    plus, body = match.groups()
    digits = re.sub(r"\D", "", body)
    # Keep the country code only when the number is explicitly international.
    head = digits[:3] if plus else ""
    tail = digits[-2:]
    return f"{plus}{head}{'*' * (len(digits) - len(head) - 2)}{tail}"


def mask_phones(text: str) -> str:
    return _PHONE.sub(_mask, text)


def redact(value: object) -> str:
    """Make a value safe for logs: mask phone numbers, truncate long text."""
    text = mask_phones(str(value))
    return text if len(text) <= MAX_LEN else text[:MAX_LEN] + "…"


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Mask only: truncating every log line would destroy tracebacks and diagnostics.
        try:
            record.msg = mask_phones(record.getMessage())
            record.args = None
        except Exception:  # a logging filter must never raise; leave the record untouched
            pass
        # Exception text can embed numbers, so pre-render and mask it.
        if record.exc_info and record.exc_info[0] is not None:
            record.exc_text = mask_phones(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = mask_phones(record.stack_info)
        return True
