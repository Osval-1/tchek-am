"""Report flow part 2 (Issue 12): confirm, consent, training opt-in, submit. All fakes."""

import logging
import re
from datetime import date, timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from tchekam.conversations import service
from tchekam.core import tasks as core_tasks
from tchekam.core.audit import AuditLog
from tchekam.i18n import t
from tchekam.reports import codes
from tchekam.reports.limits import daily_limit_reached
from tchekam.reports.models import Evidence, Report
from tchekam.reputation.facts import Band
from tchekam.reputation.service import band_for_phone
from tchekam.speech.base import Transcript

from .conftest import extraction_json

pytestmark = pytest.mark.django_db

EN = "en"
STORY = "I paid the seller on Monday and he stopped answering"
SELLER = "+237677123456"


def _says(texts, key, **fmt):
    return t(key, EN, **fmt) in texts


def _setup(bot, fake_llm, fake_speech, voice=False, **extraction):
    fake_llm.responses["evidence_extraction"] = [extraction_json(**extraction)]
    fake_speech.transcripts = [
        Transcript(text="I paid and got nothing", language="en", confidence=0.9)
    ]
    bot.text("4")
    bot.image()
    if voice:
        bot.audio()
    bot.text(STORY)
    done = bot.text("DONE")
    report = Report.objects.filter(reporter=bot.user).latest("pk")
    return report, done[-1]


def _to_confirm(bot, fake_llm, fake_speech, voice=False, **extraction) -> Report:
    report, last = _setup(bot, fake_llm, fake_speech, voice=voice, **extraction)
    assert "📋" in last
    assert bot.conversation.flow == "report_confirm"
    return report


def _to_consent(bot, fake_llm, fake_speech, voice=False, **extraction) -> Report:
    report = _to_confirm(bot, fake_llm, fake_speech, voice=voice, **extraction)
    texts = bot.text("OK")
    assert bot.conversation.flow == "report_consent"
    assert t("report.false_warning", EN) in texts[-1]
    return report


def _subjects(report, role):
    return list(report.subjects.filter(role=role).select_related("phone_number", "account_name"))


# Confirm list ---------------------------------------------------------------------------------


def test_confirm_list_shows_the_extracted_fields(bot, fake_llm, fake_speech):
    _, last = _setup(bot, fake_llm, fake_speech, voice=True)

    assert "1. Seller number(s): +237 677 12 34 56" in last
    assert "2. MoMo / Orange Money name(s): Jean Dupont" in last
    assert "3. Amount: 25 000 FCFA" in last
    assert "4. Date: 20/11/2026" in last
    assert "5. Summary: The buyer paid for a phone that was never delivered." in last
    assert "1 image, 1 voice note" in last


def test_long_summary_is_shortened_in_the_list(bot, fake_llm, fake_speech):
    _, last = _setup(bot, fake_llm, fake_speech, summary="A" * 400)

    line = next(ln for ln in last.splitlines() if ln.startswith("5. Summary:"))
    assert len(line.removeprefix("5. Summary: ")) == 300


def test_happy_path_submits(bot, fake_llm, fake_speech, monkeypatch):
    queued = []
    original = service.enqueue
    monkeypatch.setattr(
        service, "enqueue", lambda name, **kw: (queued.append((name, kw)), original(name, **kw))
    )
    report = _to_consent(bot, fake_llm, fake_speech, voice=True)

    asked = bot.text("1")
    assert asked == [t("report.optin.ask", EN)]
    assert bot.conversation.flow == "report_training_optin"
    done = bot.text("1")

    report.refresh_from_db()
    assert report.status == Report.Status.PENDING
    assert re.fullmatch(r"TA-[A-HJ-NP-Z2-9]{5}", report.reference)
    assert done == [t("report.submitted", EN, reference=report.reference, hours=24)]
    assert "24 hours" in done[0]
    assert report.consent_at is not None
    assert report.false_report_warning_ack is True
    assert report.submitted_at is not None
    assert report.summary_final == report.summary_ai
    conv = bot.conversation
    assert (conv.flow, conv.state, conv.expires_at) == ("idle", {}, None)
    bot.user.refresh_from_db()
    assert bot.user.training_opt_in is True and bot.user.training_opt_in_asked is True
    voice = report.evidence.get(kind=Evidence.Kind.VOICE)
    assert voice.training_opt_in is True
    assert ("reports.link", {"report_id": report.pk}) in queued
    entry = AuditLog.objects.get(action="report.transition", object_id=str(report.pk))
    assert entry.actor is None


