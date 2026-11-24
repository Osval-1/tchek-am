"""Tools return opaque handles. Authority and rendered copy remain in this process."""

import hashlib
import hmac
import json

from django.conf import settings
from django.db import transaction

from tchekam.ai.models import AgentOperation
from tchekam.conversations.models import BotUser, Conversation
from tchekam.i18n import t

from .context import RunContext, TrustedResult
from .execution import owned_message
from .policy import authorize, consume
from .schemas import (
    Advice,
    AgentDenied,
    Handoff,
    ImageRead,
    Language,
    MediaReference,
    NameLookup,
    NoArgs,
    Numbers,
    Pattern,
)

SCHEMAS = {
    "check_number": Numbers,
    "check_message": NoArgs,
    "what_to_do_next": Advice,
    "explain_scam_pattern": Pattern,
    "check_account_name": NameLookup,
    "check_photo": MediaReference,
    "read_image": ImageRead,
    "report_status": NoArgs,
    "start_report": NoArgs,
    "start_appeal": NoArgs,
    "set_language": Language,
}


def execute(ctx: RunContext, name: str, arguments: dict) -> str:
    consume(ctx, "tool_calls")
    if ctx.staged:
        raise AgentDenied("tool_limit")
    if name not in SCHEMAS:
        raise AgentDenied("tool_unknown")
    args = SCHEMAS[name].model_validate(arguments)
    payload = json.dumps([name, args.model_dump()], sort_keys=True, separators=(",", ":"))
    key = hmac.new(
        settings.AGENT_OPERATION_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    if not settings.AGENT_OPERATION_KEY:
        raise AgentDenied("audit_key")
    # Downloads, decoding and inference are bounded and outside Conversation transactions.
    media_result = None
    if name in ("check_photo", "read_image"):
        from .media import check_owned_photo, read_owned_image

        with transaction.atomic():
            Conversation.objects.select_for_update().get(user_id=ctx.user_id)
            authorize(ctx)
            _, created = AgentOperation.objects.get_or_create(
                run_id=ctx.run_id, key=key, defaults={"tool": name, "outcome": "pending"}
            )
            if not created:
                raise AgentDenied("media_replay")
        media_result = (
            check_owned_photo(ctx) if name == "check_photo" else read_owned_image(ctx, args.task)
        )
    with transaction.atomic():
        Conversation.objects.select_for_update().get(user_id=ctx.user_id)
        user = BotUser.objects.select_for_update().get(pk=ctx.user_id)
        run = authorize(ctx)
        previous = AgentOperation.objects.filter(run=run, key=key, outcome="allowed").first()
        # Creating the mandatory audit entry first makes audit failures fail closed.
        if previous is None:
            AgentOperation.objects.update_or_create(
                run=run, key=key, defaults={"tool": name, "outcome": "allowed"}
            )
        texts, transition = [], ""
        if name == "check_number":
            from tchekam.checks.limits import check_allowed
            from tchekam.checks.number import _check_one, render_number
            from tchekam.conversations.router import Context
            from tchekam.identifiers.models import PhoneNumber
            from tchekam.reputation.service import band_for_phone

            from .memory import remember_number, resolve_number

            numbers = list(dict.fromkeys(resolve_number(ctx, n) for n in args.numbers))
            for number in numbers:
                if previous is not None:
                    phone = PhoneNumber.objects.get(e164=number)
                    texts.append(
                        render_number(number, phone.operator, band_for_phone(number), ctx.lang).text
                    )
                elif check_allowed(user):
                    tool_ctx = Context(user, user.conversation, owned_message(run))
                    texts.append(_check_one(tool_ctx, number).text)
                    remember_number(ctx, number)
                else:
                    texts.append(t("check.limit_reached", ctx.lang))
                    break
        elif name == "check_message":
            from tchekam.checks.message import _log_if_allowed, build_reply
            from tchekam.checks.redflags import rule_flags

            msg = owned_message(run)
            if msg.kind != "text" or not msg.text:
                raise AgentDenied("source_type")
            if previous or _log_if_allowed(user, msg.text):
                # Rules-only mode deliberately avoids an unbudgeted legacy LLM child call.
                texts = [build_reply(msg.text, rule_flags(msg.text), ctx.lang)]
            else:
                texts = [t("check.limit_reached", ctx.lang)]
        elif name == "explain_scam_pattern":
            texts = [
                t(f"check.message.flag.{args.topic}", ctx.lang),
                t("check.message.caution", ctx.lang),
            ]
        elif name == "what_to_do_next":
            texts = [
                t("notify.next_steps" if args.topic == "next_steps" else "help.main", ctx.lang)
            ]
        elif name == "check_account_name":
            from tchekam.checks.limits import check_allowed
            from tchekam.checks.models import CheckLog
            from tchekam.identifiers.names import mask_name, normalize_name
            from tchekam.reports.models import ReportSubject

            if previous is None and not check_allowed(user):
                texts = [t("check.limit_reached", ctx.lang)]
            else:
                found = ReportSubject.objects.filter(
                    confirmed=True,
                    report__status="approved",
                    account_name__normalized=normalize_name(args.name),
                    account_name__provider=args.operator,
                ).exists()
                texts = [
                    t(
                        "agent.name.found" if found else "agent.name.none",
                        ctx.lang,
                        name=mask_name(args.name),
                    )
                ]
                if previous is None:
                    CheckLog.objects.create(
                        user=user, kind="name", subject_ref=key, result_band="none"
                    )
        elif name in ("check_photo", "read_image"):
            if name == "check_photo":
                from tchekam.checks.limits import check_allowed
                from tchekam.checks.models import CheckLog

                if previous is None and not check_allowed(user):
                    texts = [t("check.limit_reached", ctx.lang)]
                else:
                    texts = [media_result]
                    if previous is None:
                        CheckLog.objects.create(
                            user=user, kind="image", subject_ref=key, result_band="none"
                        )
            else:
                texts = [media_result]
        elif name == "report_status":
            # Caller-scoped; public status codes only, never notes or reporter fields.
            from tchekam.reports.models import Report

            statuses = list(
                Report.objects.filter(reporter=user)
                .order_by("-pk")
                .values_list("status", flat=True)[:5]
            )
            texts = [t("agent.status." + s, ctx.lang) for s in statuses] or [
                t("agent.status.none", ctx.lang)
            ]
        elif name in ("start_report", "start_appeal"):
            transition = Handoff(intent="report" if name == "start_report" else "appeal").intent
        elif name == "set_language":
            transition = f"lang:{args.lang}"
        else:
            raise AgentDenied("tool_unknown")
    # These aliases resolve only inside this server-owned run registry. They cannot
    # authorize a tool or replay a result from another run; keep them easy to copy.
    handle = f"r{len(ctx.results) + 1}"
    ctx.results[handle] = TrustedResult(name, tuple(texts), transition)
    if transition:
        ctx.staged = transition
    return handle


def definitions(ctx: RunContext, *, execute_fn=execute):
    from langchain_core.tools import StructuredTool

    descriptions = {
        "check_number": "Look up up to ten Cameroon phone numbers; code supplies the verdict.",
        "check_account_name": "Look up an account name; return a masked reviewed match.",
        "check_photo": "Internal photo reuse search for the owned image. No external upload.",
        "read_image": "Read numbers or XAF amounts from the owned image; requires confirmation.",
        "check_message": "Check the current user's inbound text for reviewed scam warning signs.",
        "what_to_do_next": "Reviewed help or next steps after sending money.",
        "explain_scam_pattern": "Reviewed general help about scam patterns.",
        "report_status": "List only the caller's report statuses.",
        "start_report": "Propose the existing report consent flow. Stops this agent turn.",
        "start_appeal": "Propose an appeal about the caller's own number. Stops this turn.",
        "set_language": "Propose changing the language. Stops this turn.",
    }

    def bind(name):
        def call(**kwargs):
            handle = execute_fn(ctx, name, kwargs)
            result = ctx.results[handle]
            kind = "results"
            if result.transition:
                kind = "language" if result.transition.startswith("lang:") else "handoff"
            # Server-authored receipt: copyable action, no raw tool payload or permissions.
            return json.dumps(
                {
                    "result_handle": handle,
                    "response_action": {
                        "kind": kind,
                        "handles": [handle],
                        "catalog": "number" if name == "check_number" else "text",
                    },
                }
            )

        return call

    return [
        StructuredTool.from_function(bind(n), name=n, description=descriptions[n], args_schema=s)
        for n, s in SCHEMAS.items()
    ]
