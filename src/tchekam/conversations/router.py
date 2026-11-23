"""Input router: turns one inbound private message into replies.

Flow and intent handlers register here by name. Later issues plug in by calling
`register_intent` / `register_flow`; intents nobody has registered answer "coming soon".
"""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from tchekam.i18n import t
from tchekam.identifiers.phone import find_numbers, normalize_cm_number
from tchekam.messaging.channel import InboundMessage

from .models import BotUser, Conversation

MAX_NUMBERS = 10  # the check handler decides how many it actually checks
# Keywords only count in short messages, so a pasted message that mentions "scam" is still checked.
# Verbs state an intent ("je veux signaler une arnaque"), so they get a longer allowance than
# the bare nouns, which also appear in pasted scam messages.
VERB_MAX_WORDS = 8
NOUN_MAX_WORDS = 4
PROMPT_TTL = timedelta(minutes=30)
LANGUAGES = {"1": BotUser.Language.FR, "2": BotUser.Language.EN, "3": BotUser.Language.PCM}
REPORT_VERBS = {"report", "signaler", "signalement"}
REPORT_NOUNS = {"arnaque", "scam"}
HELP_WORDS = {"help", "aide"}
GLOBAL_COMMANDS = {
    "menu": "menu",
    "0": "menu",
    "lang": "lang",
    "langue": "lang",
    "langage": "lang",
    "stop group": "group_opt_out",
    "stop groupe": "group_opt_out",
    "stop training": "training_opt_out",
}
# Menu digit -> prompt flow that waits for the input, then dispatches the intent.
MENU_PROMPTS = {
    "1": ("await_number", "prompt.send_number"),
    "2": ("await_photo", "prompt.send_photo"),
    "3": ("await_message", "prompt.send_message"),
}


@dataclass
class Reply:
    text: str
    image_url: str | None = None


@dataclass
class Context:
    user: BotUser
    conversation: Conversation
    msg: InboundMessage
    extra: dict[str, Any] = field(default_factory=dict)  # intent arguments, e.g. "numbers"

    @property
    def lang(self) -> str | None:
        return self.user.language


Handler = Callable[[Context], list[Reply]]
FLOWS: dict[str, Handler] = {}
INTENTS: dict[str, Handler] = {}


def register_flow(name: str, handler: Handler) -> None:
    FLOWS[name] = handler


def register_intent(name: str, handler: Handler) -> None:
    INTENTS[name] = handler


def say(ctx: Context, key: str, **fmt: object) -> list[Reply]:
    return [Reply(t(key, ctx.lang, **fmt))]


def dispatch(ctx: Context, intent: str, **extra: Any) -> list[Reply]:
    """Leave any prompt flow and hand over to an intent; the handler may start its own flow."""
    ctx.conversation.reset()
    ctx.extra.update(extra)
    handler = INTENTS.get(intent)
    if handler is None:
        return say(ctx, "common.coming_soon")
    return handler(ctx)


def start_flow(
    conv: Conversation,
    name: str,
    step: str = "",
    state: dict[str, Any] | None = None,
    ttl: timedelta | None = None,
) -> None:
    """Enter a flow. With a ttl the router drops the flow once it has gone stale."""
    conv.flow = name
    conv.step = step
    conv.state = state or {}
    conv.expires_at = timezone.now() + ttl if ttl else None