# Edits ----------------------------------------------------------------------------------------


def test_edit_seller_number_replaces_the_ai_subject(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    reply = bot.text("1 655 11 22 33")

    sellers = _subjects(report, "seller")
    assert [(s.phone_number.e164, s.source, s.confirmed) for s in sellers] == [
        ("+237655112233", "user", False)
    ]
    assert "1. Seller number(s): +237 655 11 22 33" in reply[0]
    assert bot.conversation.flow == "report_confirm"


def test_edit_seller_accepts_several_numbers_up_to_three(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    bot.text("1 677123456, 655112233 650112233 699000111 677123456")

    assert {s.phone_number.e164 for s in _subjects(report, "seller")} == {
        "+237677123456",
        "+237655112233",
        "+237650112233",
    }


def test_edit_seller_accepts_a_landline_typed_alone(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    bot.text("1 222 23 45 67")

    assert [s.phone_number.e164 for s in _subjects(report, "seller")] == ["+237222234567"]


def test_invalid_seller_number_reprompts_and_changes_nothing(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    reply = bot.text("1 12345")

    assert reply == [t("report.confirm.bad_number", EN)]
    sellers = _subjects(report, "seller")
    assert [(s.phone_number.e164, s.source) for s in sellers] == [(SELLER, "ai")]


def test_edit_payee_names_replace_and_clear(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    reply = bot.text("2 Marie Ngo; Paul Eto\nAlex Bih, Extra Fourth")

    payees = _subjects(report, "payee")
    assert sorted(p.account_name.display_raw for p in payees) == [
        "Alex Bih",
        "Marie Ngo",
        "Paul Eto",
    ]
    assert {(p.source, p.confirmed, p.account_name.provider) for p in payees} == {
        ("user", False, "unknown")
    }
    assert "Marie Ngo" in reply[0]

    assert bot.text("2 x" + "y" * 70) == [t("report.confirm.bad_name", EN)]
    assert len(_subjects(report, "payee")) == 3

    bot.text("2 aucun")
    assert _subjects(report, "payee") == []
    assert "2. MoMo / Orange Money name(s): —" in bot.text("2 -")[0]


def test_edit_amount(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    assert "3. Amount: 1 250 000 FCFA" in bot.text("3 1.250.000 FCFA")[0]
    report.refresh_from_db()
    assert report.amount_xaf == 1_250_000
    for bad in ["3 0", "3 100000001", "3 lots"]:
        assert bot.text(bad) == [t("report.confirm.bad_amount", EN)]
    report.refresh_from_db()
    assert report.amount_xaf == 1_250_000
    assert "3. Amount: —" in bot.text("3 -")[0]
    report.refresh_from_db()
    assert report.amount_xaf is None


def test_edit_date(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    assert "4. Date: 12/03/2026" in bot.text("4 12 March 2026")[0]
    report.refresh_from_db()
    assert report.incident_date == date(2026, 3, 12)
    future = (timezone.localdate() + timedelta(days=1)).strftime("%d/%m/%Y")
    for bad in [f"4 {future}", "4 01/01/2015", "4 32/01/2026", "4 someday"]:
        assert bot.text(bad) == [t("report.confirm.bad_date", EN)]
    report.refresh_from_db()
    assert report.incident_date == date(2026, 3, 12)
    bot.text("4 -")
    report.refresh_from_db()
    assert report.incident_date is None


def test_edit_summary_keeps_the_ai_summary(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    reply = bot.text("5 He never sent the phone\x07‮ I paid 25000")

    report.refresh_from_db()
    assert report.summary_final == "He never sent the phone I paid 25000"
    assert report.summary_ai == "The buyer paid for a phone that was never delivered."
    assert "5. Summary: He never sent the phone I paid 25000" in reply[0]
    assert bot.text("5 " + "z" * 501) == [t("report.confirm.bad_summary", EN)]
    assert bot.text("5 -") == [t("report.confirm.bad_summary", EN)]


@pytest.mark.parametrize("text", ["9 hello", "0 hello", "banana", "3", "hello 3"])
def test_unknown_field_or_unparseable_input_shows_help(bot, fake_llm, fake_speech, text):
    _to_confirm(bot, fake_llm, fake_speech)

    assert bot.text(text) == [t("report.confirm.help", EN)]
    assert bot.conversation.flow == "report_confirm"


def test_non_text_in_confirm_shows_help(bot, fake_llm, fake_speech):
    _to_confirm(bot, fake_llm, fake_speech)

    assert bot.video() == [t("report.confirm.help", EN)]


def test_edits_never_confirm_subjects_or_touch_status(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    bot.text("1 655112233")
    bot.text("2 Marie Ngo")

    assert not report.subjects.filter(confirmed=True).exists()
    report.refresh_from_db()
    assert report.status == Report.Status.DRAFT


# OK and cancel --------------------------------------------------------------------------------


def test_ok_without_a_seller_number_is_refused(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech, phone_numbers=[])
    # the extraction found nothing to ask for: drop the AI number, then try OK
    report.subjects.filter(role="seller").delete()

    reply = bot.text("OK")

    assert reply == [t("report.confirm.need_seller", EN)]
    assert bot.conversation.flow == "report_confirm"
    bot.text("1 677123456")
    assert bot.text("ok")[-1].startswith("Before sending")


def test_cancel_in_confirm_withdraws(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    assert bot.text("CANCEL") == [t("report.cancelled", EN)]

    report.refresh_from_db()
    assert report.status == Report.Status.WITHDRAWN
    assert bot.conversation.flow == "idle"


# Consent --------------------------------------------------------------------------------------


def test_consent_terms_content(bot, fake_llm, fake_speech):
    _to_confirm(bot, fake_llm, fake_speech)

    text = bot.text("OK")[0]

    assert "true to the best of my knowledge" in text
    assert "reviewed by the Tchek-Am moderator" in text
    assert "technical service providers (AI analysis and voice-note transcription)" in text
    assert "never shown to buyers" in text
    assert "never made public" in text
    assert t("report.false_warning", EN) in text
    assert settings.TERMS_URL in text
    assert "1 = I agree, 2 = cancel" in text


def test_declining_consent_withdraws_the_draft(bot, fake_llm, fake_speech):
    report = _to_consent(bot, fake_llm, fake_speech, voice=True)

    assert bot.text("2") == [t("report.consent.declined", EN)]

    report.refresh_from_db()
    assert report.status == Report.Status.WITHDRAWN
    assert report.consent_at is None and report.reference is None
    assert bot.conversation.flow == "idle"
    bot.user.refresh_from_db()
    assert bot.user.training_opt_in_asked is False


def test_other_replies_show_the_terms_again(bot, fake_llm, fake_speech):
    _to_consent(bot, fake_llm, fake_speech)

    again = bot.text("maybe")

    assert t("report.false_warning", EN) in again[0]
    assert bot.conversation.flow == "report_consent"


# Training opt-in ------------------------------------------------------------------------------


def test_training_opt_in_is_independent_of_consent_and_asked_once(bot, fake_llm, fake_speech):
    _to_consent(bot, fake_llm, fake_speech, voice=True)
    bot.text("1")
    bot.text("2")  # no to training; the report is still submitted
    bot.user.refresh_from_db()
    assert (bot.user.training_opt_in, bot.user.training_opt_in_asked) == (False, True)
    assert Report.objects.filter(reporter=bot.user, status="pending").count() == 1
    assert not Evidence.objects.filter(training_opt_in=True).exists()

    # A second report with a voice note: not asked again, the earlier answer is applied.
    BotUserModel = type(bot.user)
    BotUserModel.objects.filter(pk=bot.user.pk).update(training_opt_in=True)
    fake_llm.responses["evidence_extraction"] = [extraction_json()]
    fake_speech.transcripts = [Transcript(text="again I paid", language="en", confidence=0.9)]
    bot.text("4")
    bot.audio(b"second-voice")
    bot.text("DONE")
    bot.text("OK")
    done = bot.text("1")

    assert _says(
        done, "report.submitted", reference=Report.objects.latest("pk").reference, hours=24
    )
    assert Evidence.objects.get(kind="voice", report=Report.objects.latest("pk")).training_opt_in


def test_optin_not_asked_without_voice_evidence(bot, fake_llm, fake_speech):
    _to_consent(bot, fake_llm, fake_speech, voice=False)

    done = bot.text("1")

    assert done[0].startswith("✅")
    bot.user.refresh_from_db()
    assert bot.user.training_opt_in_asked is False


def test_optin_unclear_answer_asks_again(bot, fake_llm, fake_speech):
    _to_consent(bot, fake_llm, fake_speech, voice=True)
    bot.text("1")

    assert bot.text("hmm") == [t("report.optin.ask", EN)]
    assert bot.conversation.flow == "report_training_optin"


# Limits and blocking --------------------------------------------------------------------------


def _submitted(user, n, when=None):
    for _ in range(n):
        Report.objects.create(reporter=user, status="pending", submitted_at=when or timezone.now())


def test_fourth_submission_in_a_day_is_refused(bot, fake_llm, fake_speech):
    _to_consent(bot, fake_llm, fake_speech)
    _submitted(bot.user, 3)

    reply = bot.text("1")

    assert reply == [t("report.limit_reached", EN, n=3)]
    assert bot.conversation.flow == "idle"
    assert Report.objects.filter(reporter=bot.user, status="draft").count() == 1


def test_early_refusal_at_the_start_of_a_report(bot):
    _submitted(bot.user, 3)

    assert bot.text("4") == [t("report.limit_reached", EN, n=3)]
    assert bot.conversation.flow == "idle"
    assert not Report.objects.filter(reporter=bot.user, status="draft").exists()


def test_limit_respects_settings_and_ignores_withdrawn(bot, settings):
    settings.REPORTS_PER_DAY = 2
    _submitted(bot.user, 1)
    Report.objects.create(reporter=bot.user, status="withdrawn", submitted_at=timezone.now())
    assert not daily_limit_reached(bot.user)
    _submitted(bot.user, 1)
    assert daily_limit_reached(bot.user)


def test_limit_counts_the_douala_calendar_day(bot):
    midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    _submitted(bot.user, 3, when=midnight - timedelta(minutes=1))  # yesterday, Douala time
    assert not daily_limit_reached(bot.user)
    _submitted(bot.user, 3, when=midnight + timedelta(seconds=1))
    assert daily_limit_reached(bot.user)


def test_blocked_user_gets_no_reply_and_nothing_is_submitted(bot, fake_llm, fake_speech):
    report = _to_consent(bot, fake_llm, fake_speech)
    type(bot.user).objects.filter(pk=bot.user.pk).update(blocked=True)

    assert bot.text("1") == []

    report.refresh_from_db()
    assert report.status == Report.Status.DRAFT and report.reference is None


# Reference codes ------------------------------------------------------------------------------


def test_reference_collision_is_retried_through_the_flow(bot, fake_llm, fake_speech, monkeypatch):
    Report.objects.create(reporter=bot.user, reference="TA-AAAAA", status="withdrawn")
    codes_iter = iter(["TA-AAAAA", "TA-CCCCC"])
    monkeypatch.setattr(codes, "new_code", lambda: next(codes_iter))
    report = _to_consent(bot, fake_llm, fake_speech)

    done = bot.text("1")

    report.refresh_from_db()
    assert report.reference == "TA-CCCCC"
    assert "TA-CCCCC" in done[0]


# Resume ---------------------------------------------------------------------------------------


def test_menu_keeps_the_draft_and_resume_continues(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    bot.text("0")
    assert bot.conversation.flow == "idle"
    assert Report.objects.get(pk=report.pk).status == Report.Status.DRAFT
    resume = bot.text("4")
    assert _says(resume, "report.resume_choice", items="1 image")
    assert bot.text("1") == [t("report.resumed", EN, items="1 image")]

    last = bot.text("DONE")[-1]  # unchanged evidence: no second AI call, same list again
    assert "📋" in last
    assert bot.conversation.flow == "report_confirm"
    assert len(fake_llm.calls) == 1


def test_stale_confirm_resets_and_the_user_resumes(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)
    bot.text("1 655112233")
    conv = bot.conversation
    conv.expires_at = timezone.now() - timedelta(minutes=1)
    conv.save()

    ignored = bot.text("OK")  # not routed to the confirm step any more

    assert bot.conversation.flow == "idle"
    assert not _says(ignored, "report.confirm.need_seller")
    assert Report.objects.get(pk=report.pk).status == Report.Status.DRAFT
    bot.text("4")
    bot.text("1")
    last = bot.text("DONE")[-1]
    assert "+237 655 11 22 33" in last  # the reporter's own edit survived the re-extraction


# End to end: the public band after submit -----------------------------------------------------


def test_number_check_right_after_submit_shows_the_yellow_band(
    bot, fake_llm, fake_speech, django_capture_on_commit_callbacks
):
    # Warm the cache with the "no reports" band first; a stale cache would keep showing it.
    assert band_for_phone(SELLER).band == Band.GREEN
    _to_consent(bot, fake_llm, fake_speech)

    with django_capture_on_commit_callbacks(execute=True):
        bot.text("1")
    checked = bot.text("677 12 34 56")

    assert checked == [t("check.number.yellow_one", EN, n=1)] or any(
        t("check.number.yellow_one", EN, n=1) in text for text in checked
    )
    joined = "\n".join(checked)
    assert "🟡" in joined
    assert (
        "Jean" not in joined and "Dupont" not in joined and "25" not in joined.replace("+237", "")
    )


# Privacy --------------------------------------------------------------------------------------


def test_confirm_flow_logs_no_personal_data(bot, fake_llm, fake_speech, caplog):
    caplog.set_level(logging.DEBUG)
    _to_confirm(bot, fake_llm, fake_speech, voice=True)
    for text in ["1 655112233", "2 Secret Name", "3 31337", "4 12/03/2026", "5 private words here"]:
        bot.text(text)
    bot.text("OK")
    bot.text("1")
    bot.text("1")

    logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ["655112233", "Secret Name", "31337", "private words", "677123456", STORY]:
        assert secret not in logged
    assert core_tasks  # imported for its side effect of registering tasks in this module's run


# Hardening ------------------------------------------------------------------------------------

ODD = [
    "² x",  # superscript two: str.isdigit() is True, int() raises
    "① x",  # circled one
    "١ x",  # Arabic-Indic one
    "１ 677123456",  # full-width one
    "1² x",
    "٣ ٢٥٠٠٠",
    "3 ٢٥٠٠٠",
    "3 ²³",
    "4 ١٢/٠٣/٢٠٢٦",
    "4 12 éè 2026",
    "4 99/99/9999",
    "4 00/00/0000",
    "1 ٦٧٧١٢٣٤٥٦",
    "1 ²²²²²²²²²",
    "‮​",
    "5 😀" * 3,
    "😀",
    "   ",
    "1" * 5000,
    "١",
]


@pytest.mark.parametrize("text", ["² x", "① x", "١ x", "１ x", "0 x", "10 x"])
def test_non_ascii_or_out_of_range_field_numbers_show_help(bot, fake_llm, fake_speech, text):
    report = _to_confirm(bot, fake_llm, fake_speech)

    assert bot.text(text) == [t("report.confirm.help", EN)]

    assert bot.conversation.flow == "report_confirm"
    assert [s.phone_number.e164 for s in _subjects(report, "seller")] == [SELLER]


@pytest.mark.parametrize("step", ["confirm", "consent", "optin"])
def test_odd_unicode_never_breaks_a_step(bot, fake_llm, fake_speech, step):
    if step == "confirm":
        _to_confirm(bot, fake_llm, fake_speech, voice=True)
    else:
        _to_consent(bot, fake_llm, fake_speech, voice=True)
        if step == "optin":
            bot.text("1")
            assert bot.conversation.flow == "report_training_optin"
    flow_name = bot.conversation.flow

    for text in ODD:
        reply = bot.text(text)
        assert reply, text
        assert bot.conversation.flow == flow_name, text


def test_payee_variants_collapse_to_one_subject(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    bot.text("2 Jean Dupont; jean dupont; JEAN DüPONT")

    payees = _subjects(report, "payee")
    assert len(payees) == 1


def test_case_variants_do_not_use_up_the_cap(bot, fake_llm, fake_speech):
    report = _to_confirm(bot, fake_llm, fake_speech)

    bot.text("2 Ann, ann, Bob, bob, Cy, Di")

    assert sorted(p.account_name.display_raw for p in _subjects(report, "payee")) == [
        "Ann",
        "Bob",
        "Cy",
    ]


@pytest.mark.parametrize("name", ["677123456", "Pay 677 12 34 56", "123456 ab", "+237 677123456"])
def test_payee_names_that_are_numbers_are_refused(bot, fake_llm, fake_speech, name):
    report = _to_confirm(bot, fake_llm, fake_speech)

    assert bot.text(f"2 {name}") == [t("report.confirm.bad_name", EN)]

    assert [p.account_name.display_raw for p in _subjects(report, "payee")] == ["Jean Dupont"]


def test_submit_rechecks_the_seller_number(bot, fake_llm, fake_speech):
    report = _to_consent(bot, fake_llm, fake_speech)
    report.subjects.filter(role="seller").delete()  # e.g. a re-extraction between OK and submit

    reply = bot.text("1")

    assert reply == [t("report.confirm.need_seller", EN)]
    conv = bot.conversation
    assert (conv.flow, conv.state) == ("report_confirm", {"report_id": report.pk})
    report.refresh_from_db()
    assert report.status == Report.Status.DRAFT and report.reference is None
    assert report.consent_at is None


def test_cancel_in_training_optin_withdraws(bot, fake_llm, fake_speech):
    report = _to_consent(bot, fake_llm, fake_speech, voice=True)
    bot.text("1")

    assert bot.text("CANCEL") == [t("report.consent.declined", EN)]

    report.refresh_from_db()
    assert report.status == Report.Status.WITHDRAWN
    assert bot.conversation.flow == "idle"
    bot.user.refresh_from_db()
    assert bot.user.training_opt_in_asked is False


def test_huge_digit_input_gets_a_normal_reply_everywhere(bot, fake_llm, fake_speech):
    _to_confirm(bot, fake_llm, fake_speech)
    big = "9" * 5000

    for text in [f"3 {big}", f"4 {big}", f"4 1/1/{big}", f"1 {big}", f"2 {big}", f"5 {big}"]:
        assert bot.text(text), text
    assert bot.conversation.flow == "report_confirm"
    assert bot.text("3 25000")[0].count("25 000 FCFA") == 1


def test_huge_digit_input_in_the_details_step(bot, fake_llm, fake_speech):
    fake_llm.responses["evidence_extraction"] = [
        extraction_json(phone_numbers=[], account_names=[], amounts_xaf=[], evidence_kinds=[])
    ]
    bot.text("4")
    bot.text(STORY)
    bot.text("DONE")
    assert bot.conversation.flow == "report_await_details"

    assert bot.text("677123456 " + "9" * 5000)  # a reply, no exception
    assert bot.conversation.flow == "report_confirm"
