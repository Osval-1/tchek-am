"""Report flow part 1 (Issue 11), end to end through the webhook pipeline with fakes only."""

import hashlib
import logging
from datetime import date, timedelta

import pytest
from django.utils import timezone

from tchekam.core import tasks as core_tasks
from tchekam.i18n import t
from tchekam.messaging.models import InboundEvent
from tchekam.reports import flow, tasks
from tchekam.reports.models import Evidence, Report, ReportSubject
from tchekam.speech.base import Transcript

from .conftest import extraction_json, png

pytestmark = pytest.mark.django_db

STORY = "I paid the seller on Monday and he stopped answering"
TRANSCRIPT = "I sent the money by MoMo and never got the phone"
EN = "en"


def _says(texts, key, **fmt):
    return t(key, EN, **fmt) in texts


def _report(bot) -> Report:
    return Report.objects.get(reporter=bot.user, status=Report.Status.DRAFT)


def _start(bot):
    texts = bot.text("4")
    assert _says(texts, "report.instructions")
    return _report(bot)


def _happy_setup(fake_llm, fake_speech, **extraction):
    fake_llm.responses["evidence_extraction"] = [extraction_json(**extraction)]
    fake_speech.transcripts = [Transcript(text=TRANSCRIPT, language="english", confidence=0.9)]


# (a) happy path ----------------------------------------------------------------------------


def test_happy_path_collects_extracts_and_reaches_confirm(bot, fake_llm, fake_speech, object_store):
    _happy_setup(fake_llm, fake_speech)
    report = _start(bot)
    chat, sms = png("red"), png("blue")

    assert _says(bot.image(chat), "report.ack", items="1 image")
    assert _says(bot.image(sms), "report.ack", items="2 images")
    assert _says(bot.audio(b"voice-bytes"), "report.ack", items="2 images, 1 voice note")
    assert _says(bot.text(STORY), "report.story_noted")
    done = bot.text("DONE")

    assert done[0] == t("report.analysing", EN)
    assert "📋" in done[-1]  # the interim confirmation, sent by the extraction task

    report.refresh_from_db()
    evidence = list(report.evidence.order_by("created_at", "pk"))
    assert [e.kind for e in evidence] == ["chat", "momo_sms", "voice"]
    for item, data in zip(evidence, [chat, sms, b"voice-bytes"], strict=True):
        assert item.object_key.startswith("evidence/")
        assert item.sha256 == hashlib.sha256(data).hexdigest()
        assert item.size_bytes == len(data)
        assert object_store.get(item.object_key) == data
        assert item.source_message_id
    assert evidence[0].ai_extraction == {"kind": "chat"}
    assert evidence[2].transcript == TRANSCRIPT
    assert evidence[2].transcript_confidence == 0.9
    assert fake_speech.calls[0]["language_hint"] == "en"

    assert report.story_text == STORY
    assert report.summary_ai == "The buyer paid for a phone that was never delivered."
    assert report.scam_type == "fake_product"
    assert report.amount_xaf == 25000
    assert report.incident_date == date(2026, 11, 20)
    assert report.ai_extraction["payment_proof_candidate"] is True
    assert "tamper_observations" in report.ai_extraction

    subjects = list(report.subjects.select_related("phone_number", "account_name"))
    assert {(s.role, s.source, s.confirmed) for s in subjects} == {
        ("seller", "ai", False),
        ("payee", "ai", False),
    }
    seller = next(s for s in subjects if s.role == "seller")
    payee = next(s for s in subjects if s.role == "payee")
    assert seller.phone_number.e164 == "+237677123456"
    assert payee.account_name.provider == "momo"

    call = fake_llm.calls[0]
    assert sum(1 for b in call["user_content"] if b["type"] == "image_url") == 2
    prompt = call["user_content"][-1]["text"]
    assert TRANSCRIPT in prompt and STORY in prompt

    conv = bot.conversation
    assert (conv.flow, conv.state) == ("report_confirm", {"report_id": report.pk})
    assert conv.expires_at > timezone.now() + timedelta(hours=23)
    assert report.status == Report.Status.DRAFT


def test_every_item_refreshes_last_activity_and_expiry(bot):
    report = _start(bot)
    old = timezone.now() - timedelta(hours=5)
    Report.objects.filter(pk=report.pk).update(last_activity_at=old)

    bot.text(STORY)

    report.refresh_from_db()
    assert report.last_activity_at > old
    assert bot.conversation.expires_at > timezone.now() + timedelta(hours=23)


