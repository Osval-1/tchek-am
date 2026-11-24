"""Staff-only appeal pages (F6). Same access rules and privacy headers as the report pages.

The appellant is the owner of the appealed number, so no identity beyond that number is shown
and there is no reveal: no BotUser id, language or trust. Reporters are never shown here.
"""

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from tchekam.appeals import service
from tchekam.appeals.models import Appeal, AppealEvidence
from tchekam.core.audit import audit
from tchekam.core.http import client_ip
from tchekam.core.storage import get_object_store
from tchekam.reputation.service import band_for_phone

from .views import EVIDENCE_URL_TTL, _private, staff_required


def _viewable(appeal_id: int) -> Appeal:
    # Drafts are still being written by the appellant: staff must not browse them.
    return get_object_or_404(
        Appeal.objects.select_related("phone_number", "decided_by").exclude(status="draft"),
        pk=appeal_id,
    )


@staff_required
@require_GET
def queue(request: HttpRequest) -> HttpResponse:
    rows = (
        Appeal.objects.filter(status=Appeal.Status.OPEN)
        .select_related("phone_number")
        .order_by("submitted_at", "pk")
    )
    return _private(render(request, "moderation/appeal_queue.html", {"rows": rows}))


@staff_required
@require_GET
def review(request: HttpRequest, appeal_id: int) -> HttpResponse:
    appeal = _viewable(appeal_id)
    context = {
        "appeal": appeal,
        "band": band_for_phone(appeal.phone_number.e164),
        "reports": service.appealable_reports(appeal).order_by("decided_at", "pk"),
        "evidence": appeal.evidence.order_by("id"),
        "open": appeal.status == Appeal.Status.OPEN,
    }
    return _private(render(request, "moderation/appeal_review.html", context))


@staff_required
@require_POST
def decide(request: HttpRequest, appeal_id: int) -> HttpResponse:
    _viewable(appeal_id)
    try:
        result = service.decide(
            appeal_id,
            request.user,
            request.POST.get("action", ""),
            reason=request.POST.get("reason", ""),
            report_ids=[i for i in request.POST.getlist("report") if i.isdigit()],
            ip=client_ip(request),
        )
    except service.AppealError as exc:
        messages.error(request, str(exc))
        return redirect("moderation:appeal_review", appeal_id=appeal_id)
    messages.success(request, f"Appeal {appeal_id}: {result.appeal.status}.")
    return redirect("moderation:appeal_queue")


@staff_required
@require_GET
def evidence(request: HttpRequest, evidence_id: int) -> HttpResponse:
    item = get_object_or_404(
        AppealEvidence.objects.select_related("appeal").exclude(appeal__status="draft"),
        pk=evidence_id,
    )
    # Every request is logged, repeated views included.
    audit(request.user, "appeal_evidence.view", item, ip=client_ip(request))
    store = get_object_store()
    if not store.exists(item.object_key):
        raise Http404
    url = store.signed_url(item.object_key, ttl_seconds=EVIDENCE_URL_TTL)
    # Built by hand: HttpResponseRedirect refuses the memory:// URLs of the test store; the URL
    # comes from our own object store, never from user input.
    response = HttpResponse(status=302)
    response["Location"] = url
    return _private(response)
