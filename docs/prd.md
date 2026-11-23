# Tchek-Am: Product Requirements Document

*Status: superseded as the build spec by [features/tchek-am-mvp/PRD.md](features/tchek-am-mvp/PRD.md) (v1.0, 23 Nov 2026). Kept as background and rationale. Decisions: [ADR.md](ADR.md); terms: [CONTEXT.md](CONTEXT.md).*

> "Tchek am before you pay." A WhatsApp bot that lets buyers in Cameroon check a seller's number, product photo or message before sending MoMo / Orange Money, and lets victims report scams with evidence.

Background and market research: [idea-brief.md](idea-brief.md). Technical design: [architecture.md](architecture.md).

---

## 1. Problem

WhatsApp is Cameroon's main online marketplace. Payment is made upfront by MTN MoMo or Orange Money, which gives the buyer no protection. The most common scam is simple: the buyer pays an advance or the full price and the seller disappears. Buyers have no quick way to check a seller first, and nothing local does this job (see the competitor table in the brief).

## 2. Goals and non-goals

### Goals (MVP)
1. A buyer can get a useful answer about a seller **in under 30 seconds, without leaving WhatsApp**.
2. A victim can file an **evidence-backed report** in under 5 minutes, with the AI doing most of the typing.
3. **No report affects what the public sees until a human has reviewed it.**
4. Build a database good enough that, after the pilot, at least 1 in 5 number checks returns a meaningful signal (reports, or a confirmed reused photo).

### Non-goals (MVP)
- Holding or moving money (escrow is Idea 2, a later phase; it needs a licensed partner).
- A native mobile app.
- Labelling anyone a "scammer". We report facts ("reported N times, evidence reviewed"), not verdicts.
- Recovering stolen money or acting as the police. We point victims to the right channels.
- Verified seller badges (Phase 2, see §8). They are planned for, but not built in the MVP.

## 3. Users

| Persona | Need | Main touchpoint |
|---|---|---|
| **Buyer** (primary) | "Can I trust this seller before I send money?" | WhatsApp bot |
| **Victim / reporter** | "I was scammed. Warn others, and maybe help get my money back." | WhatsApp bot (report flow) |
| **Honest seller** | "Show buyers I'm real." Clear my name if wrongly reported. | Bot (appeal), later badge + public profile page |
| **Group admin** | Keep scammers out of my selling group. | Bot; later a group-admin channel or digest |
| **Moderator** (internal) | Review reports and appeals quickly and consistently. | Web moderation dashboard |

Languages: **French, English, Cameroonian Pidgin**. The bot answers in the user's language and the user can switch at any time.

## 4. MVP features

### F1. Check a number
**Input:** a typed number in any format (`6 77 12 34 56`, `+237677123456`, `00237…`), a shared contact card, or a forwarded message that contains a number.

**Output:**
- Normalised number + operator (MTN / Orange / Nexttel / Camtel), derived from the prefix.
- **Status band** (no raw numeric score in the MVP):
  - 🟢 *No reports*: "No reports. That doesn't prove the seller is honest. Here's how to stay safe…"
  - 🟡 *Unverified reports*: "N reports are waiting for review."
  - 🟠 *Reviewed, below the red threshold*: "Reported by N people, evidence reviewed. Not enough for a high-risk warning. Be careful: prefer cash on delivery." (1–2 approved reports without matching payment proof.)
  - 🔴 *High risk*: "Reported N times by M different people. Evidence reviewed. Last report: [month year]." (R2 threshold met.)
  - Rejected reports are never shown in any band.
- Linked names (MoMo/OM account names seen in reviewed reports, shown partially masked: `JEAN-P*** M***`).
- How many times this number has been checked (a social signal: "checked 14 times this month").
- A link to report it, and safety tips (prefer cash on delivery, meet in public, check that the MoMo name matches).

**Acceptance:** works with every common CM number format; answers in under 5 s at p95; never shows a reporter's identity or unreviewed details.

### F2. Check a photo
**Input:** a product image (forwarded or uploaded).

**Output:** "This photo matches N other posts in our database (first seen [date], posted by M different numbers)" and/or "This looks like a catalogue image (AliExpress, Jumia, etc.)". If the matches are tied to reported numbers, say so.

**MVP limits:** we match against our own corpus (every image submitted to the bot, plus partner-group posts when an admin consents). Web matching (decided 23 Nov 2026): **internal first, then web.** The bot replies right away with internal matches, then runs a web reverse-image search and sends a follow-up message only if it finds catalogue or other-seller matches. Web searches are capped per user per day and by a global monthly budget, and always run on images attached to reports. Provider: **SerpAPI (Google Lens)** for the MVP, then **Google Cloud Vision Web Detection** once funded, behind a swappable adapter. *Risk: SerpAPI scrapes Google, which is a grey area under Google's terms. That's acceptable for the pilot; move to the official API before scaling.*

**Acceptance:** finds near-duplicates after resizing, cropping (up to about 20%), recompression and WhatsApp's own compression; answers in under 10 s at p95.

