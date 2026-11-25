# Tchek-Am: Architecture Decision Record

All design decisions, the questions that led to them, the options considered and the answers given. Newest decisions are appended at the end. Entries are never edited after acceptance; if a decision changes, add a new entry that supersedes it.

*Sessions: 22 Nov 2026 (initial setup), 22–23 Nov 2026 (decision session).*

---

## ADR-001: Tech stack
Date: 2026-11-22 · Status: **Accepted**

**Question:** Which stack should the MVP use?

**Options considered:**
- **Python/Django (recommended):** Django admin gives most of the moderation dashboard for free; the ML is Python.
- **Python/FastAPI:** lighter, but the dashboard would have to be built by hand.
- **TypeScript:** NestJS/Hono + Next.js; the ML would need a Python sidecar.

**Answer:** Python/Django.

**Decision:** Python 3.13+, Django 5.x (Django Ninja for JSON endpoints), PostgreSQL + pgvector, and a Postgres-backed job queue (Procrastinate).

**Consequences:** One language and one database, and a nearly free moderation UI. The UI is less polished than a custom frontend. At large scale we may need Celery/Redis or a dedicated vector store.

---

## ADR-002: Moderation staffing during the pilot
Date: 2026-11-22 · Status: **Accepted**

**Question:** Who reviews scam reports during the pilot?

**Options considered:** the founder alone; the founder plus group admins; a small paid team.

**Answer:** The founder alone.

**Decision:** MVP tooling is Django admin plus one custom review page. No roles, per-group scoping or queue assignment.

**Consequences:** Much less to build. Review time is limited by one person's capacity (target: median under 24 h). Roles will be needed before adding moderators.

---

## ADR-003: Voice notes in the MVP
Date: 2026-11-22 · Status: **Accepted**

**Question:** Should reporters be able to send voice notes in the MVP?

**Options considered:** later (recommended, to limit complexity); yes, in the MVP.

**Answer:** Yes, in the MVP.

**Decision:** Voice notes are transcribed and the transcript goes into extraction alongside the screenshots. If the transcript is unclear, the bot asks the user to type the key details. The provider is chosen in ADR-008.

**Consequences:** More accessible for Pidgin speakers. Adds a speech-to-text dependency, its cost, and consent handling.

---

## ADR-004: Comparable platforms as a reference
Date: 2026-11-23 · Status: **Accepted (informational)**

**Question:** What do TrustGH (Ghana), CyberHub Ghana and Scam Alert NG (Nigeria) do?

**Findings:**
- **TrustGH:** LOW / MEDIUM / HIGH levels plus a 0–100 score. News coverage says more than half of reported numbers score 100%. Moderation is discretionary. Reporting requires registration with a one-time code. Its terms warn that false reports break Ghana's Cybersecurity Act. No appeal process or decay is published. It works with Ghana's Cybersecurity Authority and police.
- **CyberHub Ghana:** scores weighted by scam type (MoMo fraud 3.0, capped at 10). In the founder's example, three MoMo reports make a number high-risk. Reports are reviewed before approval.
- **Scam Alert NG:** lists "confirmed scammers" after team checks, with no published criteria. Its domain no longer resolves.

**Answer:** Founder agreed with all of these takeaways:
- avoid numeric scores;
- treat appeals and decay as differentiators ("hard agree");
- identify reporters;
- warn about false reports;
- use scam-type weighting only to sort the moderation queue.

**Consequences:** These takeaways shaped ADR-005 and ADR-007. We should also consider contacting TrustGH directly.

---

## ADR-005: Red threshold
Date: 2026-11-23 · Status: **Accepted**

**Question:** When does a number turn 🔴 red?

**Options considered:**
- **A. Strict:** always ≥ 2 independent approved reporters.
- **B. Evidence-weighted (recommended):** ≥ 2 independent approved reporters, or 1 approved report with payment proof.
- **C. Loose:** a single approved report.

**Answer:** B, but raised to **3** independent reporters.

**Decision:** 🔴 requires ≥ 3 independent approved reporters, **or** 1 approved report whose MoMo/OM transaction SMS and chat screenshot match each other and name the same number.

Reporters count as **independent** only if:
- they use different WhatsApp accounts;
- neither report names the other reporter's number; and
- they didn't submit near-identical evidence within minutes of each other.

A red result based on a single report says so ("1 reviewed report with payment proof").

**Consequences:** Stricter than comparable platforms, so easier to defend. Fewer numbers reach 🔴 early on. The moderator must check that payment proof matches.

---

## ADR-006: Band for approved reports below the threshold
Date: 2026-11-23 · Status: **Accepted**

**Question:** What do buyers see when a number has 1–2 approved reports but no payment proof?

**Options considered:**
- **A. A new 🟠 orange band (recommended).**
- **B. Show them as 🟡**, alongside pending reports.
- **C. Show them as 🟢.**

**Answer:** A.

**Decision:** The bands are:
- 🟢 **No reports**
- 🟡 **Waiting for review** (pending reports, count only)
- 🟠 **Reviewed, below the red threshold:** "Reported by N people, evidence reviewed. Not enough for a high-risk warning. Be careful: prefer cash on delivery."
- 🔴 **High risk**

Rejected reports are never shown. There is no public numeric score.

**Consequences:** Honest results, and moderation work still warns buyers. There are four states to explain in the copy.

---

## ADR-007: Decay of old reports
Date: 2026-11-23 · Status: **Accepted**

**Question:** How do old reports lose weight (R8)? The main driver is that operators may recycle inactive numbers.

