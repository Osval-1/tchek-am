# Tchek-Am: Domain glossary

Use these terms consistently in code, copy and docs. Decisions behind them: [ADR.md](ADR.md).

| Term | Meaning |
|---|---|
| **Check** | A buyer's lookup of a number (F1), photo (F2) or message (F3). It never changes reputation; it is only logged (`CheckLog`). |
| **Report** | A victim's evidence-backed claim about a seller (F4). Lifecycle: `draft → pending → (needs_info) → approved / rejected / merged`. |
| **Reporter** | The WhatsApp user who submits a report. Their identity is never shown publicly (R5). |
| **Subject** | What a report is about: a `PhoneNumber`, an `AccountName` (MoMo/OM holder name) or an `Image`. One report can have several subjects. |
| **Evidence** | A file attached to a report: chat screenshot, MoMo/OM SMS, product post, voice note. Private and encrypted; every access is audit-logged. |
| **Payment proof** | A MoMo/OM transaction SMS that matches a chat screenshot and names the same number. Lets a single approved report reach 🔴. |
| **Approved report** | A report a moderator has accepted. Only approved reports count toward 🟠/🔴. |
| **Independent reporters** | Reporters on different WhatsApp accounts, where neither report names the other reporter's number, and who did not submit near-identical evidence within minutes of each other. |
| **Status band** | The public result for a number, always computed, never stored as truth: 🟢 *No reports* · 🟡 *Waiting for review* · 🟠 *Reviewed, below the red threshold* · 🔴 *High risk*. |
| **Red threshold** | ≥ 3 independent approved reporters, **or** 1 approved report with payment proof, **and** ≥ 1 approved report in the last 12 months. |
| **Decay** | How report weight changes with age: 0–12 months full; 12–24 months visible but at most 🟠; 24+ months hidden from the public. |
| **Appeal** | A challenge by whoever controls a reported number, started from that number. Includes the *"this number is new to me"* path. |
| **Recycled number** | A number an operator reassigned to a new owner. This is the main reason for decay. |
| **Sighting** | One occurrence of an image (from a bot submission or a partner group), with the poster's number and the time. |
| **Partner group** | A WhatsApp selling group whose admin has consented to group listening. |
| **Group listening** | The bot silently collecting product-photo sightings in partner groups. No message text is stored. |
| **Web match** | A reverse-image-search hit on the open web (SerpAPI now, Google Vision later), sent as a follow-up message. |
| **Moderator** | The human who approves or rejects reports and appeals. During the pilot this is the founder alone. |
| **Channel** | The WhatsApp transport behind `MessagingChannel`: WaSender now, Meta Cloud API later. |
| **Legal hold** | A flag that suspends retention deletion at the request of the police or a court. |
| **InboundMessage** | The provider-neutral form of one incoming WhatsApp message (private or group). |
| **InboundEvent** | One stored raw webhook delivery, keyed by the provider's message id. Status: received / processed / failed / ignored. Kept for 30 days. |