# (b, c, i) fallbacks and summary filter ------------------------------------------------------


def test_low_confidence_audio_without_number_asks_for_details(bot, fake_llm, fake_speech):
    fake_llm.responses["evidence_extraction"] = [
        extraction_json(phone_numbers=[], account_names=[], amounts_xaf=[], evidence_kinds=[])
    ]
    fake_speech.transcripts = [Transcript(text="mumble", language="", confidence=0.2)]
    report = _start(bot)
    bot.audio()

    done = bot.text("FINI")

    assert done[-1] == t("report.ask_details", EN)
    assert bot.conversation.flow == "report_await_details"

    reply = bot.text("677 12 34 56 25 000 FCFA")

    report.refresh_from_db()
    subject = report.subjects.get(source="user")
    assert (subject.role, subject.confirmed) == ("seller", False)
    assert subject.phone_number.e164 == "+237677123456"
    assert report.amount_xaf == 25000
    assert bot.conversation.flow == "report_confirm"
    assert "📋" in reply[-1]


def test_low_confidence_transcript_alone_triggers_details_even_with_numbers(
    bot, fake_llm, fake_speech
):
    fake_llm.responses["evidence_extraction"] = [extraction_json(evidence_kinds=[])]
    fake_speech.transcripts = [Transcript(text="mumble", confidence=0.3)]
    _start(bot)
    bot.audio()

    assert bot.text("DONE")[-1] == t("report.ask_details", EN)


def test_extraction_failure_asks_for_details(bot, fake_llm):
    # Nothing queued on the fake: the client fails, extract_evidence returns extraction_failed.
    report = _start(bot)
    bot.image()

    assert bot.text("DONE")[-1] == t("report.ask_details", EN)
    report.refresh_from_db()
    assert report.ai_extraction["extraction_failed"] is True
    assert report.summary_ai == t("report.summary_neutral", EN)


def test_details_reply_without_number_reasks_once_then_proceeds(bot, fake_llm):
    report = _start(bot)
    bot.text(STORY)
    bot.text("DONE")
    assert bot.conversation.flow == "report_await_details"

    assert bot.text("I don't know") == [t("report.ask_details_again", EN)]
    assert bot.conversation.flow == "report_await_details"
    last = bot.text("still no idea")

    assert "📋" in last[-1]
    assert bot.conversation.flow == "report_confirm"
    assert not report.subjects.filter(source="user").exists()


def test_typed_amount_is_not_mistaken_for_the_number(bot, fake_llm):
    report = _start(bot)
    bot.text(STORY)
    bot.text("DONE")

    bot.text("25.000F au 6 77 12 34 56")

    report.refresh_from_db()
    assert report.amount_xaf == 25000
    assert report.subjects.get(source="user").phone_number.e164 == "+237677123456"


def test_number_typed_alone_may_be_a_landline(bot, fake_llm):
    report = _start(bot)
    bot.text(STORY)
    bot.text("DONE")

    bot.text("222 23 45 67")

    report.refresh_from_db()
    assert report.subjects.get(source="user").phone_number.e164 == "+237222234567"
    assert report.amount_xaf is None


def test_filtered_summary_is_replaced_by_the_neutral_template(bot, fake_llm, fake_speech):
    _happy_setup(fake_llm, fake_speech, summary="The scammer took my money.", evidence_kinds=[])
    report = _start(bot)
    bot.text(STORY)

    final = bot.text("DONE")[-1]

    report.refresh_from_db()
    assert report.ai_extraction["summary_filtered"] is True
    assert report.summary_ai == t("report.summary_neutral", EN)
    assert t("report.summary_neutral", EN) in final
    assert "scammer" not in final


# (d) limits ----------------------------------------------------------------------------------


def test_eleventh_item_is_refused(bot):
    report = _start(bot)
    for _ in range(10):
        bot.image(png(size=8))

    assert bot.image(png(size=8)) == [t("report.limit_items", EN)]
    assert report.evidence.count() == 10


def test_total_size_cap_is_refused(bot, monkeypatch):
    monkeypatch.setattr(tasks, "MAX_TOTAL_BYTES", 1000)
    report = _start(bot)
    bot.image(b"x" * 600)

    texts = bot.image(b"y" * 600)

    assert texts == [t("report.limit_size", EN)]
    assert report.evidence.count() == 1
    assert bot.conversation.state["pending"] == {}


