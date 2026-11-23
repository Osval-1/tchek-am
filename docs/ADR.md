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

## Still open
- **Company registration / legal entity:** on hold (see ADR-011).
- **To confirm with the lawyer:** Law 2024/017 (cross-border transfer, group-listening data, sensitive ID data in Phase 2), defamation exposure of the band wording, and whether Cameroon's 2010 cybersecurity law can back the false-report warning.
- **To verify:** each operator's number-recycling rules (input to ADR-007), and current SerpAPI pricing and limits.
