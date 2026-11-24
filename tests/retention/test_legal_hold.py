"""Legal hold (ADR-013) blocks every deletion type: each rule, each kind of hold."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db.models import ProtectedError

from tchekam.appeals.models import Appeal
from tchekam.checks.models import CheckLog
from tchekam.core.models import AuditLog
from tchekam.imaging.models import ImageSighting
from tchekam.messaging.models import InboundEvent
from tchekam.reports.models import Evidence, ModerationDecision, PendingNotification, Report
from tchekam.retention import rules
from tchekam.retention.models import TrainingSample

from .builders import NOW, appeal, check_log, event, group_sighting, phone, report, set_time, user

pytestmark = pytest.mark.django_db

OLD = NOW - timedelta(days=5 * 365)


def _hold(obj):
    type(obj).objects.filter(pk=obj.pk).update(legal_hold=True)


def _held_report(status, hold, **kw):
    if hold == "subject_user":  # the seller's number is a held user's own number
        held = user(legal_hold=True)
        seller = phone(held.wa_phone)
    else:
        seller = phone()
    r = report(status, seller=seller, **kw)
    target = {"report": r, "user": r.reporter, "number": seller, "evidence": r.evidence.first()}
    if hold in target:
        _hold(target[hold])
    return r


def _report_case(status, **kw):
    def make(hold):
        r = _held_report(status, hold, **kw)
        return lambda: Report.objects.filter(pk=r.pk, story_text__gt="").exists()

    return make


def _webhook(hold):
    sender_user = user()
    digits = sender_user.wa_phone.lstrip("+")
    e = event(OLD, sender=digits)
    if hold == "user":
        _hold(sender_user)
    else:
        _hold(phone(sender_user.wa_phone))
    return lambda: InboundEvent.objects.filter(pk=e.pk).exists()


def _group_event(hold):
    poster = user()
    e = event(OLD, group=True, sender=poster.wa_phone.lstrip("+"))
    _hold(poster if hold == "user" else phone(poster.wa_phone))
    return lambda: "scrubbed" not in InboundEvent.objects.get(pk=e.pk).payload["data"]["messages"]


def _notification(hold):
    r = _held_report("rejected", hold)
    mod = get_user_model().objects.create_user(f"mod-{r.pk}")
    d = ModerationDecision.objects.create(report=r, moderator=mod, action="reject")
    n = PendingNotification.objects.create(user=r.reporter, report=r, decision=d, delivered_at=OLD)
    return lambda: PendingNotification.objects.filter(pk=n.pk).exists()


def _appeal_case(status, **kw):
    def make(hold):
        number, appellant = phone(), user()
        a = appeal(status, appellant=appellant, number=number, **kw)
        set_time(Appeal, a.pk, created_at=OLD)
        _hold(appellant if hold == "user" else number)
        return lambda: Appeal.objects.filter(pk=a.pk, statement__gt="").exists()

    return make


def _training(hold):
    owner = user(training_opt_in=False)
    s = TrainingSample.objects.create(user=owner, audio_key="training/x", mimetype="audio/ogg")
    _hold(owner)
    return lambda: TrainingSample.objects.filter(pk=s.pk).exists()


def _check_log(hold):
    checker = user()
    number = phone()
    log = check_log(OLD, subject_ref=number.e164, user=checker)
    _hold(checker if hold == "user" else number)
    return lambda: CheckLog.objects.filter(pk=log.pk).exists()


def _sighting(hold):
    poster = phone()
    s = group_sighting(OLD, poster)
    if hold == "user":
        owner = user()
        ImageSighting.objects.filter(pk=s.pk).update(bot_user=owner)
        _hold(owner)
    else:
        _hold(poster)
    return lambda: ImageSighting.objects.filter(pk=s.pk).exists()


def _trust(hold):
    """A snapshot whose reports are gone, for a person (or number) now on hold."""
    from tchekam.reports.keys import reporter_key_for
    from tchekam.retention.models import ReporterTrust

    held = user() if hold == "user" else phone()
    _hold(held)
    number = held.wa_phone if hold == "user" else held.e164
    row = ReporterTrust.objects.create(reporter_key=reporter_key_for(number), trust_weight=0.2)
    return lambda: ReporterTrust.objects.filter(pk=row.pk).exists()


def _group_intake_scrub(hold):
    """The immediate scrub in groups intake (not a rule) respects the hold too."""
    poster = user()
    e = event(NOW, group=True, sender=poster.wa_phone.lstrip("+"))
    _hold(poster if hold == "user" else phone(poster.wa_phone))
    return lambda: "scrubbed" not in InboundEvent.objects.get(pk=e.pk).payload["data"]["messages"]


def _run_group_intake(now):
    from tchekam.groups.intake import ingest_group_image

    for e in InboundEvent.objects.all():
        ingest_group_image(e.message_id)  # no PartnerGroup: not ingested, then scrubbed
    return 0


# Actions that are not retention rules but must respect a hold as well.
NOT_RULES = {"group_intake_scrub": _run_group_intake}

REPORT_HOLDS = ("report", "user", "number", "evidence", "subject_user")
CASES = [
    *[("webhooks", _webhook, h) for h in ("user", "number")],
    *[("group_events", _group_event, h) for h in ("user", "number")],
    *[("notifications", _notification, h) for h in REPORT_HOLDS],
    *[("drafts", _report_case("draft", last_activity_at=OLD), h) for h in REPORT_HOLDS],
    *[("rejected_evidence", _report_case("rejected", decided_at=OLD), h) for h in REPORT_HOLDS],
    *[("approved_evidence", _report_case("approved", decided_at=OLD), h) for h in REPORT_HOLDS],
    *[("merged_evidence", _report_case("merged", decided_at=OLD), h) for h in REPORT_HOLDS],
    *[("reporter_trust", _trust, h) for h in ("user", "number")],
    *[("group_intake_scrub", _group_intake_scrub, h) for h in ("user", "number")],
    *[("appeal_drafts", _appeal_case("draft"), h) for h in ("user", "number")],
    *[
        ("appeal_statements", _appeal_case("approved", decided_at=OLD), h)
        for h in ("user", "number")
    ],
    ("training_samples", _training, "user"),
    *[("check_logs", _check_log, h) for h in ("user", "number")],
    *[("group_sightings", _sighting, h) for h in ("user", "number")],
]


def test_every_rule_has_a_legal_hold_case():
    covered = {name for name, _, _ in CASES} | {"rejected_records"}
    assert covered == {rule.name for rule in rules.RULES} | set(NOT_RULES)


@pytest.mark.parametrize(("name", "make", "hold"), CASES, ids=[f"{n}-{h}" for n, _, h in CASES])
def test_legal_hold_blocks_the_rule(name, make, hold):
    still_there = make(hold)
    action = NOT_RULES.get(name) or getattr(rules, name)

    assert action(NOW) == 0
    assert still_there()


@pytest.mark.parametrize("hold", ["report", "user", "number", "subject_user"])
def test_a_hold_placed_after_minimisation_blocks_deleting_the_rejected_record(
    hold, django_capture_on_commit_callbacks
):
    seller = phone()
    r = report("rejected", seller=seller, decided_at=OLD)
    with django_capture_on_commit_callbacks(execute=True):
        assert rules.rejected_evidence(NOW) == 1
    r.refresh_from_db()
    assert not r.subjects.exists()  # only subject_phone_keys are left
    if hold == "subject_user":  # the seller's number turns out to be a user, now held
        user(wa_phone=seller.e164, legal_hold=True)
    else:
        _hold({"report": r, "user": r.reporter, "number": seller}[hold])

    assert rules.rejected_records(NOW) == 0
    assert Report.objects.filter(pk=r.pk).exists()


def test_held_report_keeps_evidence_blobs(object_store):
    r = _held_report("rejected", "report", decided_at=OLD)
    key = r.evidence.get().object_key

    rules.rejected_evidence(NOW)

    assert object_store.exists(key) and Evidence.objects.filter(report=r).exists()


def test_a_held_user_cannot_be_deleted():
    held = user(legal_hold=True)

    with pytest.raises(ProtectedError):
        held.delete()


def test_a_hold_placed_after_selection_is_still_respected(monkeypatch):
    """The batch is re-checked under the row lock, so a hold set in between wins."""
    r = report("draft", last_activity_at=OLD)
    original = rules.drafts.candidates
    calls = []

    def candidates(now):
        calls.append(1)
        if len(calls) == 2:  # after the ids were picked, before the batch is processed
            Report.objects.filter(pk=r.pk).update(legal_hold=True)
        return original(now)

    monkeypatch.setattr(rules.drafts, "candidates", candidates)

    assert rules.drafts(NOW) == 0
    assert Report.objects.filter(pk=r.pk).exists()


def test_audit_log_is_never_touched():
    old = AuditLog.objects.create(action="report.transition", metadata={})
    # created_at cannot be back-dated (append-only), so run the rules far in the future instead.
    for rule in rules.RULES:
        rule(NOW + timedelta(days=100 * 365))

    assert AuditLog.objects.filter(pk=old.pk).exists()


@pytest.mark.parametrize("group", [False, True])
def test_a_sender_hold_spares_only_that_senders_events(group):
    held = user(legal_hold=True)
    kept = event(OLD, sender=held.wa_phone.lstrip("+"), group=group)
    other = event(OLD, sender="237699999999", group=group)
    rule = rules.group_events if group else rules.webhooks

    assert rule(NOW) == 1
    if group:
        assert "scrubbed" in InboundEvent.objects.get(pk=other.pk).payload["data"]["messages"]
    else:
        assert not InboundEvent.objects.filter(pk=other.pk).exists()
    assert InboundEvent.objects.filter(pk=kept.pk).exists()


def test_a_hold_on_one_report_spares_only_that_report():
    held = _held_report("draft", "number", last_activity_at=OLD)
    other = report("draft", last_activity_at=OLD)

    assert rules.drafts(NOW) == 1
    assert Report.objects.filter(pk=held.pk).exists()
    assert not Report.objects.filter(pk=other.pk).exists()
