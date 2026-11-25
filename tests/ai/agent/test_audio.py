import io
import json
import wave
from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest
from django.utils import timezone

from tchekam.ai.agent.execution import claim
from tchekam.ai.agent.graph import build_graph
from tchekam.ai.agent.media import transcribe_owned_audio
from tchekam.ai.agent.models import fake_model
from tchekam.ai.agent.schemas import AgentDenied
from tchekam.ai.agent.tasks import reconcile
from tchekam.ai.models import AgentBudget, AgentReservation, AgentRun, AICallLog
from tchekam.speech.base import Transcript
from tchekam.speech.openrouter import OpenRouterSTT

pytestmark = pytest.mark.django_db(transaction=True)


def wav(seconds=1):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * (8000 * seconds))
    return buffer.getvalue()


@pytest.mark.parametrize(
    "cost,expected,status", [(0.00002, 20, "settled"), (None, 60, "uncertain")]
)
def test_agent_stt_uses_persistent_limits_shared_budget_and_content_free_audit(
    make_run, settings, cost, expected, status
):
    settings.SPEECH_MAX_COST_MICROUSD = 60
    ctx = claim(make_run(kind="audio").pk)
    seen = []

    def handler(request):
        seen.append(request)
        payload = {"text": "private spoken text", "usage": {}}
        if cost is not None:
            payload["usage"]["cost"] = cost
        return httpx.Response(200, json=payload)

    stt = OpenRouterSTT(context=ctx, api_key="synthetic", transport=httpx.MockTransport(handler))
    assert stt.transcribe(wav(), "audio/wav").text == "private spoken text"
    assert ctx.model_calls == ctx.stt_calls == 1
    assert set(AgentBudget.objects.values_list("used", flat=True)) == {expected}
    assert AgentReservation.objects.get().status == status
    assert not stt.transcribe(wav(), "audio/wav").text
    assert len(seen) == 1
    assert "private spoken text" not in json.dumps(list(AICallLog.objects.values()), default=str)


def test_stt_limit_survives_worker_recovery_before_media_download(make_run, settings):
    settings.SPEECH_MAX_COST_MICROUSD = 60
    run = make_run(kind="audio")
    ctx = claim(run.pk)
    client = OpenRouterSTT(
        context=ctx,
        api_key="synthetic",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"text": "heard"})),
    )
    assert client.transcribe(wav(), "audio/wav").text
    AgentRun.objects.filter(pk=run.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    with patch("tchekam.ai.agent.tasks.enqueue"):
        reconcile()
    current = claim(run.pk)
    assert current.stt_calls == current.model_calls == 1
    with patch("tchekam.messaging.channel.get_channel") as channel:
        with pytest.raises(AgentDenied, match="call_limit"):
            transcribe_owned_audio(current)
        channel.assert_not_called()


def test_voice_turn_reaches_tools_and_reviewed_reply(make_run, fake_channel, fake_speech):
    run = make_run(kind="audio")
    fake_channel.media[run.inbound_key] = (wav(), "audio/wav")
    fake_speech.transcripts.append(Transcript("Check this message: send money now", "en", 0.9))
    ctx = claim(run.pk)
    ctx.model = fake_model()
    state = build_graph(ctx).invoke({"run_id": run.pk})
    assert state["completed"] and state["action"].kind == "results"
    assert ctx.transcript == "Check this message: send money now"
    assert ctx.model_calls == 0 and ctx.tool_calls == 1
    assert ctx.results["r1"].operation == "check_message"


@pytest.mark.parametrize("data", [b"not audio", wav(121)])
def test_unreadable_or_long_audio_is_denied_before_transcription(
    make_run, fake_channel, fake_speech, data
):
    run = make_run(kind="audio")
    fake_channel.media[run.inbound_key] = (data, "audio/wav")
    with pytest.raises(AgentDenied, match="audio_duration"):
        transcribe_owned_audio(claim(run.pk))
    assert fake_speech.calls == []
