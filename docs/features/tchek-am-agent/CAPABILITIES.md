# Capability and privacy evidence — 24 November 2026

The owner authorized **$1** for an initial synthetic live test and confirmed ZDR is
enabled on all AI models. DeepSeek chat and image-classification trials have now run
through `together/us`, with strict request-level privacy routing retained. Production
rollout remains disabled. These small, repeated development cases are smoke evidence,
not a complete held-out release evaluation.

| Role | Candidates/direction | Current selection | Evidence / remaining work |
|---|---|---|---|
| Chat | Owner selected `deepseek/deepseek-v4.1-flash-1017` | Synthetic live test via `together/us`; latest full run 33/33 | Pasted-message routing corrected with an authorized deterministic shortcut; broader held-out/language evidence remains open. |
| Separate fast model | Removed from the agent | Not required | The chat model chooses tools; deterministic message rules remain available. Existing legacy AI_MODEL_FAST integrations are separate. |
| Vision | Owner selected `deepseek/deepseek-v4.1-flash-1017` | Synthetic live test via `together/us`; latest full run 3/3 | Three generated screenshots cover FR/EN/PCM, phone/amount extraction and an embedded instruction. They do not establish real-world screenshot accuracy. |
| MAI image generation | `microsoft/mai-image-2.7-flash` | Omitted by owner decision | Its image-only output does not meet the classifier's text-output contract. Image generation is outside this feature. |
| STT | Owner-preferred OpenRouter endpoint; existing Groq remains separately configured for reports | Disabled for agent | Current STT docs explicitly say endpoint `only`, `order`, `ignore` restrictions are ignored. Equivalent approved-endpoint restrictions cannot be enforced by this adapter. |
| Photo reuse | Existing pHash/internal database path; existing SerpAPI pathway is separate | Internal-only in agent | Owned media does not authorize an external upload. Agent tools never schedule SerpAPI. No new shared-catalog copies are made by transient agent lookups. |

