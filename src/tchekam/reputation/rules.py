"""Band rules (ADR-005 red threshold, ADR-006 bands, ADR-007 decay). Pure: no Django, no I/O.

1. Only approved, pending and needs_info reports are ever looked at.
2. An approved report's age runs from the earlier of its decision date and incident date.
   At 730 days or more it is ignored for public purposes.
3. Red iff (>= 3 independent reporters or any payment proof) among approved reports under
   730 days, and at least one approved report is under 365 days. Proof and recency only
   count from reporters with trust >= 0.3 (an erased reporter has trust 0).
4. Else orange if any approved report is under 730 days; else yellow if any is pending or
   needs_info; else green.

Invariant: lowering a reporter's trust, or erasing a reporter, never makes a band worse.
Trust only ever gates the red conditions, and every gate is "trusted reporter required".
"""

from collections.abc import Iterable
from datetime import date, datetime

from .facts import NO_APPEAL, AppealState, Band, BandResult, ReportFacts
from .independence import MIN_TRUST_WEIGHT, independent_reporters

FULL_WEIGHT_DAYS = 365  # under this, a report counts fully
VISIBLE_DAYS = 730  # at or over this, a report is hidden from the public
RED_MIN_INDEPENDENT_REPORTERS = 3

APPROVED = "approved"
AWAITING_REVIEW = frozenset({"pending", "needs_info"})


def compute_band(
    facts: Iterable[ReportFacts], now: datetime, appeal: AppealState = NO_APPEAL
) -> BandResult:
    today = now.date()
    live = [f for f in facts if not _predates_owner(f, appeal.number_acquired_at, now)]

    counted: list[tuple[ReportFacts, date]] = []
    for f in live:
        if f.status != APPROVED:
            continue
        reference = age_reference(f, now)
        if reference is not None and (today - reference).days < VISIBLE_DAYS:
            counted.append((f, reference))

    pending = sum(1 for f in live if f.status in AWAITING_REVIEW)
    independent = independent_reporters(f for f, _ in counted)
    trusted = [(f, reference) for f, reference in counted if f.reporter_trust >= MIN_TRUST_WEIGHT]
    has_proof = any(f.has_payment_proof for f, _ in trusted)
    has_recent = any((today - reference).days < FULL_WEIGHT_DAYS for _, reference in trusted)

    if (independent >= RED_MIN_INDEPENDENT_REPORTERS or has_proof) and has_recent:
        band = Band.RED
    elif counted:
        band = Band.ORANGE
    elif pending:
        band = Band.YELLOW
    else:
        band = Band.GREEN

    return BandResult(
        band=band,
        approved_count=len(counted),
        independent_reporters=independent,
        pending_count=pending,
        last_report_date=max((reference for _, reference in counted), default=None),
        single_report_with_proof=(band == Band.RED and independent < RED_MIN_INDEPENDENT_REPORTERS),
        under_appeal=appeal.under_appeal,
    )


def age_reference(f: ReportFacts, now: datetime) -> date | None:
    """Earlier of the decision date and the incident date. None if neither is known."""
    candidates = [d for d in (_local_date(f.decided_at, now), f.incident_date) if d is not None]
    return min(candidates, default=None)


def _predates_owner(f: ReportFacts, acquired: date | None, now: datetime) -> bool:
    """True if the report may be about the number's previous owner (appeal: "new to me").

    Either known date before the acquisition date is enough to exclude it.
    """
    if acquired is None:
        return False
    dates = (f.incident_date, _local_date(f.submitted_at, now))
    return any(d is not None and d < acquired for d in dates)


def _local_date(moment: datetime | None, now: datetime) -> date | None:
    # Calendar days are counted in now's timezone, so a decision at 23:30 UTC is the next
    # day in Douala, as the reader would see it.
    return None if moment is None else moment.astimezone(now.tzinfo).date()
