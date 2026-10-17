# Paid plans (hosted mode)

Self-hosted mebot is free and has no billing code paths. Billing switches on only when
`MODE=hosted` **and** `BILLING_PROVIDERS` lists at least one fully configured provider;
otherwise every bot serves as before and plan limits are ignored.

## Setup

1. Create plans at the provider (test mode first):
   - **Razorpay** (INR, UPI AutoPay + cards): Subscriptions → Plans → a monthly plan → its
     `plan_...` id.
   - **Stripe** (USD/EUR/GBP): a recurring monthly Price → its `price_...` id. Enable the
     Customer Portal (Settings → Billing → Customer portal).
2. Set env vars (see [configuration](configuration.md)): `BILLING_PROVIDERS`,
   `RAZORPAY_KEY_ID/KEY_SECRET/WEBHOOK_SECRET`, `STRIPE_SECRET_KEY/WEBHOOK_SECRET`. Secrets
   live in env only, never in the database, and are scrubbed from logs and errors.
3. Point webhooks at `https://<PUBLIC_URL>/api/billing/webhook/razorpay` and
   `.../stripe`:
   - Razorpay events: `subscription.authenticated`, `.activated`, `.charged`, `.pending`,
     `.halted`, `.cancelled`, `.completed`, `.resumed`, `invoice.paid`.
   - Stripe events: `checkout.session.completed`, `customer.subscription.created`,
     `.updated`, `.deleted`, `invoice.paid`, `invoice.payment_failed`.
4. Set prices (the seeded `trial` and `monthly` plans have none), from the platform panel
   (`PUT /api/platform/plans/{code}`) or the CLI:

   ```bash
   python -m mebot.cli plans set-price monthly INR 49900 razorpay plan_XXXX
   python -m mebot.cli plans set-price monthly USD 900 stripe price_XXXX
   python -m mebot.cli plans set-limit trial daily_message_cap 100
   python -m mebot.cli plans list
   ```

   INR is always sold through Razorpay, every other currency through Stripe. The owner
   picks the currency at checkout; it is never guessed from the IP.

## How it behaves

- **Trial**: starts when a bot goes live (sign-up without approval, or approval):
  `TRIAL_DAYS` or `TRIAL_MESSAGES`, whichever runs out first. One trial per e-mail, ever:
  an HMAC of the normalised address is kept in `trial_claims` and survives deletion.
  Owners get mail at 3 days left, at 80% of messages, at the end, and after 90 days offline.
- **States**: `none → trialing → active → past_due (BILLING_GRACE_DAYS) → inactive`, plus
  `cancelled` (serving until the paid period ends). A payment from `past_due` or
  `inactive` returns to `active`. The table lives in `mebot/billing/state.py`.
- **Gate**: a bot that isn't serving answers visitors with the same neutral
  `BOT_UNAVAILABLE` 404 as a suspended one. The owner's admin stays fully usable and data is
  kept; nothing is deleted automatically.
- **Limits**: effective limit = min(plan limit, `HOSTED_MAX_*` cap, owner's own setting).
- **Status changes** only come from verified webhooks, the provider's answer to our own
  server-side calls (cancel, reconciliation) and the hourly deadline sweep. A checkout
  redirect never changes anything.
- **Webhooks**: signature first (400, the body is never logged), then the event is stored
  (provider + event id unique). A processed duplicate is a 200 no-op; an event whose
  processing failed is answered 500 (the provider retries) and run again on the retry.
  Events older than the last applied one don't change status; invoices are upserted
  anyway. Events for a replaced subscription id are ignored for status. Unknown types are
  stored and answered 200; events no bot can be matched to are stored with
  `error = "unmatched"`.
- **Reconciliation**: daily, and "Reconcile now" in the platform panel, asks the provider
  about every active / past-due / cancelled subscription and fixes drift (audited).
  Razorpay can't show a cancel scheduled for the period end, so a local `cancelled` isn't
  reverted to `active` by Razorpay's answer.
- **Deletion**: owner or operator deletion cancels the provider subscription immediately
  first; if the provider doesn't confirm, the deletion is refused with a clear error. The
  purge keeps `invoices` rows for tax records, anonymised (hosted invoice links removed).
- **Comps**: the operator can grant N free days with a reason (audited).

## Testing end to end (test mode)

Use provider test keys and test cards / UPI ids, e.g. Stripe CLI
`stripe listen --forward-to localhost:8000/api/billing/webhook/stripe` (put the printed
`whsec_...` in `STRIPE_WEBHOOK_SECRET`). The automated suite never touches the network.

## Legal

`docs/legal/terms.md`, `privacy.md` and `refunds.md` are templates that **must be reviewed
by a lawyer** (and the GST setup by a CA) before launch. `TERMS_VERSION` is stored with each
owner at sign-up; bump it when the terms change.
