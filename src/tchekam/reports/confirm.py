"""Report flow, part 2 (F4 steps 3-6): confirm the extracted facts, consent, submit.

Steps (conversation flows): report_confirm -> report_consent -> [report_training_optin] -> submit.
Everything the reporter types here is personal data: nothing in this module is logged.
Subjects the reporter edits are source=user and stay confirmed=False; the moderator confirms
them in review (Issue 13).
"""

import re
from datetime import date

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tchekam.conversations.models import Conversation
from tchekam.conversations.router import Context, Reply, register_flow, say, start_flow
from tchekam.i18n import t
from tchekam.identifiers.models import get_or_create_account_name, get_or_create_phone
from tchekam.identifiers.phone import format_cm_number
from tchekam.reports import codes, limits, parsing
from tchekam.reports.flow import (
    CANCEL_WORDS,
    CONFIRM,
    REPORT_TTL,
    cancel,
    current_draft,
    item_counts_text,
    lost_draft,
    parse_details,
    touch,
    user_command,
)
from tchekam.reports.models import Evidence, Report, ReportSubject

CONSENT = "report_consent"
OPTIN = "report_training_optin"
OK_WORDS = frozenset({"ok", "oui", "yes", "confirmer", "confirm"})
MAX_SELLERS = 3
SUMMARY_SHOWN = 300
NONE = "—"


# The list -------------------------------------------------------------------------------------


def render(report: Report, lang: str | None) -> str:
    subjects = report.subjects.select_related("phone_number", "account_name").order_by("pk")
    sellers = [
        format_cm_number(s.phone_number.e164)
        for s in subjects
        if s.role == ReportSubject.Role.SELLER and s.phone_number
    ]
    payees = [
        s.account_name.display_raw
        for s in subjects
        if s.role == ReportSubject.Role.PAYEE and s.account_name
    ]
    summary = report.summary_final or report.summary_ai or t("report.summary_neutral", lang)
    if len(summary) > SUMMARY_SHOWN:
        summary = summary[: SUMMARY_SHOWN - 1].rstrip() + "…"
    amount = f"{report.amount_xaf:,} FCFA".replace(",", " ") if report.amount_xaf else NONE
    when = report.incident_date.strftime("%d/%m/%Y") if report.incident_date else NONE
    return t(
        "report.confirm.list",
        lang,
        sellers=", ".join(sellers) or NONE,
        payees=", ".join(payees) or NONE,
        amount=amount,
        date=when,
        summary=summary,
        items=item_counts_text(report.pk, lang),
    )


def enter(conv: Conversation, report: Report, lang: str | None) -> str:
    """Move the conversation to the confirm step; returns the list to send."""
    start_flow(conv, CONFIRM, state={"report_id": report.pk}, ttl=REPORT_TTL)
    return render(report, lang)


# Edits ----------------------------------------------------------------------------------------
# Each takes the typed value and returns an error key, or None once the change is applied.


def _edit_sellers(report: Report, value: str) -> str | None:
    numbers = parse_details(value)[0][:MAX_SELLERS]
    phones = [p for e164 in numbers if (p := get_or_create_phone(e164))]
    if not phones:
        return "report.confirm.bad_number"
    with transaction.atomic():
        report.subjects.filter(role=ReportSubject.Role.SELLER, phone_number__isnull=False).delete()
        for phone in phones:
            ReportSubject.objects.create(
                report=report,
                phone_number=phone,
                role=ReportSubject.Role.SELLER,
                source=ReportSubject.Source.USER,
                confirmed=False,
            )
    return None


def _edit_payees(report: Report, value: str) -> str | None:
    names = [] if parsing.is_clear(value) else parsing.parse_names(value)
    if names is None:
        return "report.confirm.bad_name"
    accounts = list(
        {a.pk: a for n in names if (a := get_or_create_account_name(n, "unknown"))}.values()
    )
    with transaction.atomic():
        report.subjects.filter(role=ReportSubject.Role.PAYEE, account_name__isnull=False).delete()
        for account in accounts:
            ReportSubject.objects.create(
                report=report,
                account_name=account,
                role=ReportSubject.Role.PAYEE,
                source=ReportSubject.Source.USER,
                confirmed=False,
            )
    return None


def _edit_amount(report: Report, value: str) -> str | None:
    amount = None if parsing.is_clear(value) else parsing.parse_amount(value)
    if amount is None and not parsing.is_clear(value):
        return "report.confirm.bad_amount"
    report.amount_xaf = amount
    report.save(update_fields=["amount_xaf"])
    return None


def _edit_date(report: Report, value: str) -> str | None:
    when: date | None = None
    if not parsing.is_clear(value):
        when = parsing.parse_date(value)
        if when is None:
            return "report.confirm.bad_date"
    report.incident_date = when
    report.save(update_fields=["incident_date"])
    return None


def _edit_summary(report: Report, value: str) -> str | None:
    summary = None if parsing.is_clear(value) else parsing.parse_summary(value)
    if summary is None:
        return "report.confirm.bad_summary"
    report.summary_final = summary  # summary_ai stays as the model wrote it
    report.save(update_fields=["summary_final"])
    return None


EDITS = {1: _edit_sellers, 2: _edit_payees, 3: _edit_amount, 4: _edit_date, 5: _edit_summary}


def _split_edit(text: str) -> tuple[int, str] | None:
    """'3 25000' -> (3, '25000'); None when it does not start with a field number."""
    parts = text.strip().split(None, 1)
    if not parts:
        return None
    head, value = parts[0].rstrip(".:)"), (parts[1] if len(parts) > 1 else "")
    # ASCII only: str.isdigit() accepts "²" (which int() rejects) and other scripts' digits.
    if not re.fullmatch(r"[1-9]", head):
        return None
    return int(head), value.strip()