**Options considered:**
- **A. Tiered decay (recommended).**
- **B. A hard 12-month cutoff.**
- **C. No decay; appeals only.**

**Answer:** A.

**Decision:**
- **0–12 months:** reports count fully.
- **12–24 months:** reports are visible, but can make a number at most 🟠.
- **24+ months:** hidden from the public, kept for the moderator.
- A number stays 🔴 only if it has ≥ 1 approved report in the last 12 months.
- Every 🟠/🔴 result shows the date of the last report.
- The appeal flow has a **"this number is new to me"** path: the appellant gives the date they got the number.

**Consequences:** Lower defamation risk, and a differentiator. Bands depend on time, so they must be recomputed or cached with expiry. A dormant scammer can come back at 🟠.

---

## ADR-008: Speech-to-text provider
Date: 2026-11-23 · Status: **Accepted**

**Question:** Which speech-to-text service for voice notes? Cameroonian Pidgin and Camfranglais accuracy is the risk.

**Options considered:**
- **A. OpenAI `gpt-4o-transcribe`.**
- **B. Groq `whisper-large-v3`.**
- **C. Self-hosted `faster-whisper`.**
- **D. Test A and B first (recommended).**

**Answer:** B, and grow our own database later.

**Decision:** Groq `whisper-large-v3` behind a `SpeechToText` adapter. Errors are caught by the user confirming the extracted fields and by the moderator playing the audio. If the transcript is unclear, the bot asks the user to type the key details. With **separate opt-in consent**, voice notes plus the user-corrected fields form our own corpus for fine-tuning a model later.

**Consequences:** Cheap and fast. Weak Pidgin accuracy at first. The training corpus needs its own consent and retention handling (ADR-013).

---

## ADR-009: Web search for photo checks
Date: 2026-11-23 · Status: **Accepted**

**Question:** Should a photo check also search the web, or only our own database? (The internal database is empty at launch. Bing Visual Search was retired in August 2025.)

**Options considered:**
- **A. Internal only.**
- **B. Always search both.**
- **C. Internal first, then web, with caps (recommended,** using Google Cloud Vision Web Detection).

**Answer:** Use SerpAPI now, and move to Google Cloud Vision once funded.

**Decision:** Flow C:
1. Match against the internal database (sha256, pHash, CLIP/pgvector) and reply right away.
2. Run a web reverse search and send a follow-up message only if it finds matches.
3. Cap web searches per user per day, plus a global monthly budget.
4. Always run it on report images.

Provider: **SerpAPI (Google Lens)** now, then **Google Cloud Vision Web Detection**, behind a `WebImageSearch` adapter.

**Consequences:** Useful from day one with bounded cost. SerpAPI scrapes Google, which is a grey area under Google's terms: acceptable for the pilot, but we must migrate before scaling.

---

## ADR-010: Hosting
Date: 2026-11-23 · Status: **Accepted**

**Question:** Where do we host? Data leaves Cameroon regardless, through WhatsApp, Claude, Groq and SerpAPI.

**Options considered:**
- **A. A managed platform in the EU (recommended).**
- **B. A VPS in the EU (Hetzner).**
- **C. Inside Cameroon.**

**Answer:** A.

**Decision:** Render, Frankfurt region: web service, background worker, and managed Postgres with pgvector. Cloudflare R2 (EU jurisdiction) for evidence storage, plus Sentry for errors. Plain Docker + Postgres keeps us portable.

**Consequences:** Minimal operations work. Costs a bit more than a VPS. The lawyer must approve cross-border transfer under Law 2024/017. We move in-country only if the law requires it.

---

## ADR-011: WhatsApp channel
Date: 2026-11-23 · Status: **Accepted.** Company registration is **on hold**.

**Question:** Company registration and the bot's phone number. The recommendation was the official Meta Cloud API, unverified for the pilot, with a dedicated SIM and company registration in parallel.

**Answer:** Use **WaSender** for WhatsApp, and leave the company decision for now. Founder accepted all the safeguards below.

**Risks raised:**
- the number can be banned without warning;
- scammers may mass-report our number;
- WaSender is a third-party processor that sees all evidence;
- it weakens credibility with ANTIC.

**Decision:** WaSender for the pilot, behind a `MessagingChannel` interface. No other module imports WaSender code. Required safeguards:
1. The adapter, so the Meta Cloud API can be swapped in.
2. Human-like behaviour: reply only to users who message first, no unsolicited messages, rate-limited replies with typing delays.
3. A backup number, pinned by partner admins next to the main one.
4. Switch to the **Meta Cloud API** when the company is registered and funded, **or at the first ban**, whichever comes first.

Menus are numbered text, because buttons may not render through the gateway.

**Consequences:** The pilot can start immediately, and group listening becomes possible (ADR-012). The ban risk is accepted.

---

## ADR-012: Group listening in the MVP
Date: 2026-11-23 · Status: **Accepted**

**Question 1:** Should group listening be in the MVP? This is the bot joining partner groups to collect product photos, which only WaSender allows.

**Answer:** Yes.

**Question 2:** What rules apply to group listening?

**Answer:** Founder accepted the proposed defaults.

**Decision:**
- **Consent:** only groups whose admin has consented, recorded with a date. The bot leaves any group it is added to without consent.
- **Notice:** the admin posts or approves a notice ("This group is protected by Tchek-Am. Product photos are checked for reuse.").
- **What we store:** product-image fingerprints plus a thumbnail, the poster's number, the time and the group. **No message text or chat history.** Non-product images are discarded.
- **What's public:** only aggregate sighting counts, never which group.
- **Opt-out:** members message "STOP GROUP".
- **Retention:** 24 months.
- **Bot behaviour:** it never posts in the group or sends members private messages.

