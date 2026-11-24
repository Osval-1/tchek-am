"""Moderator edits and decisions on a report.

Both entry points lock the Report row, check the stale-form token, change everything in one
transaction, and schedule cache invalidation for after commit (a recompute before commit could
re-cache the old data). Nothing here logs or audits names or numbers.
"""

import hashlib
import hmac
from dataclasses import dataclass, field

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.http import QueryDict
from django.utils import timezone

from tchekam.core.audit import audit
from tchekam.core.tasks import enqueue
from tchekam.identifiers.models import get_or_create_account_name, get_or_create_phone
from tchekam.reports.models import ModerationDecision, Report, ReportSubject
from tchekam.reports.transitions import InvalidTransition, check_transition
from tchekam.reports.weighting import recompute as recompute_trust
from tchekam.reputation.service import invalidate_phone, invalidate_report

from .forms import DecisionForm, EditForm, error_messages

EDITABLE_STATUSES = frozenset({"pending", "needs_info", "approved"})
# Action -> status it moves the report to.
TARGET_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "need_info": "needs_info",
    "merge": "merged",
    "reopen": "pending",
}
_SCALAR_FIELDS = ("has_payment_proof", "scam_type", "incident_date", "amount_xaf", "summary_final")


class ModerationError(Exception):
    """A problem the moderator can fix; carries messages safe to show."""

    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages))
        self.messages = messages


class StaleReport(Exception):
    """The report changed since the moderator loaded the page."""