### F3. Check a message
**Input:** pasted or forwarded seller text.

**Output:** the red flags it detected, each with a short plain-language explanation. For example: price far below market; pressure to pay in full upfront; urgency ("only today"); "my representative / transporter will deliver"; asking for payment to a different name; refusal to meet or to accept cash on delivery. Also any numbers or names in the text, auto-checked as in F1.

**Approach:** rules plus an LLM classifier (FR/EN/Pidgin). It returns red flags, not a verdict.

### F4. Report a scam (AI-assisted)
A guided conversation in the bot:
1. **Collect.** The user sends screenshots (chat, product post, MoMo/OM SMS confirmation) and a short description by text or **voice note** (voice notes are in the MVP; decided 22 Nov 2026). Voice notes are transcribed (Groq Whisper), and the transcript goes into extraction alongside the screenshots. If the transcript is unclear (low confidence, or no number or amount found), the bot asks the user to type the key details.
2. **Extract.** AI pulls out phone numbers, MoMo/OM account names, amounts, transaction IDs, dates and the product, and writes a 2–3 line summary.
3. **Confirm.** The bot shows what it extracted and the user fixes or confirms it.
4. **Consent.** The user agrees to the terms: true statement, data use, no public identity, and a warning that knowingly false reports may be an offence (wording to be checked by the lawyer). There is a **separate, optional opt-in** to let us use their voice notes and corrections to improve speech recognition.
5. **Queue.** The report goes to moderation with automatic checks (tampering signals, links to existing reports, an evidence-quality score).
6. **Close the loop.** When the moderator decides, the reporter gets a WhatsApp message with the outcome, plus guidance on next steps (operator fraud lines, how to file a police complaint, ANTIC/CIRT).

**Acceptance:** median completion under 5 minutes; extraction gets the reported number right ≥ 95% of the time on the test set; the reporter can abandon the flow and resume it within 24 h.

### F5. Moderation dashboard (internal web)
- A queue of pending reports, sorted by priority (how often the number is being checked × evidence quality).
- Side-by-side view: evidence images, extracted fields (editable), AI flags, linked reports and the cluster graph.
- Actions: **Approve**, **Reject** (with a reason), **Need more info** (the bot asks the reporter), **Merge** (duplicate).
- An appeals queue (F6).
- A full audit log of every moderator action. Evidence opens only after login, and every view is logged.

### F6. Appeal
Anyone who controls a reported number can start an appeal from that number by messaging the bot (this proves ownership). There's a **"this number is new to me"** path: the appellant gives the date they got the number, and reports from before that date can be cleared quickly (recycled numbers, see R8). They give their side and evidence, the reports are re-reviewed, and the outcome is sent to them. While an appeal is open, the check result says "under appeal".

### F8. Group listening (partner groups)
The bot's number joins partner selling groups **with the admin's consent** and adds every product photo posted there to the photo database (for F2), along with the poster's number and the time.
Rules (decided 23 Nov 2026):
- **Consent:** only groups whose admin has agreed, recorded with a date. The bot leaves any group it is added to without that consent.
- **Notice:** the admin posts or approves a pinned notice or group-description line: "This group is protected by Tchek-Am. Product photos are checked for reuse."
- **What we store:** product images only (fingerprints for matching, plus a thumbnail), the poster's number, the time and the group. **No message text, no chat history.** Non-product images are classified and discarded.
- **What's public:** only the summary in a photo check result ("posted by 3 different numbers since March"). We never reveal which group a photo came from.
- **Opt-out:** any member can message the bot "STOP GROUP" to have their posts deleted and to stop being collected.
- **Retention:** group sightings are kept for 24 months (in line with R8).
- The bot **never posts** in the group, apart from an optional one-time introduction that the admin approves.

### F7. Onboarding and help
- First message: a language picker plus a 3-option menu (Check / Report / Help) as **numbered text** ("Reply 1, 2 or 3"). Interactive buttons aren't reliable through WaSender.
- Free-form input is detected automatically: a number triggers F1, an image asks "Product photo or scam evidence?", text triggers F3.
- Privacy notice and terms are linked on first use.

## 5. Trust and safety rules (product requirements, not suggestions)

