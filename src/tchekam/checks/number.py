"""Number check (F1): one reply message per checked number.

The reply is built only from the public band result, the month and year of the last report,
and masked names. Reporter identities, summaries, amounts and rejected reports never enter it.
"""

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.conversations.router import Context, Reply, register_intent
from tchekam.i18n import month_year, t
from tchekam.identifiers.models import PhoneNumber, get_or_create_phone
from tchekam.identifiers.names import mask_name
from tchekam.identifiers.phone import format_cm_number
from tchekam.reports.models import Report, ReportSubject
from tchekam.reputation.facts import Band, BandResult
from tchekam.reputation.service import band_for_phone

from .limits import check_allowed
from .models import CheckLog

MAX_NUMBERS = 3
MAX_NAMES = 3


def _linked_names(e164: str, counted_report_ids: frozenset[int]) -> list[str]:
    """Masked payee names from the reports the band counted, where number and name are confirmed."""
    # Restricting to the band's own report set keeps decay and appeal exclusions in force.
    # One filter() call, so "confirmed" applies to the same subject row as the phone match.
    reports = Report.objects.filter(
        pk__in=counted_report_ids, subjects__phone_number__e164=e164, subjects__confirmed=True
    )
    subjects = (
        ReportSubject.objects.filter(report__in=reports, account_name__isnull=False, confirmed=True)
        .select_related("account_name")
        .order_by("-report__decided_at", "pk")
    )
    seen: dict[str, str] = {}
    for s in subjects:
        seen.setdefault(s.account_name.normalized, mask_name(s.account_name.display_raw))
    return list(seen.values())[:MAX_NAMES]


def _checks_this_month(e164: str) -> int:
    month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return CheckLog.objects.filter(
        kind=CheckLog.Kind.NUMBER, subject_ref=e164, created_at__gte=month_start
    ).count()


def _band_lines(result: BandResult, lang: str | None) -> list[str]:
    band = result.band
    if band == Band.GREEN:
        return [t("check.number.green", lang)]
    if band == Band.YELLOW:
        n = result.pending_count
        return [t("check.number.yellow_one" if n == 1 else "check.number.yellow", lang, n=n)]

    k = result.independent_reporters
    if band == Band.RED:
        if result.single_report_with_proof:
            lines = [t("check.number.red_proof", lang)]
        else:
            lines = [t("check.number.red", lang, k=k)]
    elif k >= 1:
        lines = [t("check.number.orange_one" if k == 1 else "check.number.orange", lang, k=k)]
    else:
        # Reviewed reports exist but none counts as an independent reporter (e.g. erased).
        lines = [t("check.number.orange_reviewed", lang)]
    if result.last_report_date:
        when = month_year(result.last_report_date, lang)
        lines.append(t("check.number.last_report", lang, when=when))
    return lines


def _check_one(ctx: Context, e164: str) -> Reply:
    lang = ctx.lang
    phone = get_or_create_phone(e164)
    PhoneNumber.objects.filter(pk=phone.pk).update(check_count=F("check_count") + 1)
    result = band_for_phone(e164)
    CheckLog.objects.create(
        user=ctx.user, kind=CheckLog.Kind.NUMBER, subject_ref=e164, result_band=result.band.value
    )

    number = format_cm_number(e164)
    if phone.operator == "Unknown":
        lines = [t("check.number.header_no_operator", lang, number=number)]
    else:
        lines = [t("check.number.header", lang, number=number, operator=phone.operator)]
    lines += _band_lines(result, lang)
    if result.under_appeal and result.band != Band.GREEN:
        lines.append(t("check.number.under_appeal", lang))
    if result.band in (Band.ORANGE, Band.RED):
        if names := _linked_names(e164, result.counted_report_ids):
            lines.append(t("check.number.names", lang, names=", ".join(names)))
    if (n := _checks_this_month(e164)) > 1:
        lines.append(t("check.number.checked_times", lang, n=n))
    lines += [t("check.number.tips", lang), t("check.number.footer", lang)]
    return Reply("\n".join(lines))


def _check_if_allowed(ctx: Context, e164: str) -> Reply | None:
    """Quota check and log write under one row lock, so parallel messages cannot overshoot."""
    with transaction.atomic():
        BotUser.objects.select_for_update().get(pk=ctx.user.pk)
        if not check_allowed(ctx.user):
            return None
        return _check_one(ctx, e164)


def handle_check_number(ctx: Context) -> list[Reply]:
    numbers = ctx.extra.get("numbers", [])
    replies: list[Reply] = []
    for e164 in numbers[:MAX_NUMBERS]:
        reply = _check_if_allowed(ctx, e164)
        if reply is None:
            replies.append(Reply(t("check.limit_reached", ctx.lang)))
            return replies  # nothing more is checked or logged once the quota is used
        replies.append(reply)
    if len(numbers) > MAX_NUMBERS:
        replies.append(Reply(t("check.number.too_many", ctx.lang)))
    return replies


def register() -> None:
    register_intent("check_number", handle_check_number)
