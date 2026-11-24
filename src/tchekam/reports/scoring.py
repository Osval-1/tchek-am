"""Evidence score (0-1): how much checkable material a report carries. Used to rank the queue."""

from collections.abc import Iterable

from .models import Evidence, Report

KIND_POINTS = {
    Evidence.Kind.CHAT: 0.3,
    Evidence.Kind.MOMO_SMS: 0.3,
    Evidence.Kind.POST: 0.1,
}
VOICE_OR_STORY_POINTS = 0.1
PAYMENT_PROOF_CANDIDATE_POINTS = 0.2
TAMPER_PENALTY = 0.2


def evidence_score(
    kinds: Iterable[str],
    *,
    has_story: bool,
    payment_proof_candidate: bool,
    tamper_flags: int,
) -> float:
    """Each signal counts once however many files show it (ten chat shots are not ten signals)."""
    present = set(kinds)
    score = sum(points for kind, points in KIND_POINTS.items() if kind in present)
    if Evidence.Kind.VOICE in present or has_story:
        score += VOICE_OR_STORY_POINTS
    if payment_proof_candidate:
        score += PAYMENT_PROOF_CANDIDATE_POINTS
    score -= TAMPER_PENALTY * tamper_flags
    # Rounded so float noise (0.1 + 0.2) never shows up in stored values or boundary checks.
    return round(min(1.0, max(0.0, score)), 6)


def refresh_evidence_score(report: Report) -> float:
    """Recompute from the report's stored evidence and extraction, and save it."""
    evidence = list(report.evidence.all())
    extraction = report.ai_extraction if isinstance(report.ai_extraction, dict) else {}
    observations = extraction.get("tamper_observations") or []
    # Per-evidence flags (e.g. duplicate_evidence) and the model's observations both count.
    flags = len(observations) + sum(len(e.tamper_flags or []) for e in evidence)
    score = evidence_score(
        (e.kind for e in evidence),
        has_story=bool(report.story_text.strip()),
        payment_proof_candidate=bool(extraction.get("payment_proof_candidate")),
        tamper_flags=flags,
    )
    if report.evidence_score != score:
        report.evidence_score = score
        report.save(update_fields=["evidence_score"])
    return score