**Consequences:** The photo database grows quickly. We process data about people who haven't used the bot, so the legal review must cover this. Not storing text limits scam-ring text matching.

---

## ADR-013: Data retention
Date: 2026-11-23 · Status: **Accepted**

**Question:** How long do we keep each kind of data?

**Answer:** Accepted the proposal as written.

**Decision:**

| Data | Kept for |
|---|---|
| Raw webhook payloads | 30 days |
| Abandoned draft reports | 7 days after last activity |
| Rejected reports: evidence | 90 days |
| Rejected reports: minimal record (reporter, reason, date; no images) | 24 months (for reporter weighting, R3) |
| Approved reports: evidence | 36 months from approval, then only anonymised statistics |
| Voice notes | Same as the parent report. Opted-in training copies stay until consent is withdrawn. |
| Check logs | 12 months, then aggregated |
| Group sightings | 24 months |
| Moderation audit log | Never deleted (contains no evidence) |
| Legal hold | Overrides everything above when the police or a court asks |

Enforced by a nightly job; every deletion is audit-logged.

**Consequences:** Smaller breach and liability exposure. Retention and legal-hold support are needed from the first release. Old cases can't be re-examined after 36 months.

---

## ADR-014: Messaging boundary and webhook rules (implementation)
Date: 2026-11-23 · Status: **Accepted**

**Question:** How is the WaSender integration kept safe and swappable in code? (This came up while building ISSUES.md Issue 3.)

**Decision:**
- All WhatsApp I/O goes through the `MessagingChannel` protocol and `get_channel()`. Only `tchekam.messaging` may import `WaSenderChannel`, and a source-scan test enforces this.
- Webhook idempotency: `InboundEvent.message_id` is unique, rows are created with `get_or_create`, and the processing job is enqueued only for a new row, via `transaction.on_commit`.
- The webhook fails closed. An empty `WASENDER_WEBHOOK_SECRET` rejects every request, and prod refuses to start without it.
- Channel errors and `InboundEvent.error` carry only the endpoint, status or exception class, never message bodies or phone numbers.
- The WaSender API key is sent only to the API host, never to the media download host.

**Consequences:** Swapping in the Meta Cloud API means writing one new class. `InboundEvent.payload` holds raw personal data, so it is covered by the 30-day retention rule (ADR-013).

---

## ADR-015: Reputation engine implementation safeguards
Date: 2026-11-23 · Status: **Accepted**

**Question:** Which implementation details does the band logic need to stay defensible? (This came up while building ISSUES.md Issue 7.)

