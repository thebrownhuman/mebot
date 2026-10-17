# Privacy Policy — TEMPLATE

> **Must be reviewed by a lawyer before launch.** Written with India's DPDP Act 2023 and
> the EU/UK GDPR in mind, but it is a template, not legal advice. Replace every
> `[PLACEHOLDER]`.

Version: `2026-10`. Data fiduciary / controller: [OPERATOR LEGAL NAME], [ADDRESS].
Contact / grievance officer: [NAME, EMAIL].

## What we process

| Who | Data | Why | Basis |
| --- | --- | --- | --- |
| Owners | e-mail, password hash, terms version accepted | account, login, notices | contract |
| Owners | profile content you enter or import (resume, LinkedIn, GitHub) | to run your assistant | contract |
| Owners | your LLM provider API key (encrypted at rest) | to call the provider on your behalf | contract |
| Owners | subscription status, plan, provider customer/subscription ids, invoices (amount, period, provider invoice id, optional GSTIN) | billing, tax records | contract, legal obligation |
| Visitors | chat messages, optional name and contact details they submit | to answer them and pass messages to the owner | owner's legitimate interest / consent |
| Everyone | hashed IP (keyed HMAC, never the raw IP), rate-limit counters | abuse prevention | legitimate interest |

We do **not** receive card, bank or UPI details: payment providers collect them on their
own pages.

## Sub-processors
- **Your LLM provider** (chosen by you: e.g. OpenAI, Anthropic, Google, a local model) —
  receives visitor questions and your profile excerpts under *your* account and its terms.
- **Payment providers**: Razorpay (India) and/or Stripe — payments, invoices, receipts.
- **Telegram** — only if you connect it: notifications to you.
- **E-mail delivery**: [SMTP PROVIDER].
- **Hosting**: [HOSTING PROVIDER, REGION].

## Retention
- Conversations: per your setting (default 180 days), then deleted.
- Account deletion: offline at once, erased after 7 days. Invoices are kept for
  [8 years / as tax law requires] with links to the provider's invoice page removed. A keyed
  hash of your e-mail is kept so the free trial can't be reused.
- Webhook payloads from payment providers: stored without personal fields, cleared after
  30 days.

## Your rights
Access and export (Account → Export), correction (edit your profile), deletion (Account →
Delete), withdrawal of consent, grievance redressal and, under GDPR, objection,
restriction and complaint to your supervisory authority. Visitors can ask the owner, or
us at [EMAIL], to delete their conversation.

## Transfers
Data may be processed outside your country by the sub-processors above. [Describe
safeguards: SCCs, adequacy, DPDP transfer rules — lawyer to complete.]

## Children
Not intended for anyone under [18].

## Changes
We'll e-mail owners about material changes and bump the version above.