def test_unreadable_download_tells_user_to_resend(bot):
    report = _start(bot)

    texts = bot.image(seed=False)  # FakeChannel raises ChannelError

    assert texts == [t("report.file_failed", EN)]
    assert report.evidence.count() == 0
    assert bot.conversation.state["pending"] == {}


def test_unsupported_media_is_refused(bot):
    report = _start(bot)

    assert bot.video() == [t("report.unsupported_item", EN)]
    assert report.evidence.count() == 0


def test_story_is_capped(bot):
    report = _start(bot)
    bot.text("a" * 3000)
    bot.text("b" * 3000)

    assert bot.text("c") == [t("report.story_full", EN)]
    report.refresh_from_db()
    assert len(report.story_text) <= flow.MAX_STORY
    assert report.story_text.startswith("a" * flow.MAX_STORY_PART + "\n")


def test_a_number_in_the_flow_is_story_not_a_check(bot):
    report = _start(bot)

    assert _says(bot.text("677123456"), "report.story_noted")
    report.refresh_from_db()
    assert report.story_text == "677123456"


# (e) idempotency -----------------------------------------------------------------------------


def test_ingest_and_extract_are_idempotent(bot, fake_llm, fake_speech):
    _happy_setup(fake_llm, fake_speech, evidence_kinds=["chat"])
    report = _start(bot)
    bot.image()
    message_id = bot.last_id

    tasks.ingest_media(report_id=report.pk, message_id=message_id, kind="image")
    assert report.evidence.count() == 1

    bot.text("DONE")
    tasks.extract(report_id=report.pk)
    tasks.extract(report_id=report.pk)

    assert len(fake_llm.calls) == 1
    assert report.subjects.count() == 2


def test_ingest_ignores_a_message_from_someone_else(bot):
    report = _start(bot)
    bot.image()
    event = InboundEvent.objects.get(message_id=bot.last_id)
    event.payload["data"]["messages"]["key"]["cleanedSenderPn"] = "237699999999"
    event.payload["data"]["messages"]["key"]["id"] = "OTHER-1"
    InboundEvent.objects.create(message_id="OTHER-1", event="x", payload=event.payload)

    tasks.ingest_media(report_id=report.pk, message_id="OTHER-1", kind="image")

    assert report.evidence.count() == 1


# (f) DONE while files are still processing --------------------------------------------------


def _pending_entry(age: timedelta = timedelta(0), kind="image", retried=False) -> dict:
    return {"t": (timezone.now() - age).timestamp(), "kind": kind, "retried": retried}


def _set_state(bot, **changes):
    conv = bot.conversation
    for key, value in changes.items():
        if key == "step":
            conv.step = value
        else:
            conv.state[key] = value
    conv.save()


def test_done_while_pending_waits(bot, fake_llm):
    report = _start(bot)
    _set_state(bot, pending={"RPT-X": _pending_entry()})

    assert bot.text("DONE") == [t("report.still_processing", EN)]
    assert fake_llm.calls == []
    assert bot.conversation.step == ""
    assert report.ai_extraction == {}


def test_stale_pending_file_is_requeued_once_then_done_proceeds(bot, fake_llm, monkeypatch):
    fake_llm.responses["evidence_extraction"] = [extraction_json(evidence_kinds=["chat"])]
    report = _start(bot)
    # The first ingest job is lost (e.g. a worker died): the file stays pending.
    monkeypatch.setitem(core_tasks._REGISTRY, "reports.ingest_media", lambda **kw: None)
    bot.image()
    monkeypatch.undo()
    lost = bot.last_id
    _set_state(bot, pending={lost: _pending_entry(timedelta(minutes=11))})

    texts = bot.text("DONE")

    assert texts == [  # re-queued once, and this time ingested
        t("report.still_processing", EN),
        t("report.ack", EN, items="1 image"),
    ]
    assert report.evidence.get().source_message_id == lost
    assert bot.conversation.state["pending"] == {}

    assert bot.text("DONE")[0] == t("report.analysing", EN)
    assert bot.conversation.flow == "report_confirm"


