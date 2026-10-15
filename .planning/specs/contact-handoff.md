# Spec: contact-handoff

**Created**: 2026-10-16
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 7c)

---

## Problem

When a recruiter wants to talk to the owner ("Can we set up a call?", "How do I reach him?"), the bot has no clear, owner-controlled way to hand them off. The owner wants recruiters to get their portfolio, email, Instagram, WhatsApp username, LinkedIn, etc. — but **not** their mobile number unless they explicitly allow it. No calendar booking.

## Goal

The owner manages a list of contact channels, each with a **Share with recruiters** switch. On meeting/contact intent, the bot replies with only the shared channels (and offers the #7 "Leave my contact" form). Non-shared values never appear in any bot output, enforced by an output guard, not just the prompt.

## User Stories

- As a **recruiter**, I ask "Can I schedule a call with him?" → "Shivansh would be happy to connect! You can reach him here: 🌐 Portfolio … ✉️ Email … 📸 Instagram … 💬 WhatsApp @… — or leave your details and he'll get back to you."
- As the **owner**, I add my phone number for my own records but keep Share off; the bot never reveals it.
- As a **recruiter**, I tap a "Contact" button in the chat header and see the shared channels as clickable links.

## Requirements

### Must-have
1. **Schema (Alembic 0010):** extend `profile_links` (from #4) into contact channels:
   - add `kind TEXT NOT NULL DEFAULT 'website'` — `portfolio|website|email|linkedin|github|instagram|whatsapp|telegram|x|phone|other`
   - add `share BOOLEAN NOT NULL DEFAULT true`
   - `url` renamed/kept as `value` (URL, email address, or handle depending on kind); keep `label`.
   - Migration: existing links → `kind` inferred from domain (linkedin.com → linkedin, github.com → github, instagram.com → instagram, else website), `share=true`. `profile_identity.email_public` → channel `email`, `share=true`. `profile_identity.phone_public` → channel `phone`, **`share=false`**. Old identity columns kept but no longer used (documented), not dropped.
2. **Validation per kind:**
   - `email`: valid address. `phone`: E.164-ish digits; **default `share=false`** on create; enabling share requires an explicit `confirm_share_phone: true` in the request.
   - `whatsapp`: **username/handle only** (e.g. `@shivansh` or `wa.me/username` style). Values that are mostly digits (≥ 7 digits) are rejected with "This looks like a phone number — add it as a Phone channel instead (not shared by default)."
   - `instagram|x|telegram|github`: handle or profile URL; normalised to a canonical URL for display.
   - `portfolio|website|linkedin|other`: http(s) URL only.
   - Max 30 channels.
3. **Renderer:** `CONTACT CHANNELS (share these when someone wants to reach or meet {name})` listing only `share=true` channels in sort order. Non-shared channels are **never** sent to the LLM.
4. **Prompt rule:** on meeting / call / interview / hire / "how can I contact" intent: say {name} would be happy to connect, list the shared channels, offer the "Leave your contact" form; never invent or promise times/dates; never say it can book a meeting. If no channels are shared: offer only the contact form.
5. **Output guard** (extend the #6 stream filter): before streaming, build a redaction set from all **non-shared** channel values (and their normalised forms: digits-only phone, with/without `+`/spaces, handle with/without `@`). If any appear in output → replace with `[hidden]`, log `CHANNEL_REDACTED` (no value logged). Also redact any phone-number-shaped string (≥ 10 digits) unless it exactly matches a shared phone channel.
6. **Public endpoint:** `GET /api/public/contact-channels` → shared channels only `{ "items": [{ "kind", "label", "display", "href" }] }` (`href` = `mailto:`, `https://wa.me/…` for WhatsApp usernames, profile URLs). Rate limited via #6.
7. **Recruiter UI:** "Contact" button in chat header → panel with shared channels as icon + label links (open in new tab, `rel="noopener noreferrer"`) + "Leave my contact" (#7 form). Bot replies containing channel URLs/emails render as clickable links (safe linkify: http(s)/mailto only).
8. **Admin UI:** Identity page "Contact channels" list (replaces Links sub-list): kind select with icon, value, label, **Share with recruiters** toggle, reorder, delete; phone kind shows warning text and a confirm dialog when enabling share; WhatsApp field hint "Use your WhatsApp username, not your number".
9. **Telegram (#7):** `contact` notifications unchanged. No calendar features.
10. **Docs:** README "How recruiters contact you".

### Nice-to-have
- Per-channel click counts on the dashboard.
- Copy-to-clipboard for email in the panel.

### Out of scope
- Calendar booking / scheduling integrations.
- Showing different channels to different visitors.

## Data Model

Alembic 0010 changes `profile_links` (adds `kind`, `share`, renames `url`→`value`). snake_case, UTC timestamps, existing soft delete.

## API Changes

```
POST /api/admin/profile/links { "kind": "whatsapp", "label": "WhatsApp", "value": "@shivansh", "share": true } → 201
POST /api/admin/profile/links { "kind": "phone", "value": "+91 98xxxxxx12" } → 201 { ..., "share": false }
PUT  /api/admin/profile/links/{id} { "share": true } → 422 { "error": { "code": "CONFIRM_REQUIRED", "message": "Confirm you want to share your phone number with recruiters.", ... } }
PUT  /api/admin/profile/links/{id} { "share": true, "confirm_share_phone": true } → 200
GET  /api/public/contact-channels → { "items": [{ "kind": "email", "label": "Email", "display": "shivansh@example.com", "href": "mailto:shivansh@example.com" }] }
```

## UI Changes

Recruiter: Contact button + panel, linkified replies. Admin: contact channels editor on Identity page.

## Edge Cases

1. Phone channel exists, share off, recruiter asks "What's his number?" → bot declines + offers shared channels; number never in output (guard).
2. Owner put their phone number in Notes/FAQ text → guard still redacts phone-shaped strings not shared; preview page warns "Your notes contain a phone number".
3. WhatsApp given as a number → 422 with guidance.
4. No shared channels → bot offers only the contact form.
5. LLM hallucinates an email address → not in shared set; if it matches a non-shared value → redacted; if invented, prompt rule + evals cover (documented limitation).
6. Migration with existing links/email/phone → correct kinds; phone not shared.
7. `javascript:` or `data:` value → 422; linkify ignores non-http(s)/mailto.
8. Value split across stream chunks → guard tail buffer catches it.
9. Owner turns share off → immediately removed from prompt, public endpoint and allowed set.

## Testing Criteria

- Migration 0010 mapping (kinds, phone share=false, idempotent).
- Validation per kind incl. WhatsApp-number rejection, phone share confirm.
- Renderer includes only shared channels; non-shared never in messages sent to FakeLLM.
- Guard: non-shared value (and normalised variants) redacted, split across chunks; phone-shaped string redaction; shared phone allowed; `CHANNEL_REDACTED` logged without value.
- Public endpoint returns only shared, correct hrefs; rate limited.
- Frontend: admin editor (toggle, phone confirm, WhatsApp hint), recruiter Contact panel, safe linkify.
- Evals: meeting-intent questions return shared channels; "what's his phone number" never returns it.
- `pytest`, `npm run typecheck && npm run build && npm test` green.

## Dependencies

- Features 1–7b (`feature/learning-loop`).

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Columns typed with defaults · [x] Migration mapping defined · [x] Soft delete (existing)
- [x] Endpoints + examples · [x] snake_case JSON · [x] standard error shape
- [x] 9 edge cases · [x] Happy + edge tests · [x] Dependencies listed
