# Tchek-Am: Architecture (DRAFT v0.1)

*Companion to [prd.md](prd.md). Status: proposal for discussion.*

## 1. Guiding principles

1. **Modular monolith first.** One deployable service plus one background worker. A solo or small team ships faster this way, and the module boundaries let us split things out later.
2. **Postgres is the system of record for everything,** including vectors (pgvector). There is no separate vector database until we have more than about 5M images.
3. **The webhook must be fast; everything else runs async.** WhatsApp retries webhooks that don't get a 200 quickly, so the endpoint verifies, stores and enqueues, then returns. All AI and media work runs in workers.
4. **AI suggests, humans decide.** AI output is stored as *suggestions* next to what the moderator confirmed. Nothing AI-only reaches a public answer about a seller (PRD R1).
5. **Privacy by design.** PII is kept in separate, access-controlled tables and buckets, evidence is encrypted at rest, and every access to evidence is audit-logged.

## 2. Recommended stack

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.13+** | The ML work (CLIP, pHash, OCR) lives in Python. One language across the whole stack. |
| Web framework | **Django 5.x** (+ Django Ninja for JSON endpoints) | **Django admin gives us most of the moderation dashboard (F5) for free.** It also brings auth, migrations and audit-friendly models. |
| DB | **PostgreSQL 16 + pgvector** | Relational data, vectors, full-text search and the job queue in one place |
| Queue / worker | **Procrastinate** (Postgres-backed) or Celery + Redis | Procrastinate means one less piece of infrastructure. Switch to Celery if throughput needs it. |
| Object storage | S3-compatible (Cloudflare R2 / Backblaze B2 / MinIO locally) | Evidence and product images, with server-side encryption |
| LLM / vision | **Claude** (Haiku 5.5 for message classification and routing, Sonnet 5.5 for screenshot extraction and summaries) | Strong multilingual French/English, handles Pidgin well, and vision does OCR and extraction in one call, so there is no separate OCR pipeline in the MVP |
| Speech-to-text (voice notes) | **Groq `whisper-large-v3`** (decided 23 Nov 2026), behind a `SpeechToText` adapter. Claude doesn't take audio input. | Cheap and fast. Pidgin accuracy is expected to be weak, which is acceptable because the user confirms the extracted fields and the moderator can play the audio. **Longer term:** build our own labelled corpus from voice notes paired with the user-corrected fields (opt-in consent only) and fine-tune a model for Pidgin and Camfranglais. WhatsApp voice notes arrive as OGG/Opus. |
| Image similarity | `imagehash` (pHash/dHash) + **open_clip** ViT-B/32 or SigLIP embeddings (CPU is fine at MVP volume) | pHash catches near-identical copies; embeddings catch crops, edits and the same product shot differently |
| Phone numbers | `phonenumbers` (libphonenumber) + our own CM prefix-to-operator table | Normalise every number to E.164 |
| WhatsApp | **WaSender** (unofficial, WhatsApp Web-style session) for the pilot, behind a `MessagingChannel` interface. A `MetaCloudApiChannel` implementation comes later. | No company or verification needed, and it can join groups. It can be banned without warning, so the adapter, backup number and switch-over rule are required (PRD §7). Text-only menus. |
| Local dev | `uv`, Docker Compose (Postgres+pgvector, MinIO), ngrok / Cloudflare Tunnel for the webhook | |
| Hosting | **Render, Frankfurt region** (decided 23 Nov 2026): web service + background worker + managed Postgres with pgvector. **Cloudflare R2** (EU jurisdiction) for object storage. Sentry for errors. | Almost no server work for a solo founder. Plain Docker + Postgres keeps us portable to a VPS or in-country hosting later. |

*Alternative considered:* a TypeScript stack (NestJS/Hono + Next.js). That gives a nicer custom dashboard, but the ML would need a Python sidecar and there's no free admin. Not recommended for the MVP.

## 3. System overview

```
 WhatsApp user
      │
      ▼
 WaSender (gateway)──webhook──► ┌───────────────────────────── Django app ─────────────────────────────┐
      ▲                       │  /webhooks/whatsapp  (verify signature → store raw event → enqueue)   │
      │                       │  /admin              (moderation dashboard: Django admin + views)      │
      │ send messages         │  /s/<seller>         (Phase 2: public seller profile / badge page)     │
      │                       │  /api/v1             (Phase 3: B2B check API)                          │
      │                       └───────────────┬───────────────────────────────────────────────────────┘
      │                                       │ jobs (Postgres queue)
      │                       ┌───────────────▼──────────────── Worker(s) ───────────────────────────┐
      └───────────────────────┤  conversation engine · media download · image hashing/embedding     │
                              │  LLM extraction & classification · linking/clustering · notifications │
                              └───────┬───────────────────────┬──────────────────────┬───────────────┘
                                      ▼                       ▼                      ▼
                              PostgreSQL + pgvector     Object storage (R2)     Claude API
```

