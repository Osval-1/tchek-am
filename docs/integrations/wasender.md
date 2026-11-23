# WaSender API: integration notes

*From the public docs, read 23 Nov 2026. The docs contradict themselves in places (flagged ⚠). **Verify every event name and field against a live test session** before relying on it. All parsing must be defensive.*

## Auth and base URL
- Base URL: `https://www.wasenderapi.com/api` (the www form, as used on the endpoint pages).
- `Authorization: Bearer <SESSION_API_KEY>`. The key is **per session**; deleting the session invalidates it.
- There is also an official Python SDK on PyPI (`wasenderapi`), not evaluated. We use plain `httpx` behind our own adapter.

## Sending: `POST /api/send-message` (JSON)
| Type | Body |
|---|---|
| Text | `{"to": "+2376XXXXXXXX", "text": "..."}` |
| Image | `{"to": ..., "imageUrl": "<public URL>", "text": "<optional caption>"}`. JPEG/PNG only, max 5 MB, **by URL only**, so use a short-lived signed R2 URL. |
| Audio | `{"to": ..., "audioUrl": "<public URL>"}` |
| Contact | `{"to": ..., "contact": {"name": ..., "phone": ...}}` |

`to` can be an E.164 number or a group JID. Response: `{"success": true, "data": {"msgId": 100000, "jid": "...", "status": "in_progress"}}`.

Errors look like `{"success": false, "message": "...", "errors": {...}}`. A rate-limit body includes `retry_after` (seconds); the HTTP status code isn't documented, so treat any response with `retry_after` as rate-limited.

## Typing indicator: `POST /api/send-presence-update`
`{"jid": "<contact jid>", "type": "composing", "delayMs": 1500}`. The type is one of `composing | recording | available | unavailable`.

## Webhooks
- Configured per session in the dashboard (or `PUT /api/whatsapp-sessions/{id}`). Every delivery is a JSON POST. **Respond 200 quickly.**
- **Security:** header `X-Webhook-Signature` equals the configured Webhook Secret, compared as a plain value (not HMAC). Compare with `hmac.compare_digest`. No replay protection is documented, so rely on message-id idempotency.
- Envelope: `{"event": "...", "timestamp": 1633456789, "data": {"messages": {...}}}`. ⚠ One sample reads `data.key` directly, so accept both `data.messages` and `data`.
- ⚠ Event names vary across pages: `messages.received`, `messages-personal.received`, `messages-group.received`, `messages.upsert` (includes our own outgoing messages, so ignore anything with `key.fromMe == true`). Accept all of them and tell private from group by the fields below.
- **Private message** `data.messages`:
  - `key.id`: message id (our idempotency key)
  - `key.fromMe`
  - `key.remoteJid`: may be a LID (`...@lid`), so **don't treat it as a phone number**
  - `key.cleanedSenderPn`: the sender's phone number, digits only
  - `messageBody`: the text, or a media caption
  - `message.conversation`: the text
- **Group message:**
  - `key.remoteJid` is the group JID
  - `key.participant` is the sender's JID
  - `key.cleanedParticipantPn` is the sender's phone number
  - The presence of `key.participant` / `cleanedParticipantPn`, or a group event name, means it's a group message.
- **Media:** under `message.imageMessage | audioMessage | videoMessage | documentMessage | stickerMessage`, with fields `url`, `mimetype`, `mediaKey`, `fileSha256`, `fileLength`, `fileName`. The caption is in `messageBody`.
- **Contact card:** the webhook shape isn't documented. Fall back to extracting a phone number from any text found.
- Group join and membership events: "Group Upsert" / "Group Participants Update". The exact event strings are unverified.

## Media download: `POST /api/decrypt-media`
Body: `{"data": {"messages": {"key": {"id": "<msg id>"}, "message": {"imageMessage": {...media object as received...}}}}}` → `{"success": true, "publicUrl": "..."}`. The URL is valid for **1 hour**, so download immediately.

## Groups
- `GET /api/groups`
- `GET /api/groups/{groupJid}/metadata` returns `{subject, owner, desc, participants: [{jid, isAdmin, isSuperAdmin}]}`
- `POST /api/groups/{groupId}/leave`

## Rate limits and ban guidance
- **Trial: 1 send per minute, 50 per day. The pilot needs a paid plan** (256 per minute). The optional "Account Protection" mode limits sends to 1 every 5 s.
- Group metadata: 10 per minute, 500 per day, so **cache it**.
- Keep 1–5 concurrent workers per session. High concurrency is a documented cause of bans.
- Response headers: `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and the daily equivalents.