def test_retried_pending_file_that_stays_lost_is_dropped(bot, fake_llm):
    fake_llm.responses["evidence_extraction"] = [extraction_json(evidence_kinds=[])]
    _start(bot)
    bot.text(STORY)
    old = timedelta(minutes=11)
    _set_state(
        bot,
        pending={
            "LOST-1": _pending_entry(old, retried=True),
            "LOST-2": _pending_entry(old, kind="audio", retried=True),
        },
    )

    texts = bot.text("DONE")

    # The user is asked to resend; extraction waits so they still can.
    assert texts == [t("report.files_lost", EN, n=2)]
    conv = bot.conversation
    assert (conv.flow, conv.step, conv.state["pending"]) == ("report_collect", "", {})
    assert fake_llm.calls == []

    assert bot.text("DONE")[0] == t("report.analysing", EN)
    assert bot.conversation.flow == "report_confirm"


def test_one_lost_file_uses_the_singular(bot, fake_llm):
    _start(bot)
    bot.text(STORY)
    _set_state(bot, pending={"LOST-1": _pending_entry(timedelta(minutes=11), retried=True)})

    assert bot.text("DONE") == [t("report.files_lost_one", EN)]
    assert bot.conversation.step == ""


def test_resending_after_a_drop_then_done_reaches_extraction(bot, fake_llm):
    fake_llm.responses["evidence_extraction"] = [extraction_json(evidence_kinds=["chat"])]
    report = _start(bot)
    _set_state(bot, pending={"LOST-1": _pending_entry(timedelta(minutes=11), retried=True)})
    assert bot.text("DONE") == [t("report.files_lost_one", EN)]

    assert _says(bot.image(), "report.ack", items="1 image")
    texts = bot.text("DONE")

    assert texts[0] == t("report.analysing", EN)
    assert report.evidence.count() == 1
    assert sum(1 for b in fake_llm.calls[0]["user_content"] if b["type"] == "image_url") == 1
    assert bot.conversation.flow == "report_confirm"


def test_done_with_nothing_sent_asks_for_an_item(bot, fake_llm):
    _start(bot)

    assert bot.text("1") == [t("report.need_one_item", EN)]
    assert fake_llm.calls == []


def test_messages_while_analysing_are_told_to_wait(bot, fake_llm):
    _start(bot)
    bot.text(STORY)
    _set_state(bot, step="extracting", extracting_since=timezone.now().isoformat())

    assert bot.text("hello?") == [t("report.analysis_wait", EN)]
    assert bot.text("DONE") == [t("report.analysis_wait", EN)]  # fresh: no second job
    assert fake_llm.calls == []


def test_done_after_a_stale_extraction_reruns_it(bot, fake_llm):
    fake_llm.responses["evidence_extraction"] = [extraction_json(evidence_kinds=[])]
    _start(bot)
    bot.text(STORY)
    since = (timezone.now() - timedelta(minutes=11)).isoformat()
    _set_state(bot, step="extracting", extracting_since=since)  # the job was lost

    texts = bot.text("DONE")

    assert texts[0] == t("report.analysis_wait", EN)
    assert len(fake_llm.calls) == 1
    assert bot.conversation.flow == "report_confirm"


def test_handover_failure_returns_the_user_to_collecting(bot, fake_llm, monkeypatch):
    fake_llm.responses["evidence_extraction"] = [extraction_json(evidence_kinds=[])]
    _start(bot)
    bot.text(STORY)

    def boom(report):
        raise RuntimeError("handover failed")

    monkeypatch.setattr(flow, "present_for_confirmation", boom)

    texts = bot.text("DONE")

    assert texts[-1] == t("report.analysis_failed", EN)
    conv = bot.conversation
    assert (conv.flow, conv.step) == ("report_collect", "")
    assert "extracting_since" not in conv.state


def test_analysis_failed_never_raises(bot, monkeypatch):
    report = _start(bot)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(flow, "_from_extracting", boom)

    flow.analysis_failed(report)  # logs and returns


def test_ack_failure_keeps_the_evidence_row_and_blob(bot, object_store, monkeypatch):
    report = _start(bot)

    def boom(*args, **kwargs):
        raise RuntimeError("count failed")

    monkeypatch.setattr(flow, "item_counts_text", boom)

    assert bot.image() == []  # no ack could be built

    evidence = report.evidence.get()
    assert object_store.get(evidence.object_key)


def test_failure_after_upload_deletes_the_blob(bot, object_store, fake_speech, monkeypatch):
    report = _start(bot)

    def boom(*args, **kwargs):
        raise RuntimeError("stt crashed")

    monkeypatch.setattr(fake_speech, "transcribe", boom)

    assert bot.audio() == [t("report.file_failed", EN)]
    assert report.evidence.count() == 0
    assert object_store._objects == {}