## 4. Modules (Django apps)

| App | Responsibility |
|---|---|
| `messaging` | The `MessagingChannel` interface (`send_text`, `send_image`, `download_media`, `parse_inbound`) and the `WaSenderChannel` implementation. Webhook authentication (shared secret/signature per WaSender docs), idempotent `InboundEvent` storage, outbound rate limiter with typing delays, and failover to the backup number. **No other module imports WaSender code.** |
| `groups` | F8 group listening: partner-group registry (admin, consent date, status), group-message intake, image → `imaging` pipeline, poster opt-out |
| `conversations` | Per-user session state machine: language, current flow (check / report / appeal), step and partial data, 24 h window tracking. Input routing (number? image? text?). |
| `identifiers` | Canonical entities: `PhoneNumber`, `AccountName` (MoMo/OM holder name, normalised), `Image`. Normalisation and operator lookup. |
| `checks` | F1–F3 logic. Builds the response from approved data only. Logs every check (a demand signal and a priority input). |
| `reports` | Report, Evidence, ExtractedField (AI vs confirmed), ReportLink. The report flow's business logic. |
| `ai` | Prompt templates, Claude client, structured-output schemas, the cost/latency log and evaluation fixtures. Every AI call goes through this module. |
| `speech` | Voice-note download, transcription through a provider adapter, transcript stored on the Evidence row |
| `imaging` | pHash + embedding computation, the near-duplicate search, an optional external reverse-search adapter |
| `moderation` | Queues, decisions, appeals, audit log, moderator roles |
| `reputation` | Status-band computation (R1, R2, R3, R8). Pure functions that are easy to test and explain. |
| `sellers` (Phase 2) | Verification, badges, subscriptions, public profile |

## 5. Core data model (MVP)

```
User (wa_id, language, trust_weight, created_at, blocked)        ← PII table
Conversation (user, flow, step, state_json, window_expires_at)

PhoneNumber (e164, operator, first_seen, check_count)
AccountName (normalised, display_masked, provider: momo|om)
Image (sha256, phash, embedding vector(512), first_seen, source: submission|group|catalogue)
PartnerGroup (wa_group_id, name, admin→User, consent_at, status)
ImageSighting (image, phone_number?, user?, group?, seen_at, context: submission|group)     ← "photo used by N numbers"

Report (reporter→User, status: draft|pending|needs_info|approved|rejected|merged,
        summary_ai, summary_final, amount_xaf, incident_date, evidence_score, created_at)
Evidence (report, object_key, kind: chat|momo_sms|post|voice|other, transcript?, tamper_flags_json)  ← encrypted
ReportSubject (report, phone_number | account_name | image, role: seller|payee|product, source: ai|user|moderator)
ReportLink (report_a, report_b, reason: same_number|same_name|same_image|similar_text, score)

ModerationDecision (report, moderator, action, reason, created_at)
Appeal (phone_number, appellant→User, statement, status, decision)
AuditLog (actor, action, object, at, ip)                            ← append-only
CheckLog (user, kind: number|image|message, subject, result_band, at)
AICallLog (purpose, model, tokens_in, tokens_out, latency_ms, cost_estimate)
```

The **status band** is computed on demand (and cached) from `ReportSubject` → approved `Report`s, using distinct reporters, reporter `trust_weight`, evidence score and age decay. It is never stored as the source of truth.

## 6. Key flows

### 6.1 Inbound message
1. WaSender POSTs to `/webhooks/whatsapp`. Group messages are routed to `groups`, and 1:1 messages continue below. We verify the signature, insert `InboundEvent` (unique on the message id, so retries are idempotent), enqueue `process_inbound(event_id)` and return 200 within ~100 ms.
2. The worker loads `Conversation`. If a flow is in progress, it continues that step. Otherwise the router classifies the input:
   - contains a CM number → **check number**
   - image → ask "Product photo or scam evidence?" (interactive buttons)
   - contact card → **check number**
   - other text → keyword intent (`report`, `signaler`, `help`, `aide`…) or else **check message**
3. The reply goes through `MessagingChannel` (rate-limited, typing delay). Send is idempotent per (event, step).

