import pytest

from tchekam.conversations.models import BotUser
from tchekam.reports.models import Evidence, Report
from tchekam.reports.scoring import evidence_score, refresh_evidence_score


def score(kinds=(), story=False, proof=False, tamper=0):
    return evidence_score(
        kinds, has_story=story, payment_proof_candidate=proof, tamper_flags=tamper
    )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, 0.0),
        ({"kinds": ["chat"]}, 0.3),
        ({"kinds": ["momo_sms"]}, 0.3),
        ({"kinds": ["post"]}, 0.1),
        ({"kinds": ["voice"]}, 0.1),
        ({"story": True}, 0.1),
        ({"kinds": ["voice"], "story": True}, 0.1),  # one signal, not two
        ({"proof": True}, 0.2),
        ({"kinds": ["chat", "chat", "chat"]}, 0.3),  # repeats do not stack
        ({"kinds": ["chat", "momo_sms"]}, 0.6),
        ({"kinds": ["chat", "momo_sms", "post", "voice"], "proof": True}, 1.0),  # exactly the cap
        ({"kinds": ["other"]}, 0.0),
        ({"tamper": 1}, 0.0),  # floor
        ({"kinds": ["chat"], "tamper": 1}, 0.1),
        ({"kinds": ["chat", "momo_sms"], "proof": True, "tamper": 2}, 0.4),
        ({"kinds": ["chat", "momo_sms", "post", "voice"], "proof": True, "tamper": 1}, 0.8),
    ],
)
def test_score_boundaries(kwargs, expected):
    assert score(**kwargs) == pytest.approx(expected)


def test_score_is_clamped_to_one():
    assert score(["chat", "momo_sms", "post"], story=True, proof=True) == 1.0
    assert score(["chat", "momo_sms", "post", "voice"], story=True, proof=True) == 1.0


@pytest.mark.django_db
def test_refresh_reads_evidence_extraction_and_flags_and_persists():
    report = Report.objects.create(
        reporter=BotUser.objects.create(wa_phone="+237600000001"),
        ai_extraction={"payment_proof_candidate": True, "tamper_observations": ["odd font"]},
    )
    chat = Evidence.objects.create(
        report=report, kind="chat", object_key="k1", mimetype="image/png", sha256="a", size_bytes=1
    )
    Evidence.objects.create(
        report=report, kind="momo_sms", object_key="k2", mimetype="image/png", sha256="b",
        size_bytes=1, tamper_flags=["duplicate_evidence"],
    )  # fmt: skip

    # 0.3 + 0.3 + 0.2 - 2 * 0.2
    assert refresh_evidence_score(report) == pytest.approx(0.4)
    assert Report.objects.get(pk=report.pk).evidence_score == pytest.approx(0.4)
    chat.delete()
    assert refresh_evidence_score(report) == pytest.approx(0.1)
