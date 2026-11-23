import json
import math

import httpx
import pytest

from tchekam.ai.models import AICallLog
from tchekam.speech.base import Transcript, get_speech_to_text
from tchekam.speech.fake import FakeSpeechToText
from tchekam.speech.groq import GroqWhisper

pytestmark = pytest.mark.django_db

EMPTY = Transcript(text="", language="", confidence=0.0)
VERBOSE = {
    "text": "  Bonjour, le vendeur est au 677123456  ",
    "language": "french",
    "segments": [{"avg_logprob": -0.1}, {"avg_logprob": -0.3}],
}


def make(handler, **kwargs) -> GroqWhisper:
    return GroqWhisper(api_key="gk", transport=httpx.MockTransport(handler), **kwargs)


def ok_handler(captured: list):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=VERBOSE)

    return handler


def multipart_fields(request: httpx.Request) -> dict[str, str]:
    """Text fields of the multipart body, plus the file part's disposition line."""
    body = request.content.decode("latin-1")
    fields = {}
    for part in body.split(f"--{_boundary(request)}"):
        if 'name="' not in part:
            continue
        head, _, value = part.partition("\r\n\r\n")
        name = head.split('name="')[1].split('"')[0]
        fields[name] = head if name == "file" else value.strip()
    return fields


def _boundary(request: httpx.Request) -> str:
    return request.headers["content-type"].split("boundary=")[1]


def test_request_shape_and_parsing():
    seen: list[httpx.Request] = []
    result = make(ok_handler(seen)).transcribe(b"audio-bytes", "audio/ogg")

    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer gk"
    fields = multipart_fields(request)
    assert fields["model"] == "whisper-large-v3"
    assert fields["response_format"] == "verbose_json"
    assert fields["temperature"] == "0"
    assert 'filename="audio.ogg"' in fields["file"]
    assert "language" not in fields
    assert b"audio-bytes" in request.content
    assert result.text == "Bonjour, le vendeur est au 677123456"
    assert result.language == "french"
    assert result.confidence == pytest.approx((math.exp(-0.1) + math.exp(-0.3)) / 2)


@pytest.mark.parametrize(
    ("mimetype", "ext"),
    [
        ("audio/ogg", "ogg"),
        ("audio/ogg; codecs=opus", "ogg"),
        ("audio/opus", "ogg"),
        ("audio/mpeg", "mp3"),
        ("audio/mp4", "m4a"),
        ("audio/x-m4a", "m4a"),
        ("audio/wav", "wav"),
        ("audio/webm;codecs=opus", "webm"),
        ("application/weird", "ogg"),
    ],
)
def test_filename_extension_from_mimetype(mimetype, ext):
    seen: list[httpx.Request] = []
    make(ok_handler(seen)).transcribe(b"x", mimetype)

    assert f'filename="audio.{ext}"' in multipart_fields(seen[0])["file"]


@pytest.mark.parametrize(
    ("hint", "sent"),
    [("fr", "fr"), ("en", "en"), ("pcm", "en"), ("de", None), (None, None)],
)
def test_language_hint(hint, sent):
    seen: list[httpx.Request] = []
    make(ok_handler(seen)).transcribe(b"x", "audio/ogg", hint)

    assert multipart_fields(seen[0]).get("language") == sent


def test_confidence_defaults_without_segments_and_is_clamped():
    def handler(request):
        return httpx.Response(200, json={"text": "hi", "language": "en"})

    assert make(handler).transcribe(b"x", "audio/ogg").confidence == 0.5

    def empty(request):
        return httpx.Response(200, json={"text": " ", "language": "en"})

    assert make(empty).transcribe(b"x", "audio/ogg").confidence == 0.0

    def high(request):
        return httpx.Response(200, json={"text": "hi", "segments": [{"avg_logprob": 0.5}]})

    assert make(high).transcribe(b"x", "audio/ogg").confidence == 1.0


def timeout(request):
    raise httpx.ReadTimeout("slow", request=request)


def connect_error(request):
    raise httpx.ConnectError("down", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        timeout,
        connect_error,
        lambda r: httpx.Response(429, json={"error": "rate"}),
        lambda r: httpx.Response(500, text="boom"),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: httpx.Response(200, json={"nope": 1}),
        lambda r: httpx.Response(200, json=["x"]),
        lambda r: httpx.Response(200, json={"text": "a", "segments": [{"x": 1}]}),
    ],
)
def test_failures_return_an_empty_transcript(handler):
    assert make(handler).transcribe(b"x", "audio/ogg") == EMPTY


def test_oversize_and_empty_audio_are_not_sent():
    seen: list[httpx.Request] = []
    stt = make(ok_handler(seen))

    assert stt.transcribe(b"", "audio/ogg") == EMPTY
    assert stt.transcribe(b"0" * (25 * 1024 * 1024 + 1), "audio/ogg") == EMPTY
    assert seen == []
    assert AICallLog.objects.count() == 0


