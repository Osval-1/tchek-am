from datetime import timedelta

import pytest
from django.utils import timezone

from tchekam.conversations import router
from tchekam.conversations.models import BotUser, Conversation
from tchekam.conversations.service import handle_private_message
from tchekam.i18n import t
from tchekam.messaging.channel import InboundMessage

PHONE = "237670000099"
IMAGE = {"type": "imageMessage", "mimetype": "image/jpeg"}
VCARD = "BEGIN:VCARD\nFN:Seller\nTEL;type=CELL;waid=237690000000:+237 690 00 00 00\nEND:VCARD"


def msg(text=None, kind="text", media=None, message_id="M1", phone=PHONE):
    return InboundMessage(
        message_id=message_id,
        sender_phone=phone,
        sender_jid=f"{phone}@s.whatsapp.net",
        chat_type="private",
        group_jid=None,
        kind=kind,
        text=text,
        media=media,
        timestamp=1,
        raw_event="messages.received",
    )


def send(*args, **kwargs) -> str:
    replies = handle_private_message(msg(*args, **kwargs))
    return "\n".join(r.text for r in replies)


@pytest.fixture
def calls(monkeypatch):
    """Replace every intent with a recorder so tests see what the router dispatched."""
    seen: list[tuple[str, dict]] = []
    for name in (
        "check_number",
        "check_photo",
        "check_message",
        "report",
        "appeal",
        "help",
        "group_opt_out",
        "training_opt_out",
    ):

        def handler(ctx, name=name):
            seen.append((name, dict(ctx.extra)))
            return [router.Reply(f"handled:{name}")]

        monkeypatch.setitem(router.INTENTS, name, handler)
    return seen


@pytest.fixture
def user(db):
    u = BotUser.objects.create(wa_phone=f"+{PHONE}", language="en")
    Conversation.objects.create(user=u)
    return u


def test_new_user_gets_picker_in_all_languages(db):
    out = send("hello")

    assert "1. Français" in out and "2. English" in out and "3. Pidgin" in out
    assert BotUser.objects.get().language is None


def test_choosing_2_sets_english_and_shows_menu_with_terms(db, settings):
    settings.TERMS_URL = "https://example.test/terms"
    send("hello")

    out = send("2")

    assert BotUser.objects.get().language == "en"
    assert out.startswith(t("menu.welcome", "en"))
    assert t("menu.main", "en") in out
    assert "https://example.test/terms" in out
    assert "1. Check a number" in out and "5. Help" in out and "0 = menu, LANG = language" in out


def test_invalid_pick_repeats_picker(db):
    send("hello")

    out = send("banana")

    assert out == t("lang.picker", None)
    assert BotUser.objects.get().language is None


@pytest.mark.parametrize(
    ("kwargs", "intent", "extra"),
    [
        ({"text": "677123456"}, "check_number", {"numbers": ["+237677123456"]}),
        ({"text": "233 42 11 22"}, "check_number", {"numbers": ["+237233421122"]}),
        (
            {"text": "Il m'a demandé 25000 sur le 6 77 12 34 56 et le 699 00 11 22"},
            "check_number",
            {"numbers": ["+237677123456", "+237699001122"]},
        ),
        (
            {"text": "6 70 00 00 01 / 6 70 00 00 02 / 6 70 00 00 03 / 6 70 00 00 04"},
            "check_number",
            None,
        ),
        ({"kind": "contact", "text": VCARD}, "check_number", {"numbers": ["+237690000000"]}),
        ({"kind": "audio", "media": {"type": "audioMessage"}}, "report", {}),
        ({"text": "signaler"}, "report", {}),
        ({"text": "Signalement"}, "report", {}),
        ({"text": "ARNAQUE!"}, "report", {}),
        ({"text": "scam"}, "report", {}),
        ({"text": "4"}, "report", {}),
        ({"text": "je veux signaler une arnaque"}, "report", {}),
        ({"text": "I want to report a scam"}, "report", {}),
        ({"text": "j'ai besoin d'aide"}, "help", {}),
        ({"text": "aide"}, "help", {}),
        ({"text": "Help"}, "help", {}),
        ({"text": "5"}, "help", {}),
        ({"text": "Votre compte est bloqué, cliquez ici"}, "check_message", {}),
        (
            {"text": "I think this is a scam message sent to my cousin yesterday"},
            "check_message",
            {},
        ),
    ],
)
def test_idle_routing(user, calls, kwargs, intent, extra):
    send(**kwargs)

    assert [name for name, _ in calls] == [intent]
    if extra is not None:
        assert calls[0][1] == extra
    else:
        assert len(calls[0][1]["numbers"]) == 4  # the handler applies its own cap


def test_image_asks_choice_and_stores_pending(user, calls):
    out = send(kind="image", media=IMAGE, message_id="IMG1", text="look")

    assert out == t("image.choice", "en")
    conv = Conversation.objects.get()
    assert conv.flow == "image_choice"
    assert conv.state == {"pending_image": IMAGE, "pending_image_msg_id": "IMG1"}
    assert calls == []


@pytest.mark.parametrize(("choice", "intent"), [("1", "check_photo"), ("2", "report")])
def test_image_choice_dispatches_with_pending_image(user, calls, choice, intent):
    send(kind="image", media=IMAGE, message_id="IMG1")

    send(choice)

    assert calls == [(intent, {"image": IMAGE, "image_msg_id": "IMG1"})]
    assert Conversation.objects.get().flow == "idle"


