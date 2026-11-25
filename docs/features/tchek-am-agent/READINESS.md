# Agent readiness — 25 November 2026

The text/image/audio conversational implementation can run locally. Model selection, UI
scope, account ZDR and the initial synthetic-test budget are resolved. There is no
remaining owner decision blocking another local synthetic run within that budget.
Production traffic has not been enabled or deployed. The original A0–A9 plan includes
more release evidence and optional capabilities than this implemented scope.

## Finished code corrections

- ADR-026 consolidates every AI flow on OpenRouter, removes direct Anthropic/Groq
  adapters and keys, and retains SerpAPI. Report extraction, group classification
  and message flags use the same DeepSeek model. OpenRouter Whisper Large V3 handles
  report and agent transcription. Agent voice has audio-container duration/byte bounds,
  persistent STT/model limits, shared reservations, content-free audit and recovery
  fencing. STT enforces documented ZDR/data-policy routing; endpoint allow-lists are
  unsupported there. Contract tests pass; real STT accuracy is not yet measured.

- Explicit requests to check pasted/forwarded text use the authorized `check_message`
  tool directly. A colon, quotation mark or newline separates the request from its
  untrusted payload. This prevents quoted instructions from changing the task and
  avoids an unnecessary paid planning call. Combined/ambiguous requests retain the
  conversational planner. FR/EN/PCM injection and negative cases have regressions.
- The planner distinguishes missing message text from supplied text and direct
  instructions to guarantee payment safety. User-facing replies remain code-owned.
- Missing `last_number` references ask for a number without another model call.
- Chat and vision retain provider request ids and returned provider metadata. The
  pinned SDK drops the optional provider field, so the owned HTTP client captures
  that bounded field only. A provider display name is not an exact endpoint slug.
- Structured vision rejects a response served by a model outside its configured list.
- Redundant `approved` / `zdr_only_verified` configuration switches are removed.
  ZDR, endpoint restrictions, ownership, consent and spending enforcement remain.
- Evaluation now checks that the requested tool's result was returned, not merely
  called. Receipts hash new source files as well as the tracked worktree diff.

## Actual prerequisites for production activation

| Prerequisite | Current state |
|---|---|
| Apply checked-in migrations to the deployment database | Tested in isolated databases; no deployment database migrated here. |
| Run a dedicated `agent` worker and existing delivery/reconciliation workers | Worker configuration and runbook supplied; no production worker created. |
| Configure role endpoints, API key, separate memory/operation HMAC keys | Tested configuration supplied in `.env.example`; production secrets stay external. |
| Set finite positive daily/monthly production budgets | Defaults remain zero. The owner authorized $1 for synthetic tests only. |
| Enable environment/runtime switches and choose recipients | Defaults remain off; explicit cohort/percentage control exists. |
| Complete broader held-out, native-copy, real-image and multi-worker evaluation | Small development smoke and network-free regressions exist; full A8 is incomplete. |
| Review the production processor/notice inventory for actual data flows | No real-user OpenRouter traffic or external tracing introduced by this work. |

The first five rows are operational configuration, not unresolved implementation
decisions or extra approval booleans. Existing user consent, blocked-user handling,
scoped resources, kill switches, quotas and result provenance are runtime controls.

## Optional capabilities that stay off

| Capability | Reason / consequence |
|---|---|
| Production Langfuse tracing | Only local synthetic metadata traces are implemented. Selective external trace deletion/hold/TTL work and hosting are needed before enabling real-user tracing. Local database audit/retention already operate without it. |
| External reverse-image uploads | Agent lookup is internal and transient. No external-upload authorization or SerpAPI call is inferred from receiving a photo. |
| Automatic report evidence adoption | Handoffs enter the existing consent/collection flow. The agent does not copy extracted fields into evidence or submit a report. |
| Fast classifier / MAI generation / new UI | Removed from scope by the owner's decisions. |

Issue branches/PRs have not been published. See [ISSUES.md](ISSUES.md) for the original
plan's remaining acceptance work and [CAPABILITIES.md](CAPABILITIES.md) for measured
results, archived failures and conservative accounting against the original $1.
