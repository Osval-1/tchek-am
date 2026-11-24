"""Agent stores use the existing retention lock-and-recheck runner."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncMonth

from tchekam.ai.models import (
    AgentBudget,
    AgentDelivery,
    AgentEntityReference,
    AgentRun,
    AgentTurn,
    AICallLog,
    AIUsageMonthly,
)


def held_runs():
    from tchekam.retention.hold import held_phones, held_reports, held_users

    return AgentRun.objects.filter(
        Q(legal_hold=True)
        | Q(user_id__in=held_users())
        | Q(linked_report_id__in=held_reports())
        | Q(agententityreference__value__in=held_phones())
    ).values("pk")


def rules():
    from tchekam.retention.rules import Rule, _count_deleted

    def history(model):
        return lambda now: model.objects.filter(created_at__lt=now - timedelta(days=7)).exclude(
            run_id__in=held_runs()
        )

    def terminal(now):
        return AgentRun.objects.filter(
            status__in=["complete", "discarded"], completed_at__lt=now - timedelta(days=32)
        ).exclude(pk__in=held_runs())

    def scrub_delivery(rows, now):
        rows.filter(status="pending").update(status="cancelled")
        return rows.update(text="")

    def calls(now):
        return AICallLog.objects.filter(created_at__lt=now - timedelta(days=90)).exclude(
            agent_run_id__in=held_runs()
        )

    def aggregate(rows, now):
        groups = (
            rows.annotate(month=TruncMonth("created_at"))
            .values("month", "purpose", "model")
            .annotate(calls=Count("pk"), tokens_in=Sum("tokens_in"), tokens_out=Sum("tokens_out"))
            .order_by()
        )
        for group in groups:
            row, _ = AIUsageMonthly.objects.get_or_create(
                month=group["month"].date(), purpose=group["purpose"], model=group["model"]
            )
            AIUsageMonthly.objects.filter(pk=row.pk).update(
                **{k: F(k) + group[k] for k in ("calls", "tokens_in", "tokens_out")}
            )
        return _count_deleted(rows, now)

    return (
        Rule("agent_turns", AgentTurn, history(AgentTurn), _count_deleted),
        Rule("agent_aliases", AgentEntityReference, history(AgentEntityReference), _count_deleted),
        Rule(
            "agent_delivery_content",
            AgentDelivery,
            lambda now: history(AgentDelivery)(now).exclude(text=""),
            scrub_delivery,
        ),
        Rule("agent_runs", AgentRun, terminal, _count_deleted),
        Rule(
            "agent_budgets",
            AgentBudget,
            lambda now: AgentBudget.objects.filter(created_at__lt=now - timedelta(days=32)).exclude(
                scope__in=AgentRun.objects.filter(pk__in=held_runs()).values(
                    "agentreservation__user_scope"
                )
            ),
            _count_deleted,
        ),
        Rule("ai_calls", AICallLog, calls, aggregate),
    )


def before_user_delete(sender, instance, **kwargs):
    from django.db.models import ProtectedError

    if AgentRun.objects.filter(user=instance, pk__in=held_runs()).exists():
        raise ProtectedError("Agent records are on legal hold.", {instance})
    AgentBudget.objects.filter(scope__startswith=f"user:{instance.pk}:").delete()


def before_user_save(sender, instance, **kwargs):
    if not instance.pk:
        return
    previous = sender.objects.filter(pk=instance.pk).values("blocked", "language").first()
    if previous is not None and (
        previous["blocked"] != instance.blocked or previous["language"] != instance.language
    ):
        from tchekam.conversations.models import Conversation

        from .execution import invalidate

        with transaction.atomic():
            conv = Conversation.objects.select_for_update().filter(user=instance).first()
            if conv:
                invalidate(conv)
                conv.save(update_fields=["agent_generation"])


def stop_all():
    from django.utils import timezone

    AgentRun.objects.filter(status__in=["pending", "running"]).update(
        status="discarded", outcome="kill_switch", completed_at=timezone.now()
    )
    AgentDelivery.objects.filter(status="pending").update(status="cancelled")


def control_saved(sender, instance, **kwargs):
    if not instance.enabled:
        stop_all()
