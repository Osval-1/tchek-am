"""Only this module constructs LangChain/OpenRouter inference clients."""

import httpx
from django.conf import settings
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_openrouter import ChatOpenRouter
from openrouter import OpenRouter
from pydantic import PrivateAttr

from .policy import remaining, role_policy


class OpenRouterChatModel(ChatOpenRouter):
    _owned_http_client: httpx.Client | None = PrivateAttr(default=None)
    _provider_metadata: dict = PrivateAttr(default_factory=dict)

    def close_owned_transport(self):
        if self._owned_http_client is not None:
            self._owned_http_client.close()
            self._owned_http_client = None
            self.client.__exit__(None, None, None)


def close_model(model):
    try:
        if isinstance(model, OpenRouterChatModel):
            model.close_owned_transport()
    except Exception:
        # Transport cleanup must not mask the inference outcome or prevent spend settlement.
        pass


def close_resources(ctx):
    while ctx.model_resources:
        close_model(ctx.model_resources.pop())


class FakeChatModel(FakeMessagesListChatModel):
    """Scripted messages exercise the real create_agent loop, never a network."""

    def bind_tools(self, tools, **kwargs):
        return self


def fake_model(responses=None):
    return FakeChatModel(
        responses=responses or [AIMessage(content='{"kind":"clarify","catalog":"number"}')]
    )


def chat_model(ctx, role="chat", *, transport=None):
    policy = role_policy(role)
    timeout = remaining(ctx)
    provider_metadata = {}

    def capture_provider(response):
        # The pinned SDK drops the optional top-level provider field. Capture only
        # this bounded metadata from non-streaming responses, never log the body.
        try:
            response.read()
            provider = response.json().get("provider")
            if isinstance(provider, str):
                provider_metadata["provider"] = provider[:100]
        except (ValueError, AttributeError):
            pass

    # The pinned SDK defaults to retries when retry_config is unset: explicitly pass None.
    http_client = httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(timeout, connect=min(5, timeout)),
        follow_redirects=False,
        event_hooks={"response": [capture_provider]},
    )
    client = OpenRouter(
        api_key=settings.OPENROUTER_API_KEY,
        retry_config=None,
        timeout_ms=int(timeout * 1000),
        client=http_client,
    )
    model = OpenRouterChatModel(
        model=policy["models"][0],
        openrouter_api_key=settings.OPENROUTER_API_KEY,
        client=client,
        max_retries=0,
        request_timeout=int(timeout * 1000),
        max_tokens=settings.AGENT_MAX_OUTPUT_TOKENS,
        streaming=False,
        temperature=policy.get("temperature", 0),
        reasoning=policy.get("reasoning"),
        openrouter_provider={
            "only": list(policy["endpoints"]),
            "data_collection": "deny",
            "zdr": True,
            "require_parameters": True,
            "allow_fallbacks": False,
        },
        plugins=[],
    )
    model._owned_http_client = http_client
    model._provider_metadata = provider_metadata
    ctx.model_resources.append(model)
    return model
