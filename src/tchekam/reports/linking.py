"""Find reports related to one another, so moderators and the independence rules can see them.

Only live reports (pending, needs_info, approved) are linked: drafts are unfinished and
rejected, merged or withdrawn reports are not evidence of anything. Pairs are stored once
(`ReportLink.link` orders them), so running this for either side of a pair is harmless.
"""

from difflib import SequenceMatcher

from django.db.models import Q

from tchekam.i18n import t

from .models import Evidence, Report, ReportLink, ReportSubject

LIVE = (Report.Status.PENDING, Report.Status.NEEDS_INFO, Report.Status.APPROVED)
TEXT_SIMILARITY = 0.85
# Bounds the quadratic text comparison; newer reports are the likely duplicates.
TEXT_CANDIDATES = 2000
_REASON = ReportLink.Reason


def link_report(report: Report) -> int:
    """Create the missing links for `report`. Returns how many pairs now exist for it."""
    if report.status not in LIVE:
        return 0
    found: list[tuple[Report, str, float]] = []
    for reason, matches in (
        (_REASON.SAME_NUMBER, _same_number(report)),
        (_REASON.SAME_NAME, _same_name(report)),
        (_REASON.SAME_IMAGE, _same_image(report)),
    ):
        found += [(other, reason, 1.0) for other in matches]
    found += [(other, _REASON.SIMILAR_TEXT, score) for other, score in _similar_text(report)]
    for other, reason, score in found:
        ReportLink.link(report, other, reason, score)
    return len(found)


def _others(report: Report) -> Q:
    return Q(status__in=LIVE) & ~Q(pk=report.pk)


def _same_number(report: Report) -> list[Report]:
    phones = list(
        report.subjects.filter(phone_number__isnull=False)
        .filter(Q(confirmed=True) | Q(source=ReportSubject.Source.AI))
        .values_list("phone_number_id", flat=True)
    )
    if not phones:
        return []
    named = ReportSubject.objects.filter(phone_number_id__in=phones).filter(
        Q(confirmed=True) | Q(source=ReportSubject.Source.AI)
    )
    return list(Report.objects.filter(_others(report), subjects__in=named).distinct())


def _same_name(report: Report) -> list[Report]:
    names = list(
        report.subjects.filter(account_name__isnull=False).values_list("account_name_id", flat=True)
    )
    if not names:
        return []
    return list(
        Report.objects.filter(_others(report), subjects__account_name_id__in=names).distinct()
    )


def _same_image(report: Report) -> list[Report]:
    # Exact file match only. Issue 17 adds perceptual hashes: extend here with a pHash distance
    # <= 8 lookup and return its matches too.
    hashes = set(report.evidence.values_list("sha256", flat=True))
    hashes |= set(
        report.subjects.filter(image__isnull=False).values_list("image__sha256", flat=True)
    )
    if not hashes:
        return []
    return list(
        Report.objects.filter(_others(report))
        .filter(Q(evidence__sha256__in=hashes) | Q(subjects__image__sha256__in=hashes))
        .distinct()
    )


def _summary(report: Report) -> str:
    return (report.summary_final or report.summary_ai).strip()


def _similar_text(report: Report) -> list[tuple[Report, float]]:
    # The neutral placeholder is shared by every report whose summary was blanked: not a match.
    neutral = {t("report.summary_neutral", lang) for lang in ("fr", "en", "pcm")}
    mine = _summary(report)
    if not mine or mine in neutral:
        return []
    matches = []
    candidates = Report.objects.filter(_others(report)).order_by("-pk")[:TEXT_CANDIDATES]
    for other in candidates:
        theirs = _summary(other)
        if not theirs or theirs in neutral:
            continue
        matcher = SequenceMatcher(None, mine, theirs)
        # The upper bounds are cheap and never below the real ratio, so they only skip work.
        if matcher.real_quick_ratio() < TEXT_SIMILARITY or matcher.quick_ratio() < TEXT_SIMILARITY:
            continue
        if (ratio := matcher.ratio()) >= TEXT_SIMILARITY:
            matches.append((other, round(ratio, 4)))
    return matches


def reused_from_other_reporter(evidence: Evidence) -> bool:
    """True if a different reporter already holds a file with the same sha256.

    Drafts and rejected reports count (reuse is suspicious whatever became of the first
    report); withdrawn ones do not, since they are purged. The same reporter re-sending a
    file is not reuse.
    """
    return (
        Evidence.objects.filter(sha256=evidence.sha256)
        .exclude(report__status=Report.Status.WITHDRAWN)
        .exclude(report__reporter_key=evidence.report.reporter_key)
        .exists()
    )
