"""Explicit metadata observations; never attach the stock content-capturing callback."""

import atexit
import base64
import threading
from time import monotonic
from urllib.parse import urlparse

from django.conf import settings

NODES = frozenset(
    {
        "claim_turn",
        "authorize_turn",
        "load_memory",
        "prepare_input",
        "transcribe_audio",
        "build_context",
        "before_agent",
        "agent",
        "validate_response_action",
        "render_response",
        "guard_out",
        "safe_fallback",
        "revalidate_turn",
        "persist_memory",
        "publish_delivery",
        "discard_turn",
        "model_call",
        "check_number",
        "check_message",
        "check_account_name",
        "check_photo",
        "read_image",
        "what_to_do_next",
        "explain_scam_pattern",
        "report_status",
        "start_report",
        "start_appeal",
        "set_language",
    }
)
OUTCOMES = frozenset({"ok", "denied", "fallback", "error", "stale", "clarification"})


class MetadataTracer:
    def __init__(self, client=None):
        self.client = client

    def observe(self, name, *, outcome="ok", latency_ms=0, model_calls=0, tool_calls=0):
        if self.client is None or name not in NODES or outcome not in OUTCOMES:
            return
        values = (latency_ms, model_calls, tool_calls)
        if any(type(v) is not int or v < 0 or v > 10**9 for v in values):
            return
        # Construct a fresh object from bounded enums/numbers. Do not sanitize arbitrary
        # callback dictionaries: they may contain content in names, events or resource attrs.
        try:
            span = self.client.start_observation(
                name=name,
                as_type="span",
                metadata={
                    "policy": "agent-v1",
                    "outcome": outcome,
                    "latency_ms": latency_ms,
                    "model_calls": model_calls,
                    "tool_calls": tool_calls,
                },
            )
            span.end()
        except Exception:
            self.client = None  # optional telemetry never changes execution or retries inference

    def flush(self):
        if self.client is None:
            return

        def attempt():
            try:
                self.client.flush()
            except Exception:
                pass

        thread = threading.Thread(target=attempt, daemon=True)
        thread.start()
        thread.join(timeout=1)

    def fork(self):
        return MetadataTracer(
            self.client.fork() if self.client and hasattr(self.client, "fork") else self.client
        )


_local = None
_lock = threading.Lock()


def local_synthetic_tracer():
    """Opt-in local synthetic trial only. Real-user tracing awaits deletion/hold gates."""
    global _local
    if not settings.AGENT_TRACE_SYNTHETIC:
        return MetadataTracer()
    with _lock:
        if _local is not None:
            return _local.fork()
        _local = MetadataTracer()
        parsed = urlparse(settings.LANGFUSE_BASE_URL)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("localhost", "127.0.0.1")
            or not settings.LANGFUSE_PUBLIC_KEY
            or not settings.LANGFUSE_SECRET_KEY
        ):
            return _local
        try:
            import httpx
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            # Use the supported OTLP/HTTP endpoint directly. The pinned Langfuse SDK
            # creates media workers and an unbounded atexit shutdown even for explicit
            # spans; no SDK client/callback is constructed on the conversation path.
            with httpx.Client(timeout=1, follow_redirects=False) as http:
                response = http.get(
                    settings.LANGFUSE_BASE_URL + "/api/public/projects",
                    auth=(settings.LANGFUSE_PUBLIC_KEY, settings.LANGFUSE_SECRET_KEY),
                )
                response.raise_for_status()
            credentials = base64.b64encode(
                f"{settings.LANGFUSE_PUBLIC_KEY}:{settings.LANGFUSE_SECRET_KEY}".encode()
            ).decode()
            provider = TracerProvider(
                resource=Resource({"service.name": "tchekam-agent-synthetic"}),
                shutdown_on_exit=False,
            )
            exporter = OTLPSpanExporter(
                endpoint=settings.LANGFUSE_BASE_URL + "/api/public/otel/v1/traces",
                timeout=1,
                headers={
                    "Authorization": "Basic " + credentials,
                    "x-langfuse-ingestion-version": "4",
                },
            )
            provider.add_span_processor(
                BatchSpanProcessor(
                    exporter,
                    max_queue_size=256,
                    max_export_batch_size=64,
                    schedule_delay_millis=1000,
                )
            )
            _local.client = OTelClient(provider)
            if _local.client:
                atexit.register(_local.flush)
        except Exception:
            pass
        return _local.fork()


class OTelClient:
    def __init__(self, provider, *, start_run=False):
        self.provider = provider
        self.tracer = provider.get_tracer("tchekam.agent", "1")
        self.root = self.tracer.start_span("agent_turn") if start_run else None

    def start_observation(self, *, name, as_type, metadata):
        from opentelemetry.trace import set_span_in_context

        return self.tracer.start_span(
            name,
            context=set_span_in_context(self.root) if self.root else None,
            attributes={
                "langfuse.observation.type": as_type,
                **{f"langfuse.observation.metadata.{k}": v for k, v in metadata.items()},
            },
        )

    def flush(self):
        if self.root:
            self.root.end()
            self.root = None
        self.provider.force_flush(timeout_millis=1000)

    def fork(self):
        return OTelClient(self.provider, start_run=True)


def timed_node(tracer, name, function, ctx):
    def invoke(state):
        started = monotonic()
        outcome = "error"
        try:
            result = function(state)
            outcome = result.get("outcome", "ok")
            if outcome not in OUTCOMES:
                outcome = "denied"
            return result
        finally:
            tracer.observe(
                name,
                outcome=outcome,
                latency_ms=int((monotonic() - started) * 1000),
                model_calls=ctx.model_calls,
                tool_calls=ctx.tool_calls,
            )

    return invoke
