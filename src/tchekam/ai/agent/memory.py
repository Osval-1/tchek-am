import hashlib
import hmac
import json
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from tchekam.ai.models import AgentEntityReference, AgentTurn

from .context import RunContext
from .schemas import AgentDenied, ResponseAction


def signature(
    *, user_id, generation, run_id, role, source, content, key_version, created_at
) -> str:
    key = settings.AGENT_MEMORY_KEYS.get(key_version)
    if not key:
        raise AgentDenied("memory_key")
    body = json.dumps(
        [user_id, generation, run_id, role, source, content, key_version, created_at.isoformat()],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hmac.new(key.encode(), body.encode(), hashlib.sha256).hexdigest()


def load(ctx: RunContext) -> list[dict]:
    rows = AgentTurn.objects.filter(
        user_id=ctx.user_id,
        generation=ctx.generation,
        run__status="complete",
        run__sequence__lt=ctx.sequence,
        created_at__gte=timezone.now() - timedelta(hours=settings.AGENT_HISTORY_HOURS),
    ).order_by("-run__sequence", "-id")[: settings.AGENT_HISTORY_MESSAGES]
    output, tokens = [], 0
    for row in rows:
        args = {
            k: getattr(row, k)
            for k in (
                "user_id",
                "generation",
                "run_id",
                "role",
                "source",
                "content",
                "key_version",
                "created_at",
            )
        }
        if not hmac.compare_digest(row.signature, signature(**args)):
            raise AgentDenied("memory_integrity")
        if row.role == "user" and row.source in ("text", "transcript"):
            text = row.content.get("text")
            if not isinstance(text, str) or len(text) > 4000:
                raise AgentDenied("memory_schema")
        elif row.role == "assistant" and row.source == "action":
            text = ResponseAction.model_validate(row.content).model_dump_json()
        else:
            raise AgentDenied("memory_provenance")
        # UTF-8 bytes is a conservative token upper bound, including mixed-language text.
        tokens += len(text.encode())
        if tokens > settings.AGENT_HISTORY_TOKENS:
            break
        output.append({"role": row.role, "source": row.source, "text": text})
    return list(reversed(output))


def persist(ctx: RunContext, text: str, action: ResponseAction) -> None:
    for role, source, content in (
        ("user", "text", {"text": text[:4000]}),
        ("assistant", "action", action.model_dump()),
    ):
        fields = dict(
            user_id=ctx.user_id,
            generation=ctx.generation,
            run_id=ctx.run_id,
            role=role,
            source=source,
            content=content,
            key_version=settings.AGENT_MEMORY_KEY_VERSION,
        )
        row = AgentTurn.objects.create(**fields, signature="")
        row.signature = signature(**fields, created_at=row.created_at)
        row.save(update_fields=["signature"])


def remember_number(ctx, value, alias="last_number"):
    fields = dict(
        user_id=ctx.user_id,
        generation=ctx.generation,
        run_id=ctx.run_id,
        alias=alias,
        value=value,
        key_version=settings.AGENT_MEMORY_KEY_VERSION,
    )
    row, _ = AgentEntityReference.objects.update_or_create(
        run_id=ctx.run_id, alias=alias, defaults={**fields, "signature": ""}
    )
    sig = signature(
        user_id=ctx.user_id,
        generation=ctx.generation,
        run_id=ctx.run_id,
        role="entity",
        source="number",
        content={"alias": alias, "value": value},
        key_version=fields["key_version"],
        created_at=row.created_at,
    )
    row.signature = sig
    row.save(update_fields=["signature"])


def resolve_number(ctx, value):
    from tchekam.identifiers.phone import normalize_cm_number

    if number := normalize_cm_number(value):
        return number
    if value != "last_number":
        raise AgentDenied("unknown_reference")
    row = (
        AgentEntityReference.objects.filter(
            user_id=ctx.user_id,
            generation=ctx.generation,
            alias=value,
            created_at__gte=timezone.now() - timedelta(hours=settings.AGENT_HISTORY_HOURS),
            run__status="complete",
            run__sequence__lt=ctx.sequence,
        )
        .order_by("-run__sequence")
        .first()
    )
    if row is None:
        raise AgentDenied("unknown_reference")
    expected = signature(
        user_id=row.user_id,
        generation=row.generation,
        run_id=row.run_id,
        role="entity",
        source="number",
        content={"alias": row.alias, "value": row.value},
        key_version=row.key_version,
        created_at=row.created_at,
    )
    if not hmac.compare_digest(expected, row.signature):
        raise AgentDenied("memory_integrity")
    return row.value