Sources checked: [OpenRouter STT parameters](https://openrouter.ai/docs/guides/overview/multimodal/stt#request-parameters),
[OpenRouter ZDR and Safety Retention](https://openrouter.ai/docs/guides/features/zdr),
[ChatOpenRouter integration](https://docs.langchain.com/oss/python/integrations/chat/openrouter),
[supported Langfuse OTLP ingestion](https://langfuse.com/docs/api-and-data-platform/features/public-api).
Model inventory checked on 24 November 2026 using the public, non-billable endpoints:
[DeepSeek](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4.1-flash-1017/endpoints)
and [MAI](https://openrouter.ai/api/v1/models/microsoft/mai-image-2.7-flash/endpoints).
Owner confirmed DeepSeek for both chat and image classification, no separate fast model,
and no MAI image generation. The conversational agent remains in scope. The UI mention
was withdrawn; no new UI implementation is requested.
The authenticated, non-billable ZDR endpoint preview returned 43 DeepSeek endpoints on
24 November 2026. This provides candidates for serving-endpoint selection, not proof of
the account's ZDR-only/Safety Retention settings. The configured API key is available;
its key-info response does not expose those privacy settings. The owner subsequently
confirmed ZDR is enabled; that confirmation and the $1 authorization are recorded with
the synthetic experiment, rather than presented as an independently fetched account audit.
The dedicated STT adapter deliberately returns an empty `Transcript` before downloading
or sending audio, even with credentials. Copying chat routing preferences into STT would
silently weaken the endpoint policy.

Pinned installed contracts: LangChain **1.5.2**, LangGraph **1.2.24**,
langchain-openrouter **0.3.0**, Langfuse SDK **3.15.0** (not attached as a callback),
LangGraph CLI **0.4.43**, Langfuse server/worker **4.84.0**. `uv.lock` pins transitive
versions. The pinned ChatOpenRouter source serializes `openrouter_provider` to nested
`provider`; its `request_timeout` is milliseconds. Mocked HTTP tests exercise the actual
SDK serialization and prove transport retries are disabled with `retry_config=None`.

Template source reviewed in `.scratch/agent-template/graph.py` at
`langchain-ai/new-langgraph-project@f94c71327f6bb8b1759ddc7221d0ceb682dc440a`.
It is a fixed-response one-node scaffold. The implemented graph and exported inner
middleware/tool loop are in `graphs/outer.mmd` and `graphs/inner.mmd`.
Local Compose was derived from
`langfuse/langfuse@0eaa455d26f004bffa82dcc3807b861445df119f` with isolated credentials,
localhost-only exposure and pinned images, including a MinIO digest.

Initial smoke gates, defined before any paid ranking: task success at least **90%**,
**zero** safety/privacy/authorization violations, processing p95 at most **60 seconds**,
mean conservatively reserved cost at most **$0.05** per synthetic turn. The 24-case smoke
dataset has 8 inputs per language. It does not substitute for the larger core,
adversarial, image, speech or performance datasets required by EVAL_SUITE.md.

Measured local evidence: the fake-only full graph ran through the local LangGraph API;
Langfuse 4.84.0 health returned OK; a synthetic tool-loop trace was accepted and returned
by `/api/public/v2/observations` with HTTP 200 and **zero paid calls**. The local receipt
is `.scratch/agent-langfuse-smoke.json`; it is synthetic-only, not production approval.
Exporter tests decode actual OTLP HTTP payloads and reject content canaries. The direct
OTLP adapter avoids the pinned Langfuse SDK's automatic media workers and unbounded
shutdown handler. Production tracing, full release quality and account/key privacy
verification remain incomplete.

## Initial $1 synthetic live experiment

[Archived summary and every trial receipt](../../../evals/agent/results/2026-11-24-initial/summary.json).
Earlier failures are retained alongside the final runs; repetitions are not counted as
new independent cases. All actors, screenshots, reports and messaging were synthetic,
and the temporary evaluation databases were removed after each run.

| Latest complete collection | Result | Processing p95, nearest rank | Returned charges for that run |
|---|---|---|---|
| Dialogue: 11 cases each FR/EN/PCM | **33/33** | **4.51 seconds** | **$0.003310** |
| Screenshots: FR phone, EN amount, PCM phone+amount with injected instruction | **3/3** | **8.78 seconds** | **$0.001828** |

The earlier `fr-quoted-injection` failure is fixed. Explicit supplied-message requests
now execute the authorized rules-only message-check tool without paid planning. New
cases cover newline/quoted payloads, requests without message text and direct hostile
instructions in all three languages. The latest 33-case collection passes the stricter
check that the requested tool's result is actually returned. The last nine cases are
development regressions, not independent held-out evidence. A fixture encoding error
in an earlier new French case was corrected before the final complete run.

The experiment exposed and corrected SDK transport cleanup that had masked settlement
and audit outcomes. Subsequent changes added explicit tool receipts, short run-scoped
result aliases, deterministic temperature, low chat reasoning, disabled classifier
reasoning, token-usage recording and code-owned clarification for absent number aliases.
The registry rejects an old alias until the current run has its own authorized result.
Chat/vision also retain provider response ids and returned provider display metadata;
vision rejects an unexpected served model. Redundant manual approval/ZDR-attestation
booleans were removed without weakening request-level privacy restrictions. Receipts
include a source digest covering new files, and refuse to overwrite existing receipts.

Across **all 17 trials**, known returned charges rounded up per call total **$0.078546**.
The first three calls lost settlement/audit during the cleanup bug; their full **$0.09**
reservation remains conservatively held rather than treated as free. Total accounted:
**$0.168546 of $1**, leaving **$0.831454** of the authorized ceiling unused. No further
paid testing is scheduled. This accounting is a conservative experiment ledger, not an
independently reconciled provider invoice.

Network-free full regression: **1,793 passed**, 7 optional integrations skipped, one
slow test deselected and one existing Sentry deprecation warning. After the intake
shortcut, the complete agent suite was rerun: **81 passed** (including its 15 new
intake cases). Lint, formatting and migration consistency checks pass. The larger
held-out, real-media, native-language and deployment acceptance work remains separate;
see [READINESS.md](READINESS.md) for actual prerequisites and optional capabilities.
