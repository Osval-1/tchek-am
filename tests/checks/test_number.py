from datetime import timedelta
from itertools import count

import pytest
from django.core.cache import cache
from django.utils import timezone

from tchekam.checks.models import CheckLog
from tchekam.checks.number import handle_check_number
from tchekam.conversations.models import BotUser, Conversation
from tchekam.conversations.router import Context
from tchekam.identifiers.models import PhoneNumber, get_or_create_account_name, get_or_create_phone
from tchekam.messaging.models import InboundEvent
from tchekam.messaging.tasks import process_inbound
from tchekam.reports.models import Report, ReportSubject
from tchekam.reputation import appeals_hook
from tchekam.reputation.facts import AppealState

pytestmark = pytest.mark.django_db

SENDER = "237670000099"
TARGET = "+237677123456"  # MTN
TARGET_TEXT = "677 12 34 56"
REPORTER_PHONE = "+237655443322"  # must never show up in any reply
_ids = count(1)
_reporters = count(1)


@pytest.fixture
def asker(fake_channel):
    """ask(text, lang) sends a WhatsApp text through the webhook pipeline; returns reply texts."""

    def ask(text, lang="en", phone=SENDER):
        user, _ = BotUser.objects.get_or_create(wa_phone=f"+{phone}")
        user.language = lang
        user.save(update_fields=["language"])
        Conversation.objects.get_or_create(user=user)
        fake_channel.reset()
        cache.clear()  # reports are seeded through the ORM, which does not invalidate bands
        n = next(_ids)
        payload = {
            "event": "messages.received",
            "timestamp": 1633456789,
            "data": {
                "messages": {
                    "key": {
                        "id": f"CHK-{n}",
                        "fromMe": False,
                        "remoteJid": "123456789012345@lid",
                        "cleanedSenderPn": phone,
                    },
                    "messageBody": text,
                    "message": {"conversation": text},
                    "messageTimestamp": 1633456789,
                }
            },
        }
        event = InboundEvent.objects.create(
            message_id=f"CHK-{n}", event=payload["event"], payload=payload
        )
        process_inbound(event_id=event.pk)
        return [m["text"] for m in fake_channel.sent if m["type"] == "text"]

    return ask


def seed(
    status="approved",
    e164=TARGET,
    reporter_phone=None,
    age_days=20,
    names=(),
    name_confirmed=True,
    **fields,
):
    n = next(_reporters)
    reporter, _ = BotUser.objects.get_or_create(wa_phone=reporter_phone or f"+23769900{n:04d}")
    now = timezone.now()
    report = Report.objects.create(
        reporter=reporter,
        status=status,
        submitted_at=now - timedelta(days=age_days + 1 + n),
        decided_at=now - timedelta(days=age_days) if status == "approved" else None,
        **fields,
    )
    ReportSubject.objects.create(
        report=report,
        phone_number=get_or_create_phone(e164),
        role="seller",
        source="user",
        confirmed=status == "approved",
    )
    for name in names:
        ReportSubject.objects.create(
            report=report,
            account_name=get_or_create_account_name(name, "momo"),
            role="payee",
            source="user",
            confirmed=name_confirmed,
        )
    return report


def one(replies):
    assert len(replies) == 1
    return replies[0]


def test_green_en_and_fr(asker):
    en = one(asker(TARGET_TEXT, "en"))
    assert "+237 677 12 34 56" in en and "MTN" in en
    assert "🟢 No reports for this number." in en
    assert "doesn't prove the seller is honest" in en
    fr = one(asker(TARGET_TEXT, "fr"))
    assert "🟢 Aucun signalement" in fr and "ne prouve pas" in fr


def test_green_footer_tips_and_no_names(asker):
    out = one(asker(TARGET_TEXT))
    assert "reply 4" in out and "APPEAL" in out
    assert "cash on delivery" in out and "MoMo/OM" in out
    assert "Names seen" not in out