def test_image_choice_repeats_on_other_input(user, calls):
    send(kind="image", media=IMAGE)

    assert send("maybe") == t("image.choice", "en")
    assert Conversation.objects.get().flow == "image_choice"


@pytest.mark.parametrize(
    ("digit", "prompt", "text", "intent"),
    [
        ("1", "prompt.send_number", "677123456", "check_number"),
        ("3", "prompt.send_message", "Free money, click now", "check_message"),
    ],
)
def test_menu_digit_prompts_then_dispatches(user, calls, digit, prompt, text, intent):
    assert send(digit) == t(prompt, "en")
    assert calls == []

    send(text)

    assert [n for n, _ in calls] == [intent]


def test_menu_2_waits_for_photo(user, calls):
    assert send("2") == t("prompt.send_photo", "en")
    assert send("hello") == t("prompt.expected_photo", "en")

    send(kind="image", media=IMAGE, message_id="IMG2")

    assert calls == [("check_photo", {"image": IMAGE, "image_msg_id": "IMG2"})]


def test_await_number_without_number_reprompts(user, calls):
    send("1")

    assert send("no digits here") == t("prompt.no_number", "en")
    assert calls == []


def test_active_flow_takes_precedence_over_routing(user, calls):
    send("3")

    send("677123456 signaler")  # would normally route to check_number

    assert [n for n, _ in calls] == ["check_message"]


@pytest.mark.parametrize("command", ["MENU", "menu", "0"])
def test_menu_resets_flow_and_state(user, calls, command):
    send(kind="image", media=IMAGE)

    out = send(command)

    conv = Conversation.objects.get()
    assert (conv.flow, conv.state) == ("idle", {})
    assert out.startswith(t("menu.main", "en"))
    assert calls == []


@pytest.mark.parametrize("command", ["LANG", "langue", "Langage"])
def test_lang_reopens_picker_even_inside_a_flow(user, command):
    send("1")

    assert send(command) == t("lang.picker", "en")
    send("3")

    assert BotUser.objects.get().language == "pcm"
    assert Conversation.objects.get().flow == "idle"


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("STOP GROUP", "group_opt_out"),
        ("stop groupe", "group_opt_out"),
        ("Stop Training", "training_opt_out"),
    ],
)
def test_reserved_stop_commands_win_even_inside_flows(user, calls, text, intent):
    send("3")

    send(text)

    assert [n for n, _ in calls] == [intent]


def test_unregistered_intent_replies_coming_soon(user, monkeypatch):
    monkeypatch.delitem(router.INTENTS, "report", raising=False)

    assert send("signaler") == t("common.coming_soon", "en")


def test_help_intent_is_built_in(user):
    assert send("help") == t("help.main", "en")


def test_blocked_user_gets_no_reply(user, calls):
    user.blocked = True
    user.save()

    assert handle_private_message(msg("677123456")) == []
    assert calls == []


def test_last_inbound_at_updates_on_every_message(db):
    send("hello")
    first = BotUser.objects.get().last_inbound_at
    send("hello again")

    assert first is not None
    assert BotUser.objects.get().last_inbound_at > first


def test_unknown_flow_is_reset(user, calls):
    conv = Conversation.objects.get()
    conv.flow = "retired_flow"
    conv.save()

    send("hello there")

    assert [n for n, _ in calls] == ["check_message"]


def test_registered_flow_handler_is_dispatched(user, calls, monkeypatch):
    monkeypatch.setitem(router.FLOWS, "report", lambda ctx: [router.Reply("in report flow")])
    conv = Conversation.objects.get()
    conv.flow = "report"
    conv.save()

    assert send("677123456") == "in report flow"


def test_welcome_is_shown_only_after_language_pick(user):
    assert t("menu.welcome", "en") not in send("0")


@pytest.mark.parametrize("digit", ["6", "9", "12"])
def test_menu_digit_out_of_range_reshows_menu(user, calls, digit):
    assert send(digit).startswith(t("menu.main", "en"))
    assert calls == []


def _expire(conv):
    conv.expires_at = timezone.now() - timedelta(seconds=1)
    conv.save()


def test_prompt_flows_expire_after_30_minutes(user):
    send("1")
    conv = Conversation.objects.get()
    assert timedelta(minutes=29) < conv.expires_at - timezone.now() <= timedelta(minutes=30)


def test_expired_await_flow_is_dropped(user, calls):
    send("1")
    _expire(Conversation.objects.get())

    send("just some plain text")

    assert [n for n, _ in calls] == ["check_message"]


def test_expired_image_choice_drops_pending_image(user, calls):
    send(kind="image", media=IMAGE)
    _expire(Conversation.objects.get())

    send("1")

    # "1" is read as the main-menu choice, not as "product photo" for the dropped image.
    assert calls == []
    conv = Conversation.objects.get()
    assert (conv.flow, conv.state) == ("await_number", {})


def test_start_flow_sets_ttl_and_state(user):
    conv = Conversation.objects.get()

    router.start_flow(conv, "report", step="ask", state={"a": 1}, ttl=timedelta(hours=24))

    assert (conv.flow, conv.step, conv.state) == ("report", "ask", {"a": 1})
    assert timedelta(hours=23) < conv.expires_at - timezone.now() <= timedelta(hours=24)


def test_routing_runs_inside_a_transaction_holding_the_row_lock(user, monkeypatch):
    from django.db import connection

    seen = []
    monkeypatch.setitem(
        router.INTENTS, "check_message", lambda ctx: seen.append(connection.in_atomic_block) or []
    )

    send("hello there")

    assert seen == [True]
