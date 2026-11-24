from pathlib import Path

import pytest
from django.urls import reverse

from tchekam.core.models import AuditLog
from tchekam.identifiers.models import get_or_create_account_name
from tchekam.reports.models import Evidence, ReportLink, ReportSubject

pytestmark = pytest.mark.django_db

TEMPLATES = Path(__file__).parents[2] / "src" / "tchekam" / "moderation" / "templates"


def test_no_template_mentions_object_key():
    files = list(TEMPLATES.rglob("*.html"))
    assert files
    assert all("object_key" not in f.read_text(encoding="utf-8") for f in files)


def test_review_page_never_outputs_object_keys(staff_client, make_report):
    report = make_report(files=2)
    keys = list(Evidence.objects.values_list("object_key", flat=True))

    html = staff_client.get(reverse("moderation:review", args=[report.pk])).content.decode()

    assert all(k not in html and k.split("/")[-1] not in html for k in keys)
    for ev in report.evidence.all():
        assert f'src="/moderation/evidence/{ev.pk}/"' in html


def test_gallery_shows_audio_with_transcript_and_other_files_as_links(staff_client, make_report):
    report = make_report(files=0)
    Evidence.objects.create(
        report=report, kind="voice", object_key="k/a", mimetype="audio/ogg", sha256="a" * 64,
        size_bytes=1, transcript="he never sent the phone", transcript_confidence=0.82,
    )  # fmt: skip
    pdf = Evidence.objects.create(
        report=report, kind="other", object_key="k/b", mimetype="application/pdf",
        sha256="b" * 64, size_bytes=1,
    )  # fmt: skip

    html = staff_client.get(reverse("moderation:review", args=[report.pk])).content.decode()

    assert "<audio controls" in html
    assert "he never sent the phone" in html
    assert "0.82" in html
    assert f'<a href="/moderation/evidence/{pdf.pk}/">' in html


def test_review_shows_facts_ai_hint_band_history_links_and_decisions(
    staff_client, make_report, staff
):
    report = make_report(
        amount_xaf=25000,
        summary_ai="AI wrote this",
        summary_final="Moderator wrote this",
        story_text="my story",
        ai_extraction={"tamper_observations": ["font mismatch"], "payment_proof_candidate": True},
    )
    other = make_report(phone="+237677000099")
    ReportLink.link(report, other, "same_name", 0.9)
    report.decisions.create(moderator=staff, action="need_info", reason="send the SMS")

    html = staff_client.get(reverse("moderation:review", args=[report.pk])).content.decode()

    for text in (
        report.reference, "25000", "AI wrote this", "Moderator wrote this", "my story",
        "AI hint - verify yourself", "font mismatch", "+237677123456", "band-yellow",
        "SMS and chat screenshot match and name the same number.",
        reverse("moderation:review", args=[other.pk]), "send the SMS", "trust weight 1.00",
    ):  # fmt: skip
        assert text in html, text


def test_reporter_number_is_hidden_until_revealed(staff_client, make_report, post):
    report = make_report(reporter_phone="+237699888777")
    review = staff_client.get(reverse("moderation:review", args=[report.pk]))
    assert "699888777" not in review.content.decode()
    assert not AuditLog.objects.filter(action="reporter.reveal").exists()

    resp = post(reverse("moderation:reveal", args=[report.pk]))

    assert "+237699888777" in resp.content.decode()
    assert resp["Cache-Control"] == "no-store"
    entry = AuditLog.objects.get(action="reporter.reveal")
    assert entry.object_id == str(report.pk) and entry.actor.username == "mod"
    assert "699888777" not in str(entry.metadata)
    # never kept: neither the next page view nor the session carries it
    again = staff_client.get(reverse("moderation:review", args=[report.pk]))
    assert "699888777" not in again.content.decode()
    assert "699888777" not in str(dict(staff_client.session))


def test_xss_in_payee_name_is_escaped(staff_client, make_report):
    report = make_report()
    ReportSubject.objects.create(
        report=report, account_name=get_or_create_account_name("<script>alert(1)</script>"),
        role="payee", source="user",
    )  # fmt: skip

    html = staff_client.get(reverse("moderation:review", args=[report.pk])).content.decode()

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_rejected_report_page_is_read_only_with_reopen_form(staff_client, make_report):
    report = make_report(status="rejected")

    html = staff_client.get(reverse("moderation:review", args=[report.pk])).content.decode()

    assert 'name="reopen_reason"' in html
    assert 'name="confirmed_' not in html and 'name="action" value="approve"' not in html


# Web matches (Issue 19) -----------------------------------------------------------------------


def _store_matches(sha, matches):
    from tchekam.imaging.models import WebSearchResult

    WebSearchResult.objects.create(sha256=sha, matches=matches)


def test_review_shows_stored_web_matches_escaped_with_safe_links(staff_client, make_report):
    report = make_report(files=1)
    ev = report.evidence.get()
    _store_matches(
        ev.sha256,
        [
            {
                "url": "https://www.jumia.cm/x?a=1&b=2",
                "title": "<script>alert(1)</script> Phone",
                "source_domain": "jumia.cm",
                "kind": "catalogue",
            }
        ],
    )

    html = staff_client.get(reverse("moderation:review", args=[report.pk])).content.decode()

    assert "Found online (1)" in html
    assert "jumia.cm" in html and "[catalogue]" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; Phone" in html
    assert 'href="https://www.jumia.cm/x?a=1&amp;b=2"' in html
    assert 'rel="noopener noreferrer nofollow"' in html


def test_review_without_a_search_result_shows_no_web_section(staff_client, make_report):
    report = make_report(files=1)

    html = staff_client.get(reverse("moderation:review", args=[report.pk])).content.decode()

    assert "Found online" not in html


def test_review_shows_an_empty_search_result_and_survives_re_extraction(staff_client, make_report):
    report = make_report(files=1)
    ev = report.evidence.get()
    _store_matches(ev.sha256, [])
    Evidence.objects.filter(pk=ev.pk).update(
        ai_extraction={"kind": "post"}
    )  # as re-extraction does

    html = staff_client.get(reverse("moderation:review", args=[report.pk])).content.decode()

    assert "Found online (0)" in html and "No matches found." in html