| Rule | Detail |
|---|---|
| **R1: Human gate** | Only *approved* reports count toward the 🔴 band. Unreviewed reports show only as a count in 🟡. |
| **R2: Red threshold** (decided 22 Nov 2026) | 🔴 requires **either** ≥ 3 *independent* approved reporters, **or** 1 approved report whose MoMo/OM transaction SMS and chat screenshot match each other and name the same number. Reporters count as *independent* only if they use different WhatsApp accounts, neither report names the other reporter's number, and they didn't submit near-identical evidence within minutes of each other. A red result from a single report says so ("1 reviewed report with payment proof"). |
| **R3: Reporter weighting** | Reporters whose reports keep getting rejected are down-weighted and rate-limited. One WhatsApp account can make at most N reports per day. |
| **R4: Wording** | Never "scammer", "fraud" or "arnaqueur" as a verdict. Use factual wording only. Copy is reviewed by a lawyer before launch. |
| **R5: Reporter anonymity** | A reporter's number and identity are never shown to anyone except moderators. |
| **R6: Data minimisation** | Store only what's needed. Victims' own details are redacted from evidence used in any shared view. Retention limits are set (§9). |
| **R7: Appeal always available** | Every 🔴 or 🟡 result says how to contest it. |
| **R8: Decay** (decided 23 Nov 2026) | Because operators may recycle inactive numbers, reports decay in tiers. **0–12 months:** full weight. **12–24 months:** still visible, but can't make a number red on their own (at most 🟠). **24+ months:** hidden from the public, kept for the moderator. A number stays 🔴 only if it has ≥ 1 approved report from the last 12 months; otherwise it drops to 🟠 automatically. Every 🟠/🔴 result shows the date of the last report. |

## 6. Success metrics

| Metric | Pilot target (8 weeks after launch in 2 partner groups) |
|---|---|
| Weekly active checkers | 500 |
| Checks per week | 1,500 |
| Reports submitted / approved | 100 / 50 |
| Checks with a meaningful signal (🟡/🔴/photo match) | ≥ 20% |
| Median moderation time | < 24 h |
| Appeals that overturned a decision | Tracked (a high rate means our review process is too loose) |
| Qualitative | Partner admins say it reduced scams in their group |

## 7. Constraints and dependencies

- **WhatsApp channel: WaSender (unofficial gateway) for the pilot** (decided 23 Nov 2026). It needs no company or Meta verification, and it lets the bot join groups (F8). **Risks:** WhatsApp can ban the number without warning; scammers can mass-report our number; WaSender is a third-party processor that sees all messages; and it weakens our position with ANTIC. **Safeguards (required):** (1) all bot logic goes through a `MessagingChannel` adapter, so the official Cloud API can be swapped in; (2) human-like behaviour: reply only to users who message first, no unsolicited messages, rate-limited replies with typing delays; (3) a backup number, kept ready and pinned by partner admins next to the main one; (4) **switch to the official Meta Cloud API** when the company is registered and funded, or at the first ban, whichever comes first. **UX constraint:** interactive buttons and lists may not render through an unofficial gateway, so every menu is numbered text ("Reply 1, 2 or 3").
- **Data protection.** Cameroon's personal data protection law (Law No. 2024/017, verify the current implementing texts and regulator) applies. Get legal advice on: lawful basis, sensitive data (ID documents in Phase 2), cross-border hosting and transfer, and the defamation exposure of published report counts.
- **LLM and vision provider** processes evidence images, which contain personal data. This must be covered in the privacy notice and the data processing agreement.

## 8. Roadmap

| Phase | Scope | Exit criteria |
|---|---|---|
| **0. Validate** (now, ~2 wks) | 3–5 group-admin interviews, 10 buyer interviews, test Voshup, legal consult, set up the WaSender number + a backup number (company registration: on hold) | ≥ 2 admins commit to a pilot; there's demand to check before paying |
| **1. MVP** (~6–8 wks build) | F1–F7, moderation dashboard, internal photo corpus | Pilot live in 2 groups |
| **2. Seller reputation** | Verified seller badge (ID + MoMo-name match via payment), public profile page (PWA), subscription billing (Fapshi/Campay), "confirmed sale" signal from buyers | Paying sellers; verified sellers report more sales |
| **3. Network** | Scam-ring clustering surfaced to moderators and partners, group-admin tools (weekly digest, bulk-check members), B2B API, ANTIC/CIRT data sharing | First B2B contract or institutional partnership |
| **4. Payments** (Idea 2) | "Pay safely" links via a licensed partner's hold/release feature | Legal sign-off and a partner contract |

## 9. Open decisions

1. ~~Tech stack~~: **DECIDED** Python/Django + Postgres/pgvector (22 Nov 2026).
2. ~~Hosting~~: **DECIDED** Render (Frankfurt) + Cloudflare R2 EU (see architecture.md §2, §7).
3. ~~Red threshold~~: **DECIDED** (see R2). ~~Decay window~~: **DECIDED** tiered decay (see R8). ~~How approved reports below the red threshold are shown~~: **DECIDED** 🟠 orange band (23 Nov 2026).
4. ~~Voice notes~~: **DECIDED** in the MVP. ~~Speech-to-text provider~~: **DECIDED** Groq whisper-large-v3, with our own corpus built later (opt-in).
5. ~~External reverse-image search~~: **DECIDED** internal first, then web, via SerpAPI → Google Cloud Vision later (see F2).
6. ~~Moderators~~: **DECIDED** the founder alone during the pilot. MVP tooling = Django admin + one custom review page. No roles or queue assignment yet.
7. ~~WhatsApp channel~~: **DECIDED** WaSender + safeguards (see §7). **[ON HOLD]** Legal entity / company registration.
8. ~~Retention~~: **DECIDED** (see architecture.md §7).