def _normalize(text: str | None) -> str:
    """Lower-case, accent-free, punctuation-free, single-spaced."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", stripped).split())


def _numbers(msg: InboundMessage) -> list[str]:
    """Cameroonian numbers in a text or contact card, as E.164, at most MAX_NUMBERS."""
    text = msg.text or ""
    if msg.kind == "contact":
        values = [line.partition(":")[2] for line in text.splitlines() if line[:3].upper() == "TEL"]
        found = [n for v in values if (n := normalize_cm_number(v))]
    elif msg.kind == "text":
        # A number typed alone may be a fixed line; inside a sentence only mobiles are matched.
        alone = normalize_cm_number(text.strip())
        found = [alone] if alone else find_numbers(text)
    else:
        found = []
    return list(dict.fromkeys(found))[:MAX_NUMBERS]


def _show_menu(ctx: Context, first: bool = False) -> list[Reply]:
    ctx.conversation.reset()
    parts = [t("menu.main", ctx.lang), t("menu.terms", ctx.lang, url=settings.TERMS_URL)]
    if first:  # the welcome line is for the first menu after onboarding only
        parts.insert(0, t("menu.welcome", ctx.lang))
    return [Reply("\n\n".join(parts))]


def _start_language_picker(ctx: Context) -> list[Reply]:
    ctx.conversation.reset()
    start_flow(ctx.conversation, "language_pick")
    return say(ctx, "lang.picker")


def _language_pick(ctx: Context) -> list[Reply]:
    choice = LANGUAGES.get(_normalize(ctx.msg.text)) if ctx.msg.kind == "text" else None
    if choice is None:
        return say(ctx, "lang.picker")
    ctx.user.language = choice
    ctx.user.save(update_fields=["language"])
    return _show_menu(ctx, first=True)


def _ask_image_choice(ctx: Context) -> list[Reply]:
    state = {"pending_image": ctx.msg.media, "pending_image_msg_id": ctx.msg.message_id}
    start_flow(ctx.conversation, "image_choice", state=state, ttl=PROMPT_TTL)
    return say(ctx, "image.choice")


def _image_choice(ctx: Context) -> list[Reply]:
    state = ctx.conversation.state
    if ctx.msg.kind == "image":  # a newer image replaces the pending one
        return _ask_image_choice(ctx)
    choice = _normalize(ctx.msg.text) if ctx.msg.kind == "text" else ""
    intent = {"1": "check_photo", "2": "report"}.get(choice)
    if intent is None:
        return say(ctx, "image.choice")
    return dispatch(
        ctx,
        intent,
        image=state.get("pending_image"),
        image_msg_id=state.get("pending_image_msg_id"),
    )


def _await_number(ctx: Context) -> list[Reply]:
    numbers = _numbers(ctx.msg)
    if not numbers:
        return say(ctx, "prompt.no_number")
    return dispatch(ctx, "check_number", numbers=numbers)


def _await_photo(ctx: Context) -> list[Reply]:
    if ctx.msg.kind != "image":
        return say(ctx, "prompt.expected_photo")
    return dispatch(ctx, "check_photo", image=ctx.msg.media, image_msg_id=ctx.msg.message_id)


def _await_message(ctx: Context) -> list[Reply]:
    if ctx.msg.kind != "text" or not ctx.msg.text:
        return say(ctx, "prompt.expected_message")
    return dispatch(ctx, "check_message")


def _route_idle(ctx: Context) -> list[Reply]:
    msg = ctx.msg
    if msg.kind == "image":
        return _ask_image_choice(ctx)
    if msg.kind == "audio":
        return dispatch(ctx, "report")
    if msg.kind not in ("text", "contact"):
        return say(ctx, "common.unsupported")
    numbers = _numbers(msg)
    if numbers:
        return dispatch(ctx, "check_number", numbers=numbers)
    if msg.kind == "contact":
        return say(ctx, "prompt.no_number")

    norm = _normalize(msg.text)
    if not norm:
        return say(ctx, "common.unsupported")
    if norm in MENU_PROMPTS:
        flow, prompt = MENU_PROMPTS[norm]
        start_flow(ctx.conversation, flow, ttl=PROMPT_TTL)
        return say(ctx, prompt)
    # Count on the raw whitespace split so elisions ("j'ai") are one word, not two.
    count = len((msg.text or "").split())
    words = set(norm.split())
    if norm == "4" or (count <= VERB_MAX_WORDS and words & REPORT_VERBS):
        return dispatch(ctx, "report")
    if count <= NOUN_MAX_WORDS and words & REPORT_NOUNS:
        return dispatch(ctx, "report")
    if norm == "5" or (count <= VERB_MAX_WORDS and words & HELP_WORDS):
        return dispatch(ctx, "help")
    if norm.isdigit() and len(norm) <= 2:  # a menu choice that does not exist
        return _show_menu(ctx)
    return dispatch(ctx, "check_message")


def _route(ctx: Context) -> list[Reply]:
    conv = ctx.conversation
    if ctx.user.language is None:
        # Onboarding comes before everything, including commands: no language, no copy.
        return _language_pick(ctx) if conv.flow == "language_pick" else _start_language_picker(ctx)

    command = GLOBAL_COMMANDS.get(_normalize(ctx.msg.text)) if ctx.msg.kind == "text" else None
    if command == "menu":
        return _show_menu(ctx)
    if command == "lang":
        return _start_language_picker(ctx)
    if command:
        return dispatch(ctx, command)

    if conv.expires_at and conv.expires_at <= timezone.now():
        conv.reset()  # a stale prompt must not swallow a fresh message
    if conv.flow != Conversation.IDLE:
        handler = FLOWS.get(conv.flow)
        if handler is not None:
            return handler(ctx)
        conv.reset()  # flow from an older deploy that no longer exists
    return _route_idle(ctx)


def route(ctx: Context) -> list[Reply]:
    """Route one message; persists the conversation. Blocked users get no reply."""
    if ctx.user.blocked:
        return []
    replies = _route(ctx)
    ctx.conversation.save()
    return replies


def _help(ctx: Context) -> list[Reply]:
    return say(ctx, "help.main")


register_intent("help", _help)
register_flow("language_pick", _language_pick)
register_flow("image_choice", _image_choice)
register_flow("await_number", _await_number)
register_flow("await_photo", _await_photo)
register_flow("await_message", _await_message)