def test_yellow_shows_only_the_count(asker):
    seed("pending", summary_final="SECRETSUMMARY zebra", amount_xaf=45678, names=["Pending Pam"])
    seed("needs_info")
    out = one(asker(TARGET_TEXT))
    assert "🟡 2 reports waiting for review." in out
    for hidden in ("SECRETSUMMARY", "45678", "45 678", "PENDING", "P***", "Last report"):
        assert hidden not in out
    assert "Names seen" not in out


def test_yellow_singular_fr(asker):
    seed("pending")
    assert "🟡 1 signalement en attente" in one(asker(TARGET_TEXT, "fr"))


def test_orange_en(asker):
    seed(summary_final="SECRETSUMMARY", amount_xaf=45678)
    out = one(asker(TARGET_TEXT))
    assert "🟠 Reported by 1 person, evidence reviewed." in out
    assert "Not enough for a high-risk warning. Be careful." in out
    assert f"Last report: {timezone.localtime() - timedelta(days=20):%B %Y}" in out
    assert "SECRETSUMMARY" not in out and "45678" not in out


def test_orange_fr_two_reporters(asker):
    seed()
    seed()
    out = one(asker(TARGET_TEXT, "fr"))
    assert "🟠 Signalé par 2 personnes" in out
    assert "Dernier signalement :" in out


def test_orange_without_reporter_count_says_reviewed(asker):
    # Erased reporter: an approved report but no trusted independent reporter.
    report = seed()
    Report.objects.filter(pk=report.pk).update(reporter=None)
    out = one(asker(TARGET_TEXT))
    assert "🟠 Reviewed reports exist." in out and "Reported by" not in out


def test_red_en_and_fr(asker):
    for _ in range(3):
        seed()
    en = one(asker(TARGET_TEXT, "en"))
    assert "🔴 High risk: reported by 3 different people. Evidence reviewed." in en
    assert "Last report:" in en
    fr = one(asker(TARGET_TEXT, "fr"))
    assert "🔴 Risque élevé : signalé par 3 personnes différentes" in fr


def test_red_payment_proof_uses_single_report_wording(asker):
    seed(has_payment_proof=True)
    out = one(asker(TARGET_TEXT))
    assert "🔴 High risk: 1 reviewed report with payment proof." in out
    assert "different people" not in out


def test_reporter_number_never_appears_in_any_band(asker):
    seed("pending", reporter_phone=REPORTER_PHONE)
    replies = asker(TARGET_TEXT)
    Report.objects.all().delete()
    seed(reporter_phone=REPORTER_PHONE)
    replies += asker(TARGET_TEXT, "fr")
    seed(reporter_phone="+237655443323")
    seed(reporter_phone="+237655443324")
    replies += asker(TARGET_TEXT)
    seed(has_payment_proof=True, reporter_phone="+237655443325")
    replies += asker(TARGET_TEXT, "pcm")
    assert len(replies) == 4
    for text in replies:
        assert "55443322" not in text and "55 44 33" not in text


def test_linked_names_are_masked_deduplicated_and_capped(asker):
    seed(names=["Jean-Paul Mbarga", "Awa Njoya"])
    seed(names=["jean-paul  MBARGA", "Éric Tabi", "Zoe Biya"])
    out = one(asker(TARGET_TEXT))
    names_line = next(line for line in out.splitlines() if line.startswith("Names seen"))
    names = names_line.split(": ", 1)[1].split(", ")
    assert len(names) == 3
    assert out.count("JEAN-P*** M***") == 1
    assert "MBARGA" not in out.upper().replace("M***", "")


def test_unconfirmed_names_do_not_link(asker):
    seed(names=["Hidden Hank"], name_confirmed=False)
    out = one(asker(TARGET_TEXT))
    assert "Names seen" not in out and "H***" not in out


def test_names_never_for_yellow(asker):
    # An old approved report no longer counts (band is yellow via the pending one).
    seed(age_days=800, names=["Old Olga"])
    seed("pending", names=["Pending Pam"])
    out = one(asker(TARGET_TEXT))
    assert "🟡" in out and "Names seen" not in out and "O***" not in out