def test_success_is_logged_without_content():
    make(ok_handler([])).transcribe(b"x", "audio/ogg")

    (row,) = AICallLog.objects.all()
    assert (row.purpose, row.model, row.prompt_version) == ("stt", "whisper-large-v3", "")
    assert row.success is True
    assert row.error == ""
    assert row.tokens_in == row.tokens_out == 0
    assert row.latency_ms >= 0
    assert "Bonjour" not in json.dumps(list(AICallLog.objects.values()), default=str)


@pytest.mark.parametrize(
    ("handler", "error"),
    [
        (timeout, "ReadTimeout"),
        (lambda r: httpx.Response(429, text="secret body"), "HTTPStatusError:429"),
        (lambda r: httpx.Response(200, text="secret"), "JSONDecodeError"),
    ],
)
def test_failure_is_logged_without_content(handler, error):
    make(handler).transcribe(b"x", "audio/ogg")

    (row,) = AICallLog.objects.all()
    assert row.purpose == "stt"
    assert row.success is False
    assert row.error == error
    assert "secret" not in json.dumps(list(AICallLog.objects.values()), default=str)


def test_fake_returns_canned_transcripts_in_order(fake_speech):
    first = Transcript("un", "fr", 0.9)
    fake_speech.transcripts.extend([first, Transcript("deux", "fr", 0.8)])

    assert fake_speech.transcribe(b"a", "audio/ogg", "fr") == first
    assert fake_speech.transcribe(b"b", "audio/ogg").text == "deux"
    assert fake_speech.transcribe(b"c", "audio/ogg") == EMPTY
    assert [c["audio"] for c in fake_speech.calls] == [b"a", b"b", b"c"]


def test_factory_selects_by_setting(settings, fake_speech):
    settings.SPEECH_BACKEND = "fake"
    assert get_speech_to_text() is FakeSpeechToText.instance()
    settings.SPEECH_BACKEND = "groq"
    assert isinstance(get_speech_to_text(), GroqWhisper)
    settings.SPEECH_BACKEND = "nope"
    with pytest.raises(ValueError):
        get_speech_to_text()


def _file_part_content_type(request: httpx.Request) -> str:
    head = multipart_fields(request)["file"]
    return head.split("Content-Type: ")[1].split("\r\n")[0].strip()


@pytest.mark.parametrize(
    ("mimetype", "expected"),
    [
        ("", "audio/ogg"),
        ("AUDIO/OGG; codecs=opus", "audio/ogg"),
        ("audio/opus", "audio/ogg"),
        ("audio/x-m4a", "audio/mp4"),
        ("audio/ogg\r\n\r\nINJECT\r\n--x", "audio/ogg"),
    ],
)
def test_file_part_content_type_is_canonical(mimetype, expected):
    seen: list[httpx.Request] = []
    make(ok_handler(seen)).transcribe(b"x", mimetype)

    assert _file_part_content_type(seen[0]) == expected
    assert b"INJECT" not in seen[0].content


def test_absurd_or_nonfinite_logprobs_do_not_break_parsing():
    def big(request):
        return httpx.Response(200, text='{"text": "hi", "segments": [{"avg_logprob": 1000}]}')

    result = make(big).transcribe(b"x", "audio/ogg")
    assert (result.text, result.confidence) == ("hi", 1.0)

    def nan(request):
        return httpx.Response(200, text='{"text": "hi", "segments": [{"avg_logprob": NaN}]}')

    result = make(nan).transcribe(b"x", "audio/ogg")
    assert (result.text, result.confidence) == ("hi", 0.0)


def test_size_limit_is_inclusive():
    from tchekam.speech.groq import MAX_AUDIO_BYTES

    seen: list[httpx.Request] = []
    stt = make(ok_handler(seen))

    assert stt.transcribe(b"0" * MAX_AUDIO_BYTES, "audio/ogg").text
    assert len(seen) == 1
    assert stt.transcribe(b"0" * (MAX_AUDIO_BYTES + 1), "audio/ogg") == EMPTY
    assert len(seen) == 1


def test_logs_contain_only_class_and_status(caplog):
    caplog.set_level("DEBUG")
    make(lambda r: httpx.Response(429, text="secret body")).transcribe(b"x", "audio/ogg")
    make(connect_error).transcribe(b"x", "audio/ogg")

    # httpx's own INFO request line carries the URL; only our logger is under test here.
    records = [r for r in caplog.records if r.name.startswith("tchekam")]
    assert records
    text = "\n".join(r.getMessage() for r in records)
    assert "429" in text
    assert "ConnectError" in text
    for leaked in ("secret", "api.groq.com", "Bearer", "gk"):
        assert leaked not in text


def test_call_log_failure_never_raises(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("tchekam.speech.groq.record_call", boom)

    assert make(ok_handler([])).transcribe(b"x", "audio/ogg").text


@pytest.mark.parametrize("mimetype", [None, 123, b"audio/ogg"])
def test_non_string_mimetype_does_not_raise(mimetype):
    seen: list[httpx.Request] = []
    result = make(ok_handler(seen)).transcribe(b"x", mimetype)

    assert result.text
    assert _file_part_content_type(seen[0]) == "audio/ogg"