def _confirm(ctx: Context) -> list[Reply]:
    report = current_draft(ctx.user, ctx.conversation.state.get("report_id"))
    if report is None:
        return lost_draft(ctx)
    cmd = user_command(ctx)
    if cmd in CANCEL_WORDS:
        return cancel(ctx, report)
    touch(ctx, report)
    if cmd in OK_WORDS:
        return _ok(ctx, report)
    edit = _split_edit(ctx.msg.text or "") if ctx.msg.kind == "text" else None
    if edit is None or edit[0] not in EDITS or not edit[1]:
        return say(ctx, "report.confirm.help")
    error = EDITS[edit[0]](report, edit[1])
    if error:
        return say(ctx, error)
    return [Reply(render(report, ctx.lang))]


# Consent and opt-in ---------------------------------------------------------------------------


def _ok(ctx: Context, report: Report) -> list[Reply]:
    has_seller = report.subjects.filter(
        role=ReportSubject.Role.SELLER, phone_number__isnull=False
    ).exists()
    if not has_seller:  # a report no one can be warned about is never submitted
        return say(ctx, "report.confirm.need_seller")
    if not report.summary_final:
        report.summary_final = report.summary_ai
        report.save(update_fields=["summary_final"])
    start_flow(ctx.conversation, CONSENT, state={"report_id": report.pk}, ttl=REPORT_TTL)
    return _show_terms(ctx)


def _show_terms(ctx: Context) -> list[Reply]:
    warning = t("report.false_warning", ctx.lang)
    return say(ctx, "report.consent.terms", warning=warning, url=settings.TERMS_URL)


def _consent(ctx: Context) -> list[Reply]:
    report = current_draft(ctx.user, ctx.conversation.state.get("report_id"))
    if report is None:
        return lost_draft(ctx)
    cmd = user_command(ctx)
    touch(ctx, report)
    if cmd == "1":
        return _after_consent(ctx, report)
    if cmd == "2" or cmd in CANCEL_WORDS:
        return _decline(ctx, report)
    return _show_terms(ctx)


def _decline(ctx: Context, report: Report) -> list[Reply]:
    # The draft's evidence and story are purged later by retention, as for any withdrawn draft.
    report.transition(Report.Status.WITHDRAWN, reason="consent declined")
    ctx.conversation.reset()
    return say(ctx, "report.consent.declined")


def _set_voice_opt_in(report: Report, value: bool) -> None:
    Evidence.objects.filter(report=report, kind=Evidence.Kind.VOICE).update(training_opt_in=value)


def _after_consent(ctx: Context, report: Report) -> list[Reply]:
    has_voice = report.evidence.filter(kind=Evidence.Kind.VOICE).exists()
    if has_voice and not ctx.user.training_opt_in_asked:
        start_flow(ctx.conversation, OPTIN, state={"report_id": report.pk}, ttl=REPORT_TTL)
        return say(ctx, "report.optin.ask")
    if has_voice:  # decided on an earlier report: the same answer applies
        _set_voice_opt_in(report, ctx.user.training_opt_in)
    return _submit(ctx, report)


def _training_optin(ctx: Context) -> list[Reply]:
    report = current_draft(ctx.user, ctx.conversation.state.get("report_id"))
    if report is None:
        return lost_draft(ctx)
    cmd = user_command(ctx)
    if cmd in CANCEL_WORDS:
        return _decline(ctx, report)
    touch(ctx, report)
    answer = {"1": True, "2": False}.get(cmd)
    if answer is None:
        return say(ctx, "report.optin.ask")
    # Stored on the user and the evidence whatever the report's fate: consent is separate.
    ctx.user.training_opt_in = answer
    ctx.user.training_opt_in_asked = True
    ctx.user.save(update_fields=["training_opt_in", "training_opt_in_asked"])
    _set_voice_opt_in(report, answer)
    return _submit(ctx, report)


# Submit ---------------------------------------------------------------------------------------


def _submit(ctx: Context, report: Report) -> list[Reply]:
    if notice := limits.limit_notice(ctx.user):
        ctx.conversation.reset()  # the draft stays; resume works once the limit lifts
        return say(ctx, notice[0], **notice[1])
    with transaction.atomic():
        row = Report.objects.select_for_update().get(pk=report.pk)
        if row.status != Report.Status.DRAFT:
            return lost_draft(ctx)
        # Subjects can change between OK and now (a re-extraction); never submit without a seller.
        if not row.subjects.filter(
            role=ReportSubject.Role.SELLER, phone_number__isnull=False
        ).exists():
            start_flow(ctx.conversation, CONFIRM, state={"report_id": row.pk}, ttl=REPORT_TTL)
            return say(ctx, "report.confirm.need_seller")
        row.consent_at = timezone.now()
        row.false_report_warning_ack = True
        row.save(update_fields=["consent_at", "false_report_warning_ack"])
        codes.assign_reference(row)
        # Stamps submitted_at, audits, and signals after commit so cached bands refresh.
        row.transition(Report.Status.PENDING, actor=None, reason="submitted by reporter")
    ctx.conversation.reset()
    ctx.enqueue_after("reports.link", report_id=row.pk)
    return say(ctx, "report.submitted", reference=row.reference, hours=settings.REVIEW_ETA_HOURS)


def register() -> None:
    register_flow(CONFIRM, _confirm)
    register_flow(CONSENT, _consent)
    register_flow(OPTIN, _training_optin)