def test_under_appeal_line_only_when_reports_exist(asker):
    appeals_hook.set_provider(lambda e164: AppealState(under_appeal=True, number_acquired_at=None))
    assert "Under appeal" not in one(asker(TARGET_TEXT))
    seed()
    assert "⚖️ Under appeal: the owner of this number is contesting the reports." in one(
        asker(TARGET_TEXT)
    )


def test_check_count_and_log(asker):
    asker(TARGET_TEXT)
    asker(TARGET_TEXT)
    assert PhoneNumber.objects.get(e164=TARGET).check_count == 2
    log = CheckLog.objects.latest("pk")
    assert (log.kind, log.subject_ref, log.result_band) == ("number", TARGET, "green")
    assert log.user.wa_phone == f"+{SENDER}"


def test_checked_times_this_month(asker):
    assert "Checked" not in one(asker(TARGET_TEXT))
    assert "Checked 2 times this month" in one(asker(TARGET_TEXT))
    assert "Vérifié 3 fois ce mois-ci" in one(asker(TARGET_TEXT, "fr"))


def test_operator_unknown_is_omitted(asker):
    out = one(asker("641 00 00 01"))  # no operator owns prefix 641
    assert "+237 641 00 00 01" in out and "Unknown" not in out and "()" not in out


def test_limit_message_on_31st_check_and_no_log(asker):
    for _ in range(30):
        assert "limit" not in one(asker(TARGET_TEXT))
    out = one(asker(TARGET_TEXT))
    assert "limit of checks" in out
    assert CheckLog.objects.count() == 30
    assert PhoneNumber.objects.get(e164=TARGET).check_count == 30


def test_limit_applies_per_number_mid_batch(asker, settings):
    settings.CHECKS_PER_DAY = 2
    replies = asker("677 12 34 56 and 690 00 00 01 and 655 00 00 02")
    assert len(replies) == 3
    assert "limit of checks" in replies[2]
    assert CheckLog.objects.count() == 2


def test_several_numbers_get_one_message_each(asker):
    replies = asker("677 12 34 56 / 690 00 00 01")
    assert len(replies) == 2
    assert "+237 677 12 34 56" in replies[0] and "MTN" in replies[0]
    assert "+237 690 00 00 01" in replies[1] and "Orange" in replies[1]


def test_handler_caps_at_three_even_with_more_numbers():
    user = BotUser.objects.create(wa_phone="+237670000088", language="en")
    ctx = Context(
        user=user,
        conversation=Conversation.objects.create(user=user),
        msg=None,
        extra={"numbers": [f"+23767700000{i}" for i in range(5)]},
    )
    replies = handle_check_number(ctx)
    assert len(replies) == 4
    assert "first 3" in replies[-1].text
    assert CheckLog.objects.count() == 3


def test_names_from_decayed_reports_are_not_shown(asker):
    # Decided yesterday, but the incident was over 24 months ago: the band ignores it, so must we.
    seed(names=["Old Olga"], incident_date=timezone.localdate() - timedelta(days=800))
    seed(names=["Fresh Fred"])
    out = one(asker(TARGET_TEXT))
    assert "🟠" in out and "F*** F***" in out and "O***" not in out


def test_names_from_reports_before_number_acquisition_are_not_shown(asker):
    today = timezone.localdate()
    appeals_hook.set_provider(
        lambda e164: AppealState(under_appeal=False, number_acquired_at=today - timedelta(days=30))
    )
    old_owner = seed(names=["Previous Pete"], incident_date=today - timedelta(days=60))
    kept = seed(names=["Current Carl"])
    Report.objects.filter(pk__in=[old_owner.pk, kept.pk]).update(
        submitted_at=timezone.now() - timedelta(days=1)
    )
    out = one(asker(TARGET_TEXT))
    assert "🟠" in out and "C*** C***" in out and "P***" not in out


def test_four_numbers_check_three_and_say_so(asker):
    replies = asker("677 00 00 01 / 677 00 00 02 / 677 00 00 03 / 677 00 00 04")
    assert len(replies) == 4
    assert "first 3" in replies[3]
    assert CheckLog.objects.count() == 3