### 6.2 Check photo
Download the media (the URL expires quickly, so do this right away) → sha256 (exact match) → pHash (Hamming distance ≤ 8 means near-duplicate) → CLIP embedding (pgvector cosine search, top-k, threshold tuned on a labelled set) → combine the results → store an `ImageSighting` → reply. Then a web reverse search runs as a separate job (`WebImageSearch` adapter: `SerpApiLensProvider` now, `GoogleVisionWebDetectionProvider` later), subject to per-user and monthly caps, and sends a follow-up message only if it finds matches.

### 6.3 Report extraction
Each evidence image goes to Claude vision with a **strict JSON schema**: `{phone_numbers[], account_names[], amounts[], transaction_ids[], dates[], operator, product, summary, language, tamper_observations[]}`. Results are merged across all images, and numbers and names are normalised. Then the tamper heuristics run: font/time inconsistencies flagged by the model, plus EXIF/recompression checks and duplicate evidence already used in another report. The summary is shown back to the user to confirm. On submit, the linker finds related reports by shared number, name, image or text similarity.

### 6.4 Moderation
Django admin with a custom **review page**: evidence gallery, AI fields next to editable confirmed fields, linked reports, and one-click decisions. Approving writes `ModerationDecision`, invalidates the band cache for each subject, and enqueues a notification to the reporter (a free-form message inside 24 h, an approved template otherwise).

## 7. Security and privacy

- Evidence is stored in a private bucket, opened only through short-lived signed URLs from the dashboard, and every view is audit-logged.
- `User.wa_id` and phone numbers of *reporters* are never included in check responses. Masked account names only.
- Moderators get 2FA, roles (moderator / admin) and least privilege.
- Secrets live in environment variables or the platform's secret store. We rotate the WhatsApp system-user token.
- **Hosting region (decided):** EU (Frankfurt). Data leaves Cameroon whatever we host, through WaSender and WhatsApp/Meta, Anthropic (Claude), Groq and SerpAPI, so the lawyer must approve cross-border transfer under Law 2024/017 regardless. Every foreign processor is listed in the privacy notice. We move to in-country hosting only if the law requires the database itself to stay in Cameroon.
- **Retention (decided 23 Nov 2026)**, enforced by a nightly `retention` job; every deletion is written to the audit log:
  | Data | Kept for |
  |---|---|
  | Raw webhook payloads | 30 days |
  | Abandoned draft reports | 7 days after last activity |
  | Rejected reports: evidence | 90 days |
  | Rejected reports: minimal record (reporter, reason, date; no images) | 24 months (for R3 reporter weighting) |
  | Approved reports: evidence | 36 months from approval, then deleted; only anonymised counts and statistics are kept |
  | Voice notes | Same as the parent report. Opted-in training copies stay until consent is withdrawn. |
  | Check logs | 12 months, then aggregated per number per month |
  | Group sightings | 24 months |
  | Moderation audit log | Never deleted (contains no evidence) |
  | **Legal hold** | Overrides all of the above when the police or a court asks |

## 8. AI cost and quality controls

- All prompts are versioned in `ai/prompts/`. We keep a labelled fixture set (start with 30–50 real or anonymised scam screenshots and messages in FR/EN/Pidgin) and an `evals` command that scores extraction accuracy and red-flag precision.
- Haiku for routing and message red flags, Sonnet only for vision extraction. Prompt caching for the long system prompts.
- Per-user rate limits (e.g. 30 checks/day, 3 reports/day) cap both cost and abuse.

## 9. Repository layout (proposed)

```
tchek-am/
  docs/                    PRD, architecture, ADRs, idea brief
  src/tchekam/             Django project
    settings/              base / dev / prod
    messaging/  groups/  conversations/  identifiers/  checks/
    reports/  ai/  imaging/  moderation/  reputation/
    locale/                fr / en / pcm (Pidgin) message catalogues
  tests/                   pytest; fixtures incl. sample webhook payloads & images
  evals/                   AI evaluation sets + runner
  docker-compose.yml       postgres+pgvector, minio
  pyproject.toml           uv-managed
```

## 10. Build order (MVP)

1. Skeleton: Django + uv + Docker Compose + CI (lint, tests). WaSender webhook receive plus an echo reply over a tunnel, through the `MessagingChannel` adapter. **This proves the channel end to end.**
2. `identifiers` + `checks` number check (F1) with seeded data. Conversation router + i18n (FR/EN first, Pidgin copy reviewed by a native speaker).
3. `reports` flow + `ai` extraction + `speech` voice-note transcription (F4) + Django admin moderation (F5, single moderator: no roles or assignment).
4. `reputation` band rules (R1–R8) with thorough unit tests.
5. `imaging` photo check (F2).
6. Message check (F3), appeals (F6), notifications, rate limits.
7. Hardening: audit log, retention jobs, backups, monitoring (Sentry), load test on the webhook. Then the pilot.