def test_failure_creating_the_row_deletes_the_blob(bot, object_store, monkeypatch):
    report = _start(bot)

    def boom(*args, **kwargs):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(tasks, "_keep", boom)

    bot.image()

    assert report.evidence.count() == 0
    assert object_store._objects == {}


def test_no_ack_while_extracting(bot):
    report = _start(bot)
    bot.text(STORY)
    # A late file lands while extraction runs: kept, but the user is not interrupted.
    _set_state(bot, step="extracting", extracting_since=timezone.now().isoformat())
    _set_state(bot, pending={"RPT-LATE": _pending_entry()})
    bot.channel.sent.clear()
    InboundEvent.objects.create(
        message_id="RPT-LATE",
        event="messages.received",
        payload={
            "event": "messages.received",
            "data": {
                "messages": {
                    "key": {
                        "id": "RPT-LATE",
                        "fromMe": False,
                        "remoteJid": f"{bot.user.wa_phone[1:]}@s.whatsapp.net",
                        "cleanedSenderPn": bot.user.wa_phone[1:],
                    },
                    "message": {"imageMessage": {"mimetype": "image/png", "url": "https://x"}},
                }
            },
        },
    )
    bot.channel.media["RPT-LATE"] = (png(), "image/png")

    tasks.ingest_media(report_id=report.pk, message_id="RPT-LATE", kind="image")

    assert report.evidence.count() == 1
    assert bot.channel.sent == []
    assert bot.conversation.state["pending"] == {}


def test_reextraction_keeps_a_user_typed_amount(bot, fake_llm):
    fake_llm.responses["evidence_extraction"] = [
        extraction_json(evidence_kinds=[], amounts_xaf=[25000]),
        extraction_json(evidence_kinds=["chat"], amounts_xaf=[30000]),
    ]
    report = _start(bot)
    bot.text(STORY)
    bot.text("DONE")
    Report.objects.filter(pk=report.pk).update(amount_xaf=40000)  # the reporter corrected it
    bot.text("0")
    bot.text("4")
    bot.text("1")
    bot.image()
    bot.text("DONE")

    report.refresh_from_db()
    assert len(fake_llm.calls) == 2
    assert report.amount_xaf == 40000


def test_reextraction_updates_an_ai_amount(bot, fake_llm):
    fake_llm.responses["evidence_extraction"] = [
        extraction_json(evidence_kinds=[], amounts_xaf=[25000]),
        extraction_json(evidence_kinds=["chat"], amounts_xaf=[30000]),
    ]
    report = _start(bot)
    bot.text(STORY)
    bot.text("DONE")
    bot.text("0")
    bot.text("4")
    bot.text("1")
    bot.image()
    bot.text("DONE")

    report.refresh_from_db()
    assert report.amount_xaf == 30000


# (g) cancel, menu, resume --------------------------------------------------------------------


def test_cancel_withdraws_the_draft(bot):
    report = _start(bot)

    assert bot.text("ANNULER") == [t("report.cancelled", EN)]
    report.refresh_from_db()
    assert report.status == Report.Status.WITHDRAWN
    assert bot.conversation.flow == "idle"


def test_menu_keeps_the_draft_and_report_offers_resume(bot):
    report = _start(bot)
    bot.image()
    bot.text("MENU")
    report.refresh_from_db()
    assert report.status == Report.Status.DRAFT

    texts = bot.text("4")

    assert texts == [t("report.resume_choice", EN, items="1 image")]
    assert bot.conversation.flow == "report_resume_choice"


def test_resume_continue_keeps_collecting_into_the_old_draft(bot):
    report = _start(bot)
    bot.text(STORY)
    bot.text("0")
    bot.text("4")

    assert bot.text("1") == [t("report.resumed", EN, items=t("report.count.none", EN))]
    bot.text("more details")

    report.refresh_from_db()
    assert report.story_text == f"{STORY}\nmore details"
    assert Report.objects.filter(reporter=bot.user).count() == 1


def test_resume_start_new_withdraws_the_old_draft(bot):
    old = _start(bot)
    bot.text("0")
    bot.text("4")

    assert _says(bot.text("2"), "report.instructions")

    old.refresh_from_db()
    assert old.status == Report.Status.WITHDRAWN
    new = _report(bot)
    assert new.pk != old.pk
    assert bot.conversation.state["report_id"] == new.pk


