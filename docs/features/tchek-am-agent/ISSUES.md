# Conversational agent implementation ledger

The implementation is disabled by default. The rows below distinguish shipped local
code from acceptance evidence still required by PLAN.md. No issue is represented as a
passing pilot or live-model release. Changes are currently uncommitted; issue-specific
branches/PRs have not been created or published.

Owner model decision, 24 November 2026: use `deepseek/deepseek-v4.1-flash-1017` for both
chat and image classification; keep the conversational agent; remove its separate fast
model role; omit MAI image generation. The UI mention was withdrawn. Model selection is
resolved. The owner subsequently authorized $1 for synthetic live tests and confirmed ZDR
on all AI models. Initial trials through `together/us` are archived in CAPABILITIES.md:
latest dialogue 33/33, images 3/3, conservative total $0.168546 including unknown-billing
reservations. Larger release evaluations and later rollout decisions remain.

Owner update, 25 November 2026 (ADR-026): all AI flows now use OpenRouter. Direct
Anthropic/Groq adapters, SDK dependency and keys are removed; SerpAPI is retained.
OpenRouter Whisper Large V3 implements report and agent transcription with supported
ZDR/data-policy routing, durable agent limits and shared budgets. STT endpoint lists
remain unsupported and are not claimed. New contracts are tested with mock HTTP;
the archived paid results above predate consolidation and do not establish STT quality.

See [READINESS.md](READINESS.md) for the current scope and actual operational
prerequisites. Model/ZDR/budget decisions are resolved. Manual `approved` and
`zdr_only_verified` booleans were removed; runtime authorization, privacy routing and
budgets remain enforced. The pasted-message routing correction and final results are
recorded in CAPABILITIES.md; older failed receipts remain archived.

| Issue | Plan | Implemented locally | Remaining acceptance |
|---|---|---|---|
| 26 | A0 | Dated matrix; pinned API/SDK contracts; STT routing limitations documented; owner-confirmed ZDR; DeepSeek/Together live dialogue and screenshot trials within $1; original failures and cost ledger archived; pasted-message routing fixed | Broader held-out role-quality and live STT evidence. |
| 27 | A1 | ADR-023/024/025; strict action/runtime contracts; pinned dependencies/CLI; fake-only Studio export; settings inventory; import-boundary scan | Issue-specific PR and review of proposed catalogs/configuration. |
| 28 | A2 | Scoped chat/structured adapter; nested endpoint policy; explicit timeouts/no SDK retry; persistent counters; shared locked reservation ledger; conservative settlement; live usage/pricing; provider/request metadata; served-model rejection in chat and vision | Wider outage/price-change contract coverage. Exact endpoint selection is enforced by request; returned provider display metadata is not an exact endpoint identity. |
| 29 | A3 | Pinned localhost Compose; real local health and OTLP ingestion/readback; explicit metadata spans; HTTP canary/outage/bounded-flush tests | Optional production tracing: selective trace erasure/hold and TTL cleanup, broader exporter matrix and hosting. Production tracing stays off and does not block core execution. |
| 30 | A4 | Strict registry; deterministic verdict parity; masked names; owned-message flags; internal transient photo check; typed vision; reviewed advice/status; staged report/appeal/language actions; run-scoped result handles | Native copy review; broader parameter/adversarial coverage. Automatic evidence adoption and external uploads stay outside the implemented scope; existing collection/consent flows remain usable. |
| 31 | A5 | Complete outer graph and real create_agent loop; mandatory repeated enforcement; memory/fallback/stale completion; actual graph exports and executable fake-only Studio graph | Full multilingual/adversarial trajectories and all configured live models; expanded failure/performance coverage. |
| 32 | A6 | Django migrations; FIFO/generation/leases/fencing; durable outbox/reconciler; router matrix; HMAC memory/aliases; shortcut references; runtime cohort/kill switch; retention/hold/erasure/AI-log aggregation | Large-scale multi-worker/load evidence; review retention defaults; full crash-window matrix. |
| 33 | A7 | Image ownership/decoding; internal lookup; typed observations/confirmation; DeepSeek live screenshot smoke 3/3; OpenRouter STT for reports and agent; owned audio/duration checks; durable STT/model counts, reservations and recovery tests | Real-world image/audio evaluation, including FR/EN/PCM transcription accuracy. STT uses supported ZDR routing under ADR-026 instead of unsupported endpoint lists. |
| 34 | A8 | Network-free application/provider/telemetry tests, concurrency regressions, expanded multilingual synthetic runner and limited smoke receipts | Full specified held-out datasets, Promptfoo campaigns, live adversarial results, role quality, real media and queue/load metrics. |
| 35 | A9 | Runtime admin cohort/rollout/role switch, guarded workers/delivery, operational runbook and rollback instructions | Staff/partner cohort decision, processor/legal review, alerts/load gates and explicit pilot approval. No production deployment performed. |

Conservative implementation choices: terminal metadata keeps **32 days** to cover the
reconciliation window; rendered delivery text is cleared after **7 days**. Agent photo
lookups are transient, so ordinary private chat images are not silently adopted as shared
catalog sightings. External search and agent-conversation training reuse are not enabled.
Existing deterministic integrations remain configured independently.
