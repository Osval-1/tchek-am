from time import monotonic

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from requests import Response, Session

from tchekam.ai.agent.tracing import MetadataTracer, OTelClient


class CaptureSession(Session):
    def __init__(self):
        super().__init__()
        self.sent = []

    def request(self, method, url, data=None, **kwargs):
        self.sent.append((url, data))
        response = Response()
        response.status_code = 200
        response._content = b""
        return response


def test_real_otlp_http_export_contains_only_constructed_metadata():
    session = CaptureSession()
    exporter = OTLPSpanExporter(
        endpoint="http://localhost:3100/api/public/otel/v1/traces", session=session, timeout=1
    )
    provider = TracerProvider(
        resource=Resource({"service.name": "synthetic"}), shutdown_on_exit=False
    )
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = MetadataTracer(OTelClient(provider))
    canary = "SECRET phone 677123456 https://private/audio?token=SECRET"
    tracer.observe("agent", outcome="ok", model_calls=1)
    tracer.observe(canary, outcome="ok")
    tracer.observe("agent", outcome=canary)
    tracer.observe("agent", latency_ms=canary)
    assert len(session.sent) == 1
    url, wire = session.sent[0]
    assert url.endswith("/api/public/otel/v1/traces")
    assert b"SECRET" not in wire and b"677123456" not in wire and b"private" not in wire
    request = ExportTraceServiceRequest.FromString(wire)
    spans = [
        span
        for resource in request.resource_spans
        for scope in resource.scope_spans
        for span in scope.spans
    ]
    assert [span.name for span in spans] == ["agent"]
    assert all(not span.events and not span.links for span in spans)
    assert "langfuse.observation.metadata.model_calls" in {a.key for a in spans[0].attributes}
    provider.shutdown()


def test_exporter_failure_does_not_escape():
    class Broken:
        def start_observation(self, **kwargs):
            raise RuntimeError("SECRET")

    tracer = MetadataTracer(Broken())
    tracer.observe("agent")
    assert tracer.client is None


def test_flush_is_bounded():
    import threading

    release = threading.Event()

    class Stuck:
        def flush(self):
            release.wait(timeout=5)

    started = monotonic()
    MetadataTracer(Stuck()).flush()
    release.set()
    assert monotonic() - started < 1.5