def test_flow_continues_at_23_hours(bot):
    report = _start(bot)
    conv = bot.conversation
    conv.expires_at = timezone.now() + timedelta(hours=1)  # last activity 23 h ago
    conv.save()

    assert _says(bot.image(), "report.ack", items="1 image")
    assert report.evidence.count() == 1


def test_after_25_hours_report_offers_resume(bot):
    report = _start(bot)
    bot.image()
    conv = bot.conversation
    conv.expires_at = timezone.now() - timedelta(hours=1)  # last activity 25 h ago
    conv.save()
    Report.objects.filter(pk=report.pk).update(
        last_activity_at=timezone.now() - timedelta(hours=25)
    )

    assert bot.text("4") == [t("report.resume_choice", EN, items="1 image")]


def test_drafts_older_than_seven_days_are_not_offered(bot):
    report = _start(bot)
    bot.text("0")
    Report.objects.filter(pk=report.pk).update(last_activity_at=timezone.now() - timedelta(days=8))

    assert _says(bot.text("4"), "report.instructions")


def test_voice_note_with_no_flow_starts_a_report_with_that_note(bot, fake_speech):
    fake_speech.transcripts = [Transcript(text=TRANSCRIPT, confidence=0.9)]

    texts = bot.audio()

    assert texts[0].startswith(t("report.instructions", EN))
    assert _says(texts, "report.ack", items="1 voice note")
    assert _report(bot).evidence.get().kind == "voice"


# (h) image choice -> scam evidence -----------------------------------------------------------


def test_image_choice_2_starts_a_report_with_that_image(bot):
    bot.image(png("green"))
    assert bot.text("2")[0] == t("report.instructions", EN)

    report = _report(bot)
    evidence = report.evidence.get()
    assert evidence.mimetype == "image/png"
    assert evidence.sha256 == hashlib.sha256(png("green")).hexdigest()


def test_resume_choice_carries_the_triggering_image(bot):
    old = _start(bot)
    bot.text("0")
    bot.image()
    bot.text("2")  # scam evidence -> resume offer, image held
    assert bot.conversation.flow == "report_resume_choice"

    bot.text("1")

    assert old.evidence.count() == 1


# (j) privacy ---------------------------------------------------------------------------------


def test_happy_path_logs_no_personal_data(bot, fake_llm, fake_speech, caplog):
    _happy_setup(fake_llm, fake_speech)
    with caplog.at_level(logging.DEBUG):
        _start(bot)
        bot.image()
        bot.image()
        bot.audio()
        bot.text(STORY)
        bot.text("DONE")
        bot.text("0")

    logged = caplog.text
    assert bot.conversation.flow == "idle"
    for secret in (STORY, TRANSCRIPT, "677123456", "Jean Dupont", "70000055", "phone that was"):
        assert secret not in logged


def test_subjects_are_replaced_when_extraction_reruns_on_new_evidence(bot, fake_llm):
    fake_llm.responses["evidence_extraction"] = [
        extraction_json(evidence_kinds=[]),
        extraction_json(evidence_kinds=["chat"], phone_numbers=["655123456"]),
    ]
    report = _start(bot)
    bot.text(STORY)
    bot.text("DONE")
    bot.text("0")
    bot.text("4")
    bot.text("1")
    bot.image()
    bot.text("DONE")

    assert len(fake_llm.calls) == 2
    numbers = set(
        ReportSubject.objects.filter(
            report=report, source="ai", phone_number__isnull=False
        ).values_list("phone_number__e164", flat=True)
    )
    assert numbers == {"+237655123456"}


def test_evidence_kinds_follow_image_order(bot, fake_llm):
    fake_llm.responses["evidence_extraction"] = [
        extraction_json(evidence_kinds=["post", "chat", "momo_sms"])
    ]
    report = _start(bot)
    for color in ("red", "green", "blue"):
        bot.image(png(color))
    bot.text("DONE")

    kinds = list(
        Evidence.objects.filter(report=report)
        .order_by("created_at", "pk")
        .values_list("kind", flat=True)
    )
    assert kinds == ["post", "chat", "momo_sms"]


def test_a_failed_extraction_is_retried_on_done(bot, fake_llm):
    _start(bot)
    bot.text(STORY)
    bot.text("DONE")  # nothing queued on the fake: extraction fails, details are asked
    bot.text("0")
    bot.text("4")
    bot.text("1")
    fake_llm.responses["evidence_extraction"] = [extraction_json(evidence_kinds=[])]

    bot.text("DONE")

    assert len(fake_llm.calls) == 2
    assert bot.conversation.flow == "report_confirm"
