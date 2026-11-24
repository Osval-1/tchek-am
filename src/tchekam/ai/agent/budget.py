from decimal import ROUND_CEILING, Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tchekam.ai.models import AgentBudget, AgentReservation

from .context import RunContext
from .policy import authorize
from .schemas import AgentDenied


def billed_microusd(value) -> int | None:
    """Missing/invalid billing retains the conservative reservation; never assume zero."""
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            return None
        return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, ValueError, TypeError):
        return None


def reserve(ctx: RunContext, call_id: str, amount: int) -> AgentReservation:
    """Reserve before transport; uncertain calls retain the entire charge."""
    if amount <= 0:
        raise AgentDenied("unknown_price")
    day = timezone.localdate().isoformat()
    user_scope, global_scope = f"user:{ctx.user_id}:{day}", f"global:{day[:7]}"
    with transaction.atomic():
        authorize(ctx)
        # Everyone takes the global lock first, avoiding cross-user deadlocks.
        for scope in (global_scope, user_scope):
            AgentBudget.objects.get_or_create(scope=scope)
        global_row = AgentBudget.objects.select_for_update().get(scope=global_scope)
        user_row = AgentBudget.objects.select_for_update().get(scope=user_scope)
        if AgentReservation.objects.filter(call_id=call_id).exists():
            raise AgentDenied("call_replay")
        limits = (settings.AGENT_MONTHLY_BUDGET_MICROUSD, settings.AGENT_DAILY_BUDGET_MICROUSD)
        for row, limit in zip((global_row, user_row), limits, strict=True):
            if limit <= 0 or row.used + amount > limit:
                raise AgentDenied("budget")
        for row in (global_row, user_row):
            row.used += amount
            row.save(update_fields=["used"])
        return AgentReservation.objects.create(
            run_id=ctx.run_id,
            call_id=call_id,
            amount=amount,
            user_scope=user_scope,
            global_scope=global_scope,
        )


def settle(reservation_id: int, actual: int | None) -> None:
    with transaction.atomic():
        # Same lock ordering as reserve, even when settling an older period.
        scopes = AgentReservation.objects.get(pk=reservation_id)
        rows = [
            AgentBudget.objects.select_for_update().get(scope=s)
            for s in (scopes.global_scope, scopes.user_scope)
        ]
        reservation = AgentReservation.objects.select_for_update().get(pk=reservation_id)
        if reservation.status != "reserved":
            return
        if actual is None:
            reservation.status = "uncertain"
        else:
            if actual < 0 or actual > reservation.amount:
                # A configured upper bound was violated. Never refund or permit another call.
                reservation.status = "overrun"
                from tchekam.ai.models import AgentControl

                AgentControl.objects.filter(pk=1).update(enabled=False)
                from .retention import stop_all

                stop_all()
            else:
                for row in rows:
                    row.used -= reservation.amount - actual
                    row.save(update_fields=["used"])
                reservation.amount = actual
                reservation.status = "settled"
        reservation.save(update_fields=["amount", "status"])
