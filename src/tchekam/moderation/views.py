"""Staff-only moderation pages. Thin: rules and state changes live in service.py."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from tchekam.core.audit import audit
from tchekam.core.http import client_ip
from tchekam.core.storage import get_object_store
from tchekam.identifiers.models import AccountName
from tchekam.reports.models import Evidence, Report, ReportLink, ReportSubject
from tchekam.reports.weighting import is_limited
from tchekam.reputation.service import band_for_phone

from . import service
from .forms import REJECT_REASONS
from .priority import queue_rows

EVIDENCE_URL_TTL = 300  # seconds
# Draft and withdrawn reports may have no consent: staff must not browse their content.
HIDDEN_STATUSES = ("draft", "withdrawn")


def staff_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Anonymous or no OTP -> admin login (which asks for the token); not staff -> 403."""

    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = request.user
        if not (user.is_authenticated and user.is_active):
            return redirect_to_login(request.get_full_path(), reverse("admin:login"))
        if not user.is_staff:
            raise PermissionDenied
        # Fail closed: a password-only session never reaches evidence.
        if not user.is_verified():
            return redirect_to_login(request.get_full_path(), reverse("admin:login"))
        return view(request, *args, **kwargs)

    return wrapper


def _private(response: HttpResponse) -> HttpResponse:
    # Pages show victims' evidence: never cached, never leak the URL through Referer.
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _viewable_report(report_id: int) -> Report:
    return get_object_or_404(Report.objects.exclude(status__in=HIDDEN_STATUSES), pk=report_id)


@staff_required
@require_GET
def queue(request: HttpRequest) -> HttpResponse:
    return _private(render(request, "moderation/queue.html", {"rows": queue_rows()}))


@staff_required
@require_GET
def review(request: HttpRequest, report_id: int) -> HttpResponse:
    report = _viewable_report(report_id)
    subjects = list(report.subjects.select_related("phone_number", "account_name").order_by("id"))
    sellers = [s for s in subjects if s.phone_number_id and s.role == ReportSubject.Role.SELLER]
    bands = [(s.phone_number.e164, band_for_phone(s.phone_number.e164)) for s in sellers]
    links = ReportLink.objects.filter(Q(report_a=report) | Q(report_b=report)).select_related(
        "report_a", "report_b"
    )
    linked = [
        (link.report_b if link.report_a_id == report.pk else link.report_a, link) for link in links
    ]
    extraction = report.ai_extraction if isinstance(report.ai_extraction, dict) else {}
    reporter = report.reporter
    history = None
    if reporter is not None:
        counts = dict(
            Report.objects.filter(reporter=reporter)
            .exclude(status__in=HIDDEN_STATUSES)
            .values_list("status")
            .annotate(n=Count("id"))
        )
        history = {
            "approved": counts.get("approved", 0),
            "rejected": counts.get("rejected", 0),
            "pending": counts.get("pending", 0) + counts.get("needs_info", 0),
            "trust_weight": reporter.trust_weight,
            "blocked": reporter.blocked,
            # Counts only: a warning must not reveal more about the reporter than the history does.
            "limited": is_limited(reporter.trust_weight, counts.get("rejected", 0)),
        }
    context = {
        "report": report,
        "evidence": report.evidence.order_by("id"),
        "subjects": subjects,
        "bands": bands,
        "linked": linked,
        "decisions": report.decisions.select_related("moderator").order_by("-created_at"),
        "tamper_observations": extraction.get("tamper_observations") or [],
        "payment_proof_candidate": bool(extraction.get("payment_proof_candidate")),
        "history": history,
        "can_edit": report.status in service.EDITABLE_STATUSES,
        "token": service.state_token(report),
        "reject_reasons": REJECT_REASONS,
        "scam_types": Report.ScamType.choices,
        "providers": AccountName.Provider.choices,
    }
    return _private(render(request, "moderation/review.html", context))


def _stale(request: HttpRequest, report_id: int) -> HttpResponse:
    response = render(request, "moderation/stale.html", {"report_id": report_id}, status=409)
    return _private(response)


@staff_required
@require_POST
def save(request: HttpRequest, report_id: int) -> HttpResponse:
    _viewable_report(report_id)  # 404 for draft/withdrawn: no existence leak via messages
    try:
        changed = service.save_edits(report_id, request.user, request.POST, ip=client_ip(request))
    except service.StaleReport:
        return _stale(request, report_id)
    except service.ModerationError as exc:
        for message in exc.messages:
            messages.error(request, message)
    else:
        messages.success(request, "Changes saved." if changed else "Nothing to change.")
    return redirect("moderation:review", report_id=report_id)


@staff_required
@require_POST
def decide(request: HttpRequest, report_id: int) -> HttpResponse:
    _viewable_report(report_id)  # 404 for draft/withdrawn: no existence leak via messages
    try:
        decision = service.decide(report_id, request.user, request.POST, ip=client_ip(request))
    except service.StaleReport:
        return _stale(request, report_id)
    except service.ModerationError as exc:
        for message in exc.messages:
            messages.error(request, message)
        return redirect("moderation:review", report_id=report_id)
    messages.success(
        request, f"Report {decision.report.reference or report_id}: {decision.action}."
    )
    return redirect("moderation:queue")


@staff_required
@require_POST
def reveal(request: HttpRequest, report_id: int) -> HttpResponse:
    report = _viewable_report(report_id)
    reporter = report.reporter
    audit(request.user, "reporter.reveal", report, ip=client_ip(request))
    # Shown in this response only: not kept in the session, a message or a URL.
    context = {"report": report, "number": reporter.wa_phone if reporter else None}
    return _private(render(request, "moderation/reveal.html", context))


@staff_required
@require_GET
def evidence(request: HttpRequest, evidence_id: int) -> HttpResponse:
    item = get_object_or_404(
        Evidence.objects.select_related("report").exclude(report__status__in=HIDDEN_STATUSES),
        pk=evidence_id,
    )
    # Every request is logged, repeated views included.
    audit(request.user, "evidence.view", item, ip=client_ip(request))
    store = get_object_store()
    if not store.exists(item.object_key):
        raise Http404
    url = store.signed_url(item.object_key, ttl_seconds=EVIDENCE_URL_TTL)
    # Built by hand: HttpResponseRedirect refuses the memory:// URLs of the test store, and
    # the URL comes from our own object store, never from user input.
    response = HttpResponse(status=302)
    response["Location"] = url
    return _private(response)
