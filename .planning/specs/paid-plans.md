# Feature 16: Paid plans (plugin SDK + monthly subscription)

Epic: `.planning/epics/mebot-open-source.md` · Depends on: #15 (hosted mode) · Size: L+, split into **16a** billing core and **16b** plugin SDK · Worker: Opus

## Goal

The hosted platform becomes a paid service. Owners sign up, bring their own LLM key, embed the bot with a drop-in plugin, and pay a monthly subscription to keep it serving. **Self-host stays free and open source:** billing exists only when `MODE=hosted` AND a billing provider is configured. Otherwise every code path behaves exactly as today.

## Non-negotiables
- **No card or UPI data ever touches mebot.** Only provider-hosted checkout and portal pages (PCI SAQ-A scope).
- **Subscription state changes only through verified webhooks** (plus a reconciliation job). Never trust a checkout redirect or a client call.
- Provider secrets come from env only. They are never stored in the DB, never logged, and scrubbed from errors (reuse `llm.base.scrub`).
- Recruiters never see billing. An unpaid bot looks "unavailable", the same as suspended.
- No real network in tests. The user runs a manual E2E in provider **test mode** themselves.

---

## 16a — Billing core

### Providers
- Interface `BillingProvider`: `create_checkout(owner, plan, currency) -> url`, `portal_url(owner)`, `cancel(subscription, at_period_end)`, `fetch_subscription(id)`, `verify_webhook(headers, raw_body) -> Event`, `parse(event) -> NormalizedEvent`.
- **Razorpay** (INR; UPI AutoPay and cards): Subscriptions API (plan_id, subscription create → `short_url`). Webhook signature `X-Razorpay-Signature` = HMAC-SHA256(raw body, webhook secret). Events: `subscription.authenticated/activated/charged/pending/halted/cancelled/completed`, `invoice.paid`. Razorpay has no customer portal, so cancel goes through our API, and updating the payment method uses the subscription `short_url`.
- **Stripe** (USD and others): Checkout Session `mode=subscription`, plus the Billing Portal. Webhook `Stripe-Signature`: verify the timestamp + v1 HMAC with a 5-minute tolerance. Events: `checkout.session.completed`, `customer.subscription.created/updated/deleted`, `invoice.paid`, `invoice.payment_failed`.
- Use raw `httpx`, no provider SDKs (matches the LLM adapters, testable with respx). Implement signature verification ourselves, with test vectors.
- Config: `BILLING_PROVIDERS=razorpay,stripe` (either or both), `RAZORPAY_KEY_ID/KEY_SECRET/WEBHOOK_SECRET`, `STRIPE_SECRET_KEY/WEBHOOK_SECRET`. Currency is chosen by the owner at checkout (India/INR → Razorpay, else Stripe), never by IP.

### Data (next free migration)
- `plans`: code, name, active, `prices` JSON {currency: {amount_minor, provider, provider_plan_id}}, `limits` JSON (messages/day, tokens/day, imports/day, …), trial flags. Seed with `trial` and `monthly`. Edited by the operator via CLI/UI, not hard-coded.
- `subscriptions`: bot_id, provider, provider_customer_id, provider_subscription_id, plan_code, status, current_period_end, cancel_at_period_end, grace_until, trial_ends_at, updated_from_event_at.
- `billing_events`: provider + event_id (unique), type, received_at, processed_at, error. Raw payload is kept 30 days, minus PII where possible.
- `invoices`: bot_id, provider_invoice_id (unique), amount_minor, currency, status, period, hosted_url/pdf_url, gst fields if the provider supplies them.
- `trial_claims`: HMAC(normalised email) and claimed_at, so one trial per email survives account deletion.
- `admins.terms_version` + `terms_accepted_at`.
- No FKs, TEXT ids, TIMESTAMPTZ on Postgres.

### Webhooks
- `POST /api/billing/webhook/{provider}`: read the raw body, verify the signature (400 on failure, logged without the body), then insert into `billing_events` (duplicate event_id → 200 no-op), then process in a transaction.
- Out-of-order safety: ignore events older than `subscriptions.updated_from_event_at` for status changes. Invoices are upserted regardless.
- Unknown event types: store and return 200.
- A processing error is recorded on the event, returns 500 so the provider retries, and pings the maintainer on Telegram.
- Reconciliation job (daily, plus on demand from the operator panel): `fetch_subscription` for every non-terminal subscription; fix any drift and audit it.

### State machine
`none → trialing → active → past_due (grace_until = now + BILLING_GRACE_DAYS, default 7) → inactive`, plus `cancelled` (serving until `current_period_end`, then `inactive`). Payment success from past_due or inactive returns to active. Transitions live in one pure function with a table-driven test, and every transition is logged.

### Trial
- Starts at signup approval: `TRIAL_DAYS` (default 14) or `TRIAL_MESSAGES` (default 200), whichever comes first. No card needed.
- One trial per email (`trial_claims`).
- Owner emails at 3 days left, at 80% of messages, and at expiry, using the 15a mailer.

