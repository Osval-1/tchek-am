"""Plain values the reputation rules work on. No Django: the rules stay pure and fast to test."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class Band(StrEnum):
    """Public status band (ADR-006). Never stored as truth; always computed."""

    GREEN = "green"  # no reports
    YELLOW = "yellow"  # waiting for review
    ORANGE = "orange"  # reviewed, below the red threshold
    RED = "red"  # high risk


@dataclass(frozen=True)
class ReportFacts:
    """What the rules need to know about one report naming the subject."""

    report_id: int
    status: str  # Report.Status value
    # Pseudonymous reporter identity (Report.reporter_key); survives erasure. "" if unknown.
    reporter_key: str = ""
    reporter_phone: str | None = None  # E.164 of the reporter's account; None once erased
    reporter_trust: float = 1.0
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    incident_date: date | None = None
    has_payment_proof: bool = False  # moderator-confirmed
    subject_phones: frozenset[str] = frozenset()  # E.164 of every phone subject on the report
    # reporter_key_for() of each subject phone, so "names the other reporter" still matches
    # a reporter whose phone is gone (erased).
    subject_keys: frozenset[str] = frozenset()
    evidence_sha256s: frozenset[str] = frozenset()
    summary: str = ""  # summary_final


@dataclass(frozen=True)
class AppealState:
    under_appeal: bool
    # "This number is new to me": reports dated before this belong to a previous owner.
    number_acquired_at: date | None


NO_APPEAL = AppealState(under_appeal=False, number_acquired_at=None)


@dataclass(frozen=True)
class BandResult:
    band: Band
    approved_count: int  # approved reports aged under 24 months
    independent_reporters: int  # among those reports
    pending_count: int  # pending + needs_info
    last_report_date: date | None  # newest age reference among counted approved reports
    single_report_with_proof: bool  # red reached through payment proof, not 3 reporters
    under_appeal: bool
