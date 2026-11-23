"""Builders for pure reputation tests. No Django, no DB."""

from datetime import UTC, date, datetime, timedelta

from tchekam.reputation.facts import ReportFacts

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def days_ago(n: int, now: datetime = NOW) -> datetime:
    return now - timedelta(days=n)


def date_ago(n: int, now: datetime = NOW) -> date:
    return days_ago(n, now).date()


_UNSET = object()


def phone_of(reporter_id: int) -> str:
    """Test reporter n's own WhatsApp number."""
    return f"+2376{reporter_id:08d}"


def key_of(phone: str) -> str:
    """Stand-in for reporter_key_for(): any injective phone -> key mapping will do."""
    return f"key:{phone}"


def report(report_id: int, status: str = "approved", reporter_id=_UNSET, **kw) -> ReportFacts:
    """A report by test reporter `reporter_id` (an int, or None for no reporter at all).

    By default each report has its own reporter, so reporters are independent. The key is
    derived from the reporter's number (and survives overriding reporter_phone=None, i.e.
    erasure); subject_keys are derived from subject_phones, as the service does.
    """
    if reporter_id is _UNSET:
        reporter_id = 1000 + report_id
    own_phone = None if reporter_id is None else phone_of(reporter_id)
    kw.setdefault("reporter_phone", own_phone)
    kw.setdefault("reporter_key", key_of(own_phone) if own_phone else "")
    kw.setdefault("subject_keys", frozenset(key_of(p) for p in kw.get("subject_phones", ())))
    kw.setdefault("submitted_at", days_ago(30))
    if status == "approved":
        kw.setdefault("decided_at", days_ago(20))
    return ReportFacts(report_id=report_id, status=status, **kw)


def approved(report_id: int, age_days: int = 20, reporter_id=_UNSET, **kw) -> ReportFacts:
    """An approved report decided `age_days` ago and submitted a day before that."""
    kw.setdefault("decided_at", days_ago(age_days))
    kw.setdefault("submitted_at", days_ago(age_days + 1))
    return report(report_id, "approved", reporter_id, **kw)