**Decision:**
- **Structure:** pure facts → rules → service layers, with `now` passed in explicitly. The rules are pure functions with 100% branch coverage, enforced in CI.
- **Report age:** the earlier of the decision date and the incident date. Counted in days (365 / 730), in the Africa/Douala timezone.
- **Reporter identity:** each report keeps a stable pseudonymous `reporter_key` (HMAC of the reporter's number). Independence is judged on this key, so a reporter who erases their account can't turn into several "independent" reporters.
- **Low-trust reporters:** a reporter with trust weight below 0.3 still *links* other reporters as dependent, but a group made up only of low-trust reporters doesn't count as an independent reporter. Their reports also can't make a number red through payment proof, and can't meet the "approved report in the last 12 months" condition. An erased reporter is treated as having trust 0.0 until a trust record that survives erasure exists (ISSUES.md Issue 24).
- **Monotonicity invariant:** lowering a reporter's trust, or erasing a reporter, must never make a band more severe. A property test enforces this. The "names the other reporter's number" link compares pseudonymous keys, so it still works after erasure.
- **Cache:** band results are cached in a **shared database cache** (not per process) for 1 hour. The cache is cleared after commit through a `report_status_changed` signal. Any other change that affects a band (subject confirmation, payment proof, trust weight, appeals) must call `invalidate_report` / `invalidate_phone`.

**Consequences:** Results stay consistent across the web and worker processes, and the rules can be audited and tested in isolation. Prod needs `REPORTER_KEY_SECRET`; rotating it would split reporter identities.

---

## ADR-016: AI module implementation
Date: 2026-11-23 · Status: **Accepted**

**Question:** How is Claude called, and what is recorded about each call? (This came up while building ISSUES.md Issue 9.)

**Decision:**
- **One seam to the provider:** Claude is called only through the `LLMClient` interface in `tchekam.ai`. Only `ai/anthropic_client.py` imports the `anthropic` SDK, and a source-scan test enforces this. The SDK installed is 2.12.0 (the brief assumed 1.x); its call shapes were checked against the installed source.
- **Models:** `claude-haiku-5-5` for routing and message flags, `claude-sonnet-5-5` for screenshot extraction. Thinking stays at its adaptive default and depth is set with `output_config.effort` (medium for extraction). No sampling parameters, no prefill, no forced tool choice.
- **Structured output:** a JSON schema built from pydantic models (`output_config.format`), with every property required and no extra properties, not tool use.
- **Refusal fallback:** Sonnet extraction calls use the server-side refusal fallback (`AI_REFUSAL_FALLBACK`, on by default). Consequence: a different model may then process the evidence, so the served model is logged on every call. Haiku has no fallback. A refusal or a `max_tokens` stop counts as an extraction failure.
- **Images:** all of a report's images go to Sonnet in one call (this replaces the architecture note about one call per image, because cross-checking chat against payment screenshots needs them together). Skipped or over-cap images keep their slot in `evidence_kinds` as "other". Images that are oversized or look like decompression bombs are skipped, never raised on.
- **Signature:** `extract_evidence(images: list[(bytes, mimetype)], transcript, story, lang)`.
- **Call log:** `AICallLog` stores metadata only: served model, token counts (including cache read/write), latency, error class, request id. It never stores prompts, responses, images or phone numbers. It has no cost column; cost is derived from tokens when needed.
- **Prompts:** versioned files `ai/prompts/<purpose>/vN.md`, with the highest N used and the version logged.
- **Wording rule (R4):** the prompt forbids accusatory labels, and a deterministic post-filter removes banned terms from the model's summary and tamper observations before anything is shown.

**Consequences:** The provider can be swapped by writing one class. Evidence is processed by Anthropic (and possibly a fallback model), which the privacy notice must name. Extraction quality is measured by the eval runner (`python -m evals.run extraction`) once real, anonymised cases exist.

---

## ADR-017: Report flow processing model
Date: 2026-11-23 · Status: **Accepted**

**Question:** How does the report flow do slow work (downloads, transcription, AI) without holding up the conversation or losing user data? (This came up while building ISSUES.md Issue 11.)

**Decision:**
- **Handlers stay fast.** Handlers run while the per-user conversation row is locked, so they never download, transcribe or call AI. They queue jobs with `Context.enqueue_after(...)`. The service runs those jobs only after the transaction commits and the replies are delivered, and still runs them if delivery fails.
- **Messages from jobs** go only through `conversations.outbound.send_to_user`, which never raises and logs only a class name and the user's internal id.
- **Draft state lives on the report, not in the conversation.** The reporter's text is saved to `Report.story_text` as it arrives, so it survives MENU, language changes and expiry. The conversation keeps only the report id, the step, and a set of pending file ids.
- **Limits are enforced twice:** a quick check in the handler, and a final check in the ingest job under a lock (conversation, then report), so concurrent files cannot exceed 10 items or 15 MB. Refused files are deleted from storage.
- **Idempotency:** each stored file is unique per report by the provider's message id; extraction is skipped when a fingerprint of its inputs (evidence ids, hashes, story) is unchanged, and failed results are not reused, so FINI retries them.
- **Personal data added:** `Report.story_text`, `Report.ai_extraction`, `Evidence.transcript`. All are covered by the retention schedule (ADR-013, Issue 24).

**Recovery guarantees (checked against the code):**
- A stored file is kept only if its evidence record was created; on every other path it is deleted, and a failure while sending an acknowledgement never affects it.
- A file job that never reports back blocks DONE for at most 10 minutes, is then re-queued once, and if it is still missing 10 minutes later a further DONE drops it and tells the user how many files to resend; the user stays in collecting, and extraction starts only on the DONE after that.
- A crashed extraction always ends in a safe state: the user goes back to collecting and is told to send DONE again. A vanished extraction job is re-queued by a DONE sent more than 10 minutes after it started.
- Unchanged evidence is never sent to the AI twice (input fingerprint), but a stored failure is always retried.
- **Known gap:** if a slow extraction is still running after 10 minutes and the user sends DONE, the model may be called twice (one handover message, double billing).

**Consequences:** The conversation stays responsive and the user can always recover by sending DONE again. The in-memory object store is now a single shared instance in dev and tests.

---

## ADR-018: Moderator access control
Date: 2026-11-23 · Status: **Accepted**

**Question:** How is access to victims' evidence protected? (This came up while building ISSUES.md Issue 14.)

**Decision:**
- **Two-step login:** every `/moderation/` and `/admin/` page requires a password plus a one-time code from an authenticator app (django-otp TOTP). A staff user with no enrolled device cannot log in at all.
- **Enrolment is command-line only** (`add_totp`), so there is no web page that could be abused to add a device. It prints the secret, the setup link and 8 one-time recovery codes once.
- **Sessions:** expire after 8 hours without activity and when the browser closes; cookies are HttpOnly, SameSite=Strict, Secure and HSTS in production.
- **Login throttle:** 5 failures per username (after the same Unicode normalisation Django uses) or 20 per client address lock further attempts for 15 minutes. The message is identical for unknown users. An operator can clear a lock with `unlock_login`.
- **Client address:** taken from the connection, or from the N-th hop from the right of `X-Forwarded-For` where `TRUSTED_PROXY_COUNT=N` (never the first, client-controlled hop).
- **Audit:** every evidence view, login, failed login (only an HMAC prefix of the username) and unlock is logged.

**Accepted risks:** a correct password (without a token) is confirmable through the device-selection step of the login form, limited by the throttle to 5 guesses per account per 15 minutes (a later improvement is to pre-select the single device and show one generic error before the token is verified); changing `SECRET_KEY` resets login counters and makes older audit hashes unmatchable; recovery codes are stored unhashed in the database (an attacker who can read the database can already reach the evidence references); the lock counter is not atomic on the shared database cache, so concurrent failures may undercount slightly.

**Consequences:** The only way to the evidence is a verified moderator session. Locking out the founder by deliberate failed logins is possible but recoverable with `unlock_login`.

---

## ADR-019: Group listening implementation
Date: 2026-11-24 · Status: **Accepted**

**Question:** How is group listening (ADR-012) built so that no group text is kept, the bot never writes to a group, and an opt-out always wins? (This came up while building ISSUES.md Issue 20.)

**Decision:**
- **Boundary:** the new `tchekam.groups` app plugs into messaging through `messaging.hooks.register_group_handler`, called from its `AppConfig.ready`. Nothing in messaging depends on groups, and a source-scan test checks that no other app imports `tchekam.groups` (imaging imports `PartnerGroup` for type checking only). The handler runs in the `messaging.process_inbound` job, never in the webhook request and never under a Conversation lock. Download, classification and ingest run in a separate queued job, `groups.ingest_image`.
- **No text at rest:** `messaging.parser.storable_payload` rebuilds every group payload from allow-lists before the webhook saves it. It keeps the key fields (id, fromMe, remoteJid, participant, cleanedParticipantPn), the event name, the timestamp and a kind marker. For an image it also keeps only the media pointers that decrypt-media needs (url, directPath, mimetype, mediaKey, mediaKeyTimestamp, fileSha256, fileEncSha256, fileLength). Message bodies, captions, quoted messages, vCards, display names and thumbnails are never stored. Private payloads are stored as received.
- **Leaving unconsented groups:** the bot leaves each jid at most once, ever. The `UnconsentedGroupLeave` row (unique jid) is the claim, inserted in the same transaction as the `leave_group` call. A concurrent delivery waits on the unique index and then does not leave again. If the call fails, the claim rolls back and a later message retries. This departs from ADR-012 ("the bot leaves any group it is added to without consent"): a group that adds the bot back after the first leave is ignored but not left (follow-up b in ISSUES.md Issue 20).
- **Paused and left groups:** a `PartnerGroup` with status paused or left is ignored without leaving, because consent exists or existed.
- **Posters:** a sighting needs the poster's number. A LID-only sender, or a number that is not Cameroonian, is discarded before download. This is a scope cut against PRD F8 ("every product photo"), recorded here rather than made silently.
- **Classifier:** `ai` purpose `is_product_photo` (Haiku with vision, strict schema `{is_product: bool}`, prompt v1). Only an explicit true is stored; false, a failure or a refusal discards the bytes. Verdicts are cached for 30 days per prompt version and sha256 in the shared Django cache, and failures are never cached.
- **Opt-out concurrency:** STOP GROUP and the group ingest serialise on a per-poster `pg_advisory_xact_lock`. The ingest re-checks consent and opt-out inside the lock, so an image being stored while its poster opts out is either deleted by the opt-out or refused by the job. Lock order is always the Conversation row, then the advisory lock, then Image rows `FOR UPDATE` in pk order (`imaging.erase.delete_sightings`). A sighting committed after the erasure locked its image fails the deferred foreign-key check instead of pointing at a deleted image. `groups.intake._store` retries once on that error.
- **Erasure:** `imaging.erase.delete_sightings` deletes the sightings, then every image left with no sighting, unless a report still refers to it. Thumbnails are deleted from the ObjectStore only after commit.
- **Group link on sightings:** `ImageSighting.group` is a foreign key to `PartnerGroup` on the existing `group_id` column, with PROTECT, so deleting a group can never leave its sightings behind. Group records are deleted only through the audited admin action "Delete group and all its sightings", which erases the sightings first.
- **Never writing to a group:** every `send_*` on `MessagingChannel` raises `GroupSendForbidden` for an `@g.us` target unless `allow_group=True` (unused in the MVP). It is deliberately not a `ChannelError`, so code that swallows provider errors cannot hide it. `send_to_user` refuses group targets without raising.
- **Router policy:** `DATA_PROTECTION_COMMANDS` (today only `group_opt_out`) runs before onboarding and also for blocked users. A group member who never used the bot can opt out with their first message (the reply is in all three languages), and blocking someone never keeps their group photos collected. Blocked users still get nothing for any other message.
- **Opt-out key:** `GroupOptOut` is keyed on `"+<digits>"`, the `BotUser.wa_phone` convention, so the check before download is one indexed lookup.
- **Consent records:** the admin requires a notice confirmation, sets the recorder from the logged-in staff member, makes consent fields read-only after creation, and audit-logs every create, change and deletion (field names and counts only).
- **Group metadata:** `groups.metadata.group_metadata` calls the provider at most once per group per day and keeps only the subject and member count, never the participant list.

**Consequences:** Group text never reaches the database, and the bot cannot post in a group by mistake. Photos posted by group members, most of whom never used the bot, are sent to Anthropic for classification, so the privacy notice and the legal review must name this processing. Group sightings use `seen_at` and the group link for the 24-month retention job (ADR-013, Issue 24). The known gaps are tracked as follow-ups under ISSUES.md Issue 20.

---

## ADR-021: Channel safeguards
Date: 2026-11-24 · Status: **Accepted**

**Question:** How does the bot stay under WhatsApp's and WaSender's limits, avoid unsolicited messages, survive a ban, and process each inbound message once? (This came up while building ISSUES.md Issue 23.)

**Decision:**
- **Decorator:** `get_channel()` returns `SafeChannel(channel)` when `CHANNEL_SAFEGUARDS` is true (default true; false in test settings so existing tests see the bare channel). Order inside a send: group refusal (`GroupSendForbidden`, unchanged), reply-only window, rate limits, typing, send.
- **Deferral seam:** our limiter raises `Deferred`, a subclass of `RateLimited`, so callers treat the provider's limit and ours the same way. `messaging.outbox.deliver` catches it and re-enqueues only the unsent replies as `messaging.deliver_replies` (queue `whatsapp`, delay at least `retry_after`). Re-running `process_inbound` would route the message twice, because routing has already committed. Transient `ChannelError`s retry up to 3 times with backoff; rate-limit deferrals are capped at 20. `send_to_user` queues its message as a `deliver_replies` job on the `whatsapp` queue (so background jobs obey the same lock cap, and results are delayed, not dropped); its return value only means "queued", and a send outside the reply window is dropped by the job. Reply-window notifications pass `defer=False` and keep the `PendingNotification` fallback.
- **Limiter:** one `pg_advisory_xact_lock` serialises every check, so it holds across workers. A global token bucket (`SEND_RATE_PER_MINUTE`, default 20) and a per-recipient sliding log (6 sends per 30 s; a log, so the 7th is always refused). Recipients are stored as keyed HMAC-SHA256 hashes; rows older than the window are pruned on every call. A refused send charges nothing.
- **Typing:** `send_typing(jid, min(4000, 40 ms x len(text)))`, then a sleep of the same length, inside the worker task. A typing failure other than a rate limit is swallowed.
- **Reply-only:** a send is allowed if `BotUser.last_inbound_at` is within `REPLY_WINDOW_HOURS`, else `UnsolicitedMessageBlocked` (a `ChannelError`). The `allow_unsolicited(to)` context manager is the escape hatch for delivering a queued `PendingNotification`; it is unused today because queued notifications are delivered inside a reply to an inbound message.
- **Failover:** `ChannelState` (one row) holds the active session, overriding the `WASENDER_ACTIVE_SESSION` default. The database is read on each `get_channel()` only when `WASENDER_BACKUP_API_KEY` is set. The WaSender channel cache is keyed by API key, so a switch applies on the next call. `switch_channel primary|backup` refuses a session without a key and writes an `AuditLog` row. The webhook accepts either session's secret. Prod settings refuse a backup session without its key.
- **Concurrency:** queue `whatsapp`, with lock `whatsapp-{sha256(recipient) % 3}` (Python's `hash()` differs per process): at most 3 sends at once. The webhook enqueues `process_inbound` on it with the sender's lock. Jobs with a lock are deferred with `lock_mode="mutex"`: Procrastinate's default `ordered` mode lets a waiting job scheduled for the future hold the lock, so one 30 s deferral would stall every job sharing its lock, a third of all users. The trade-off: ordering per recipient is no longer guaranteed, and a deferred tail can arrive after a newer reply.
- **Retry-safe processing:** `InboundEvent` gets `PROCESSING`, `claimed_at` and `attempts`. A worker claims with `filter(pk, status=RECEIVED).update(...)` (also adding 1 to `attempts`) and continues only if one row changed. `RateLimited` before routing committed requeues the event after the delay (cap 20, refunding the attempt). Other errors before the commit reset the event to `RECEIVED` and retry with backoff until `attempts` reaches 3, then `FAILED`. Any exception after the routing commit (delivery, limiter or database error, a delivered callback, enqueueing a job) is tagged `after_commit` by `handle_private_message`: the event ends `FAILED` with no re-run, since a re-run would route twice, and queued notifications stay pending. The periodic `messaging.recover_stuck_events` resets claims older than 10 minutes and re-enqueues them, or marks the event `FAILED` once it has been claimed 3 times.
- **Prod:** settings refuse to start with `CHANNEL_SAFEGUARDS` false.

**Accepted risks:** processing is at-least-once: a crash after a send and before `processed` can resend a reply (also after recovery). A rate-limit deferral counts as delivered for queued notifications, so one whose later retries all fail is lost. A send made inside a database transaction (`reports.notify`) holds the limiter's advisory lock until that transaction ends, briefly pausing other sends.

**Consequences:** A worker must listen to the `whatsapp` queue (see `docs/runbook.md`). The limits are per deployment, not per WhatsApp number: a switch to the backup does not reset the counters.

---

## ADR-022: Retention job and legal hold (implementation)
Date: 2026-11-24 · Status: **Accepted**

**Question:** How is the retention schedule (ADR-013) enforced without breaking bands, reporter weighting (R3) or legal holds? (This came up while building ISSUES.md Issue 24.)

**Decision:**
- **One nightly run, one audit row:** `retention.run` runs at 02:00 Africa/Douala (cron read in that timezone, not UTC). Each rule returns a count; the run writes a single `AuditLog("retention.run")` with the counts and the class names of failed rules, never personal data. This replaces "every deletion is audit-logged" one row per object. A failing rule does not stop the others. `run_retention --dry-run` counts and changes nothing.
- **Batches, not one transaction:** 200 rows per transaction, locked with SKIP LOCKED and re-checked under the lock, so a legal hold set mid-run wins and a busy row waits for the next night. Blobs are deleted only after their batch commits. Rules take `now` as an argument (no clock library).
- **Rejected reports:** evidence and personal fields go at 90 days, the subjects are replaced by `subject_phone_keys` (HMACs with `REPORTER_KEY_SECRET`), and the minimal record (reporter, status, dates, decisions with the reason) is deleted at 24 months, as the ADR-013 table says. A minimised report cannot be reopened. Consequence (accepted, per ADR-013): deleting the record removes that rejection from the reporter's counts, so their trust rises at their next recompute.
- **Approved reports at 36 months:** evidence, summaries, story, AI extraction and the reporter FK go; subjects, amount, dates and `reporter_key` stay. This never changes a band (the report has been hidden since 24 months). Reporter weighting counts reports by `reporter_key` as well as the FK, so trust does not fall when the FK is dropped.
- **Merged reports:** follow the approved schedule: anonymised 36 months after the merge (`decided_at`), independently of the target. They are duplicates whose facts live on in the target, so the same statistics are kept.
- **Trust survives erasure:** `ReporterTrust(reporter_key, trust_weight)` is written before a `BotUser` is deleted (a `pre_delete` receiver, which covers every deletion path) and before a report loses its reporter. Reputation reads it through `reputation.trust_hook` (installed by retention; reputation does not import retention). The lookup returns the lower of the snapshot and the trust of a live account on the same key; no record means 0.0, as before. A new `BotUser` on a number with history starts at the lower of its snapshot and the weight its old decided reports give (counted by key), never at the 1.0 default, so re-registering cannot restore weight. The snapshot only ever goes down: it is created with the current trust and later lowered (never raised, by an atomic conditional update), so a later account on the same number, the same person back or a recycled number's new owner, can never lift the weight of reports whose link is gone, whether that account is erased or retention anonymises one of its reports. A snapshot is written only for someone who reported, and deleted once no report carries the key. Consequence: an erased trusted reporter keeps counting, which updates ADR-015's interim rule; erasing still never makes a band more severe than before erasure. `REPORTER_KEY_SECRET` must never be rotated.
- **Training copies:** made after an approval or rejection commits (signal, then a queued job), only while both the evidence and the user are opted in, under `training/`, kept until STOP TRAINING or account erasure. STOP TRAINING is a data-protection command (works before onboarding and for blocked users); blob deletion is a queued job, never under the Conversation lock (ADR-017).
- **Appeals:** an undecided (draft) appeal is deleted 7 days after creation. A decided appeal loses its statement and evidence 12 months after the decision and keeps status, dates, `number_acquired_at` and the moderator's reason, so an approved "new to me" exclusion keeps working. Open appeals are never touched.
- **Short-lived logs:** delivered `PendingNotification` rows go 30 days after delivery; group events lose the poster and media key as soon as they will not be ingested, and in any case after 24 h (never while the poster's account or number is held); limiter tables prune themselves.
- **Legal hold:** flags on `Report`, `Evidence`, `PhoneNumber` and `BotUser`. A report is held if it, its reporter, a subject number (also through `subject_phone_keys` once the subjects are gone) or any of its evidence is held; a user's hold also covers their own number, including where that number is a report subject. Every rule skips held objects, a held user cannot be deleted, and every toggle (admin actions on reports, numbers, users) is audit-logged. Only superusers or staff with the `retention.manage_legal_hold` permission see and use the toggles.

**Consequences:** Retention can run on a large backlog without long locks, and a hold always wins. `CheckLogMonthly` keeps the subject (a number or an image hash) per month without any user link. Not yet covered: account-name rows left without subjects, `WebSearchUsage` and `AICallLog` rows (see the [DECIDE] items in the ISSUES.md Issue 24 note).

---

## ADR-023: Scoped OpenRouter access for the conversational agent

**Date:** 2026-11-24. **Status:** implementation accepted with all real roles disabled;
provider/model access decisions remain gated by the capability evidence in
`features/tchek-am-agent/CAPABILITIES.md`. Amends ADR-016 for this integration only.

The agent uses pinned `langchain-openrouter` behind `ai/agent/models.py` and scoped
structured extraction behind `ai/openrouter_client.py`. Existing Anthropic extraction,
group classification and Groq report transcription keep their current configuration.
Model and serving-endpoint allow-lists are separate. Requests require nested
`provider.only`, `data_collection=deny`, `zdr=true`, `require_parameters=true`, and
`allow_fallbacks=false`. No search plugins, input/output logging, Broadcast or hidden
legacy-model fallback is enabled. Account/key ZDR-only settings and legal exceptions
must be reviewed separately; a request flag alone is insufficient evidence.

Transport retries are disabled in the pinned SDK. Every paid attempt reserves a
conservative integer-micro-USD allowance against locked daily-user and monthly-global
ledgers before transport. Unknown billing retains the charge; duplicate settlement
cannot refund twice. Persistent counters include child calls and survive worker recovery.
Provider absence, refusal, malformed JSON, truncation and policy failure produce typed
unavailability and reviewed output. Model quality is not established by fake tests.

OpenRouter STT is explicitly unavailable: its current endpoint ignores provider `only`,
`order` and `ignore`. The adapter makes no request, including when configured with a key.
Revisit ADR-008 only after an independently enforceable and evaluated STT policy exists.
Conditional Gemini vision and alternatives remain disabled pending role-specific evidence.

## ADR-024: Bounded conversational graph with durable Django memory

**Date:** 2026-11-24. **Status:** accepted for disabled implementation; pilot acceptance
remains subject to Issues 26–35 and the evaluation specification.

A compiled outer LangGraph owns authorization, memory, media preparation, response
validation/rendering, final revalidation and atomic completion. A real `create_agent`
subgraph owns the model/tool loop. Its mandatory middleware repeats scope checks,
context bounds, persistent call counters, reservations and strict action validation.
Server-created runtime context is never constructed from model JSON. Tools provide
opaque run-local result handles; verdict text and substantive advice come from code
and reviewed catalogs. The model has no arbitrary text output channel.

Retain ADR-001's Procrastinate queue; use a separate `agent` queue/worker. The router
commits internal run/event ids before enqueueing. Generation, sequence, lease and fencing
checks enforce FIFO and reject stale completion. Completion commits memory, staged
preferences/consent-flow entry, run outcome and a unique delivery outbox atomically.
The guarded WhatsApp dispatcher rechecks authorization before every attempt. Channel
delivery remains at least once, with an unavoidable final-send cancellation race.

Django tables persist runs, bounded server-assigned turns and scoped HMAC-authenticated
entity aliases. History is untrusted data, never approval. No automatic summaries,
per-node checkpointer recovery, delegated agents or general-purpose execution tools.
MENU, data-protection commands, flow/language changes, blocking and the runtime kill
switch interrupt incompatible work. Ordinary consecutive idle turns remain ordered.

Agent photo checks use transient decoded query images against existing internal matches;
they do not add thumbnails/sightings to the shared catalog or automatically upload to
SerpAPI. This intentionally minimizes chat-media persistence. Existing deterministic
photo/report paths remain separate; their external-upload eligibility review is a pilot
blocker. Vision observations always require the user to verify/type critical values.
Agent chat and agent transcripts are never copied into training samples (D5).

## ADR-025: Agent retention and local metadata-only observability

**Date:** 2026-11-24. **Status:** local implementation accepted; production tracing and
hosting are not approved. Extends ADR-022 without editing its accepted rules.

| Store | Handling |
|---|---|
| Agent turns and aliases | Delete after 7 days; retrieval additionally expires after 24 hours, 20 messages and 6,000 conservative history tokens. |
| Agent delivery text | Clear after 7 days; pending records retain their delivery/recovery metadata. |
| Terminal run/operation/delivery/reservation metadata | Delete after 32 days, conservatively allowing the full reconciliation window. Pending runs remain until reconciled. |
| Per-user/global period budgets | Keep current period and at least 32 days for reconciliation; erase per-user scope keys on account erasure. |
| AICallLog | Aggregate after 90 days into anonymous monthly purpose/model token/call totals; no request or user identifiers in aggregates. |

Existing retention batching locks and rechecks candidates. User/run/linked-report/subject
holds protect applicable stores; holding data never extends its eligibility as context.
User erasure cascades through agent stores unless applicable legal hold forbids erasure.
Budget charges for uncertain requests remain conservative through recovery.

The local synthetic Langfuse trial uses an isolated localhost-only pinned Compose stack.
A private OpenTelemetry provider exports explicit metadata spans to the supported
OTLP/HTTP endpoint. No stock LangChain callback, media instrumentation or global exporter
is installed. Span names/outcomes are closed enums; attributes are constructed from fixed
policy codes and bounded numeric counters, never arbitrary callback metadata.
Export/authentication failures disable optional tracing and cannot retry inference or
change replies. Flush is bounded. Real-user trace export stays off pending selective
deletion/hold support, processor review and a production hosting decision (D3/D4).

## ADR-026: OpenRouter for every AI flow; retain SerpAPI

**Date:** 2026-11-25. **Status:** accepted by owner instruction. Supersedes the direct
provider choices in ADR-008/016/019 and the limited migration scope in ADR-023.

Use OpenRouter for conversational planning, screenshot/report extraction, group-photo
classification, message warning flags and transcription. All chat/image tasks use
`deepseek/deepseek-v4.1-flash-1017`; the former separate fast model is removed globally.
Keep the existing Whisper Large V3 transcription family, now addressed as
`openai/whisper-large-v3` through OpenRouter. Both are configurable model ids.
One `OPENROUTER_API_KEY` supplies all AI calls. Delete the Anthropic SDK/adapter,
direct Groq adapter, their keys/base URLs/model selectors and refusal-fallback option.
Keep SerpAPI and its existing adapter, quotas, key and eligibility rules unchanged.
WhatsApp, storage, database and application secrets remain necessary.

Structured calls retain strict JSON validation, refusal/truncation handling, bounded
timeouts, content-free audit and deterministic downstream confirmation/verdicts.
Chat/image requests enforce approved endpoints, ZDR, no data collection, no provider
fallbacks and no hosted plugins. Reports/groups retain their existing quotas; agent
children additionally use the persistent shared reservation and invocation limits.

OpenRouter transcription supports `provider.zdr` and `provider.data_collection`, but
ignores endpoint `only`, `order` and `ignore` preferences. The prior endpoint-list
requirement for STT is replaced by the documented ZDR-only data-policy route, relying
on the owner's account-ZDR confirmation. No unsupported allow-list guarantee is made.
The adapter is implemented instead of returning the previous unconditional unavailable
result. Agent audio is owned, bounded by parsed audio-container duration/bytes and deadline, limited
to one durable STT attempt, and cannot be replayed after uncertain billing. A low or
missing-quality transcript cannot silently submit a report or adopt extracted evidence.

Historical ADRs and archived paid-test receipts remain evidence of earlier choices.
No provider credentials are revoked externally and no deployment occurs here. The
privacy/processor inventory must reflect OpenRouter and its selected serving providers
before real-user rollout. Contract tests use mock HTTP; real STT accuracy still needs
a separate FR/EN/PCM audio evaluation.

References: [STT parameters](https://openrouter.ai/docs/guides/overview/multimodal/stt),
[transcription API](https://openrouter.ai/docs/api/api-reference/stt/create-transcription).

## Still open
- **Company registration / legal entity:** on hold (see ADR-011).
- **To confirm with the lawyer:** Law 2024/017 (cross-border transfer, group-listening data, sensitive ID data in Phase 2), defamation exposure of the band wording, and whether Cameroon's 2010 cybersecurity law can back the false-report warning.
- **To verify:** each operator's number-recycling rules (input to ADR-007), and current SerpAPI pricing and limits.
