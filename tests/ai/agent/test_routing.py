from unittest.mock import patch

import pytest
from django.db import transaction

from tchekam.ai.models import AgentRun
from tchekam.conversations.models import Conversation
from tchekam.conversations.router import Context, route
from tchekam.messaging.parser import parse_wasender_payload

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "kind,text,agent",
    [
        ("text", "Is 677123456 OK to pay?", True),
        ("text", "And what should I do now?", True),
        ("text", "Is this a scam?", True),
        ("text", "Help me after I sent money", True),
        ("text", "677123456", False),
        ("text", "1", False),
        ("image", "payment screenshot", True),
        ("audio", "", True),
        ("text", "MENU", False),
        ("text", "STOP TRAINING", False),
        ("text", "report", False),
    ],
)
def test_routing_matrix(make_run, actor, kind, text, agent):
    source = make_run(text, kind=kind)
    event = source.inbound
    source.delete()  # fixture creates a stored inbound; the router must create the run itself
    conv = Conversation.objects.get(user=actor)
    context = Context(actor, conv, parse_wasender_payload(event.payload))
    with transaction.atomic(), patch("tchekam.conversations.router.dispatch", return_value=[]):
        route(context)
    assert AgentRun.objects.filter(inbound=event).exists() is agent
    if agent:
        assert context.jobs[0][0] == "agent.process"
        assert set(context.jobs[0][1]) == {"run_id", "queue", "lock"}


def test_agent_off_preserves_embedded_number_shortcut(make_run, actor, settings):
    settings.AGENT_ENABLED = False
    run = make_run("Check 677123456 please")
    msg = parse_wasender_payload(run.inbound.payload)
    run.delete()
    with patch("tchekam.conversations.router.dispatch", return_value=[]) as dispatch:
        route(Context(actor, Conversation.objects.get(user=actor), msg))
    assert dispatch.call_args.args[1] == "check_number"


def test_active_flow_is_never_agent(make_run, actor):
    run = make_run("And what now?")
    msg = parse_wasender_payload(run.inbound.payload)
    run.delete()
    conv = Conversation.objects.get(user=actor)
    conv.flow = "await_number"
    with patch("tchekam.conversations.router.queue_turn", create=True) as queue:
        route(Context(actor, conv, msg))
    assert not queue.called
    assert not AgentRun.objects.exists()
