"""Independent reporters (ADR-005): clusters of reporters that may be one person, via union-find.

Two reporters are dependent if they share a reporter_key (same person, even after erasure),
if one's report names the other (by phone, or by key once the phone is erased), or if they
submitted within 10 minutes of each other and shared an evidence file or near-identical text.
Dependency is transitive.

Every reporter takes part in clustering, whatever their trust, so a low-trust or erased
reporter still links the people around them. The count is the number of clusters holding at
least one reporter with trust >= MIN_TRUST_WEIGHT. Lowering trust or erasing a reporter can
therefore only lower the count, never raise it.
"""

from collections.abc import Iterable
from datetime import timedelta
from difflib import SequenceMatcher
from itertools import combinations

from .facts import ReportFacts

MIN_TRUST_WEIGHT = 0.3  # below this a reporter does not count on their own (Issue 16)
NEAR_IDENTICAL_WINDOW = timedelta(minutes=10)
TEXT_SIMILARITY = 0.9

Node = tuple[str, str | int]


def independent_reporters(reports: Iterable[ReportFacts]) -> int:
    reports = list(reports)
    parent: dict[Node, Node] = {_node(r): _node(r) for r in reports}  # same key -> same node

    def find(node: Node) -> Node:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for a, b in combinations(reports, 2):
        if _dependent(a, b):
            parent[find(_node(a))] = find(_node(b))
    return len({find(_node(r)) for r in reports if r.reporter_trust >= MIN_TRUST_WEIGHT})


def _node(report: ReportFacts) -> Node:
    # Tagged tuples, so a fallback can never collide with a real key.
    if report.reporter_key:
        return ("reporter", report.reporter_key)
    if report.reporter_phone:  # live reporter without a key: not expected (DB constraint)
        return ("phone", report.reporter_phone)
    return ("report", report.report_id)  # nobody to match it to: it stands alone


def _dependent(a: ReportFacts, b: ReportFacts) -> bool:
    return _names(a, b) or _names(b, a) or _near_identical(a, b)


def _names(a: ReportFacts, b: ReportFacts) -> bool:
    """True if report a names b's reporter as a subject."""
    by_phone = b.reporter_phone is not None and b.reporter_phone in a.subject_phones
    by_key = bool(b.reporter_key) and b.reporter_key in a.subject_keys
    return by_phone or by_key


def _near_identical(a: ReportFacts, b: ReportFacts) -> bool:
    if a.submitted_at is None or b.submitted_at is None:
        return False
    if abs(a.submitted_at - b.submitted_at) > NEAR_IDENTICAL_WINDOW:
        return False
    if a.evidence_sha256s & b.evidence_sha256s:
        return True
    if not (a.summary and b.summary):
        return False
    return SequenceMatcher(None, a.summary, b.summary).ratio() >= TEXT_SIMILARITY