### Gating
- `is_serving(bot)` = `status in (trialing, active, past_due-within-grace, cancelled-before-period-end)`. It's checked in the same place as the 15a "live" check.
- Not serving: public chat/widget gets the neutral `BOT_UNAVAILABLE` (same body as suspended); owner admin stays fully usable so they can fix billing; data is retained. After 90 days inactive, a reminder mail is sent. **No automatic deletion.**
- Plan limits: effective limit = min(plan limit, HOSTED_MAX cap, owner's own lower setting). Plug into the #6 limits, no new limiter.
- When billing is off (self-host, or no provider configured), `is_serving` = true and plan limits are ignored. Test that single mode is untouched.

### Owner UI: Account → Billing
Plan and status (trial days/messages left, renewal date, grace warning banner), choose plan + currency → checkout, manage (Stripe portal / Razorpay update link), cancel at period end (with confirmation), invoices list, and usage this period. Signup gets a ToS + privacy checkbox (stores terms_version). Works at 375/768/1440 with loading, empty and error states.

### Operator panel (extends 15b)
Subscription status/plan columns, MRR by currency, past-due list, a "reconcile now" button, and a manual comp (grant N free days, with a reason, audited). Still no access to content or keys.

### Notifications
Maintainer Telegram ping on new subscription, cancellation, payment failed, and webhook processing errors (best-effort).

### Account deletion (15a flow)
Cancel the provider subscription immediately, before the soft-delete. If the cancel fails, block the delete with a clear error. Invoices are kept for tax records (the purge keeps `invoices` rows, anonymised; document it).

### Legal (templates, not legal advice)
`docs/legal/terms.md`, `privacy.md`, `refunds.md` with placeholders and a banner: "must be reviewed by a lawyer before launch". Cover DPDP/GDPR: data categories, the owner-brought LLM key, sub-processors (LLM provider, payment provider, Telegram), export and delete rights (exist from 15a). GST: rely on the provider's GST invoicing (Razorpay); store an optional owner GSTIN; platform GSTIN in settings. Own invoice generation is out of scope. Flag that a CA should review.

---

## 16b — Plugin SDK

- New `packages/sdk/` (TS, built with Vite library mode). It wraps the existing iframe embed (keeps CSP/iframe isolation; never renders chat in the host DOM).
  - Web component `<mebot-chat bot-key="pk_…" theme="light|dark|auto" position="right">`.
  - React wrapper `MebotChat` (separate entry, React as a peer dependency).
  - Plain JS `Mebot.init({botKey, …})`.
- API: `open()`, `close()`, `toggle()`, events `ready/open/close/message` (via postMessage with an origin check).
- Theming via CSS variables (`--mebot-accent`, `--mebot-radius`, `--mebot-font`, launcher size/offset), passed to the iframe as validated params (allow-list, no raw CSS injection).
- Public bot key only. The SDK must never accept or forward an LLM key (add a test).
- Origin allow-list per bot: the CSP frame-ancestors from #8, plus a server-side `Origin` check on public chat/session APIs in hosted mode. Unknown origin → `BOT_UNAVAILABLE`.
- Versioning: semver. CDN path `/sdk/v1/mebot.js` (served by the backend with long cache + immutable versioned files), npm package name as a placeholder `<npm-scope>/mebot`. Size budget: ≤ 6 KB gzip core (check in CI).
- Release: workflow file for npm publish on tag. **Do not publish.**
- Docs: `docs/sdk.md` with examples (HTML, React, Next.js, WordPress snippet).
- The existing one-line loader keeps working (backwards compatible).

## Tests
- Signature verification vectors for both providers (valid, tampered, wrong secret, stale Stripe timestamp).
- Webhook idempotency (duplicate), out-of-order, unknown type, processing error → 500 + event error recorded.
- State-machine table; grace expiry; cancel at period end; reconciliation drift fix.
- Trial by days and by messages; one trial per email after deletion and re-signup.
- Gating: unpaid → neutral 404 identical to suspended; owner admin still works; single mode and billing-off unchanged.
- Limits are min(plan, cap, owner).
- Secrets never appear in logs or errors (caplog check).
- The operator still can't reach content (extend the 15b test to the new routes); the cross-tenant suite covers the new billing routes automatically.
- SDK: vitest for the web component/React wrapper, the postMessage origin check, theme param allow-list, no-LLM-key, and size check.
- The full suite passes on SQLite and on Postgres (MEBOT_TEST_POSTGRES).

## Out of scope
Coupons, annual plans, usage-based metering, taxes beyond the provider's, our own invoice PDFs, team seats, refunds automation (manual via the provider dashboard).

## Gate 1 checklist
- [ ] Billing inert unless hosted + provider configured (test)
- [ ] Hosted checkout/portal only; no payment data stored
- [ ] Webhook signature verified, idempotent, out-of-order safe; reconciliation job
- [ ] State machine with grace; gating via neutral unavailable
- [ ] Trial (days/messages), one per email
- [ ] Plan limits = min(plan, cap, owner)
- [ ] Billing page, operator billing view, maintainer pings
- [ ] Deletion cancels the subscription first
- [ ] Legal templates flagged for lawyer/CA review
- [ ] 16b SDK: web component + React + JS, iframe-isolated, origin allow-list, ≤6 KB, not published
- [ ] Split: 16a verified before 16b starts