def state_token(report: Report) -> str:
    """Fingerprint of everything a moderator's decision depends on, to refuse stale forms."""
    subjects = sorted(
        report.subjects.values_list(
            "id", "confirmed", "phone_number_id", "account_name_id", "image_id"
        )
    )
    raw = repr(
        (
            report.status,
            report.last_activity_at.isoformat(),
            report.has_payment_proof,
            report.scam_type,
            report.incident_date,
            report.amount_xaf,
            report.summary_final,
            subjects,
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _lock(report_id: int) -> Report:
    return Report.objects.select_for_update().get(pk=report_id)


def _check_token(report: Report, token: str) -> None:
    if not hmac.compare_digest(state_token(report), token or ""):
        raise StaleReport


@dataclass
class _Edit:
    fields: list[str] = field(default_factory=list)
    phones: set[str] = field(default_factory=set)

    @property
    def changed(self) -> bool:
        return bool(self.fields)


def _invalidate_after_commit(report: Report, phones: set[str]) -> None:
    def run() -> None:
        invalidate_report(report)
        # Removed subjects are gone from the DB, so invalidate_report cannot find their numbers.
        for e164 in phones:
            invalidate_phone(e164)

    transaction.on_commit(run)


def _apply_edits(report: Report, post: QueryDict, actor: AbstractBaseUser, ip: str | None) -> _Edit:
    """Apply the edit fields of a POST to a locked, editable report. Raises ModerationError."""
    form = EditForm(post)
    if not form.is_valid():
        raise ModerationError(error_messages(form))
    data = form.cleaned_data
    edit = _Edit()

    scalar_changes = []
    for name in _SCALAR_FIELDS:
        value = data[name].strip() if name == "summary_final" else data[name]
        if getattr(report, name) != value:
            setattr(report, name, value)
            scalar_changes.append(name)

    subject_changes: set[str] = set()
    subjects = list(report.subjects.select_related("phone_number"))
    for s in subjects:
        phone = s.phone_number.e164 if s.phone_number_id else None
        if post.get(f"remove_{s.pk}"):
            s.delete()  # clears s.pk, which the duplicate check below relies on
            subject_changes.add("subjects.removed")
            if phone:
                edit.phones.add(phone)
            continue
        confirmed = bool(post.get(f"confirmed_{s.pk}"))
        if s.confirmed != confirmed:
            s.confirmed = confirmed
            s.save(update_fields=["confirmed"])
            subject_changes.add("subjects.confirmed")
            if phone:
                edit.phones.add(phone)

    if data["add_phone"]:
        phone_obj = get_or_create_phone(data["add_phone"])
        if phone_obj is None:
            raise ModerationError(["Not a valid Cameroonian phone number."])
        existing = next(
            (s for s in subjects if s.pk is not None and s.phone_number_id == phone_obj.pk), None
        )
        if existing is None:
            ReportSubject.objects.create(
                report=report,
                phone_number=phone_obj,
                role=ReportSubject.Role.SELLER,
                source=ReportSubject.Source.MODERATOR,
                confirmed=True,
            )
            subject_changes.add("subjects.added")
        elif not existing.confirmed or existing.role != ReportSubject.Role.SELLER:
            existing.confirmed = True
            existing.role = ReportSubject.Role.SELLER
            existing.save(update_fields=["confirmed", "role"])
            subject_changes.add("subjects.confirmed")
        edit.phones.add(phone_obj.e164)
    if data["add_name"]:
        account = get_or_create_account_name(data["add_name"], data["add_name_provider"])
        if account is None:  # the form already rejects this; never build an invalid subject
            raise ModerationError(["The payee name is not usable."])
        ReportSubject.objects.create(
            report=report,
            account_name=account,
            role=ReportSubject.Role.PAYEE,
            source=ReportSubject.Source.MODERATOR,
            confirmed=True,
        )
        subject_changes.add("subjects.added")

    edit.fields = scalar_changes + sorted(subject_changes)
    if edit.changed:
        # Bumping last_activity_at also changes the state token: other open forms go stale.
        report.last_activity_at = timezone.now()
        report.save(update_fields=[*scalar_changes, "last_activity_at"])
        # Field names only: values (names, numbers) never go to the audit log.
        audit(actor, "report.edit", report, ip=ip, fields=edit.fields)
        _invalidate_after_commit(report, edit.phones)
    return edit


def save_edits(
    report_id: int, actor: AbstractBaseUser, post: QueryDict, ip: str | None = None
) -> bool:
    """Apply the moderator's edits. Returns False when nothing changed."""
    with transaction.atomic():
        report = _lock(report_id)
        if report.status not in EDITABLE_STATUSES:
            raise ModerationError([f"A {report.status} report cannot be edited."])
        _check_token(report, post.get("state_token", ""))
        return _apply_edits(report, post, actor, ip).changed


def _has_confirmed_seller(report: Report) -> bool:
    return report.subjects.filter(
        phone_number__isnull=False, role=ReportSubject.Role.SELLER, confirmed=True
    ).exists()


def decide(
    report_id: int, actor: AbstractBaseUser, post: QueryDict, ip: str | None = None
) -> ModerationDecision:
    """Apply any edits in the POST, then the decision, atomically."""
    form = DecisionForm(post)
    if not form.is_valid():
        raise ModerationError(error_messages(form))
    action = form.cleaned_data["action"]
    with transaction.atomic():
        report = _lock(report_id)
        # Before the token check, so a double-click gets the precise reason, not "stale".
        try:
            check_transition(report.status, TARGET_STATUS[action])
            if action == "reopen" and report.status != "rejected":
                raise InvalidTransition("only rejected reports can be reopened")
        except InvalidTransition as exc:
            raise ModerationError([f"Not allowed: {exc}."]) from exc
        _check_token(report, post.get("state_token", ""))

        edit = _Edit()
        if post.get("edits") and report.status in EDITABLE_STATUSES:
            edit = _apply_edits(report, post, actor, ip)
        if action == "approve" and not _has_confirmed_seller(report):
            raise ModerationError(["Approval needs at least one confirmed seller phone number."])

        decision = ModerationDecision.objects.create(
            report=report, moderator=actor, action=action, reason=form.reason()
        )
        try:
            if action == "merge":
                target = Report.objects.filter(pk=form.cleaned_data["merge_target"]).first()
                if target is None:
                    raise ModerationError(["The merge target does not exist."])
                report.merge_into(target, actor=actor)
            else:
                # The free text stays on the decision; the audit row only gets the category.
                code = form.cleaned_data["reason_code"] if action == "reject" else action
                report.transition(TARGET_STATUS[action], actor=actor, reason=code)
        except InvalidTransition as exc:
            raise ModerationError([f"Not allowed: {exc}."]) from exc
        # Same transaction as the decision, so the weight never disagrees with report statuses.
        trust_phones = recompute_trust(report.reporter) if report.reporter_id else set()
        if edit.changed or trust_phones:
            # The status signal covers the transition; subject/proof edits and a changed
            # reporter weight (it feeds other numbers' bands) need this explicit call.
            _invalidate_after_commit(report, edit.phones | trust_phones)
        transaction.on_commit(
            lambda: enqueue("notify.report_decided", report_id=report.pk, decision_id=decision.pk)
        )
    return decision
