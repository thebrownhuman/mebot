# mebot registry: privacy

The registry (registry.shivanshmishra.in) receives three kinds of requests from mebot
installs. This file lists exactly what is stored. Nothing else is kept.

## Heartbeat (anonymous, on by default)

Sent about once a day unless the owner sets `TELEMETRY=off`.

| Stored | Example |
|---|---|
| `install_id` (first 16 bytes of SHA-256 of the install's public key) | `65b60673d6ed884bf01c2c222d82ada0` |
| public key | base64, 32 bytes |
| mebot version | `0.9.0` |
| mode | `single` |
| first seen / last seen (UTC) | `2026-10-17T10:00:00Z` |

**Not stored:** IP address, hostname, URL, e-mail, bot name, user agent, chat counts, or
any other usage data. The client IP is held in memory for a few seconds to rate-limit
abuse and is never written to disk or to logs. A random install key is not linked to a
person unless the owner registers (below).

## Registration (opt-in)

Only if the owner ticks the consent box in mebot (setup or Account page).

| Stored | Why |
|---|---|
| e-mail | so the maintainer can send security notices |
| site URL (the owner's `PUBLIC_URL`) | to know where mebot is used |
| bot name (optional) | context |
| mebot version, created/updated time | support |

Each registration pings the maintainer on Telegram (e-mail, site, version). The message
is stored in a local outbox until delivered, then deleted after 30 days.

## Unregistering

Unticking the consent box in mebot sends a signed `DELETE /v1/register`. The registration
row is **hard deleted** immediately. The anonymous heartbeat row stays, and goes away
with the 180-day purge below. mebot retries until the registry confirms the deletion.

To delete a registration without access to the install, e-mail the maintainer with the
address you registered; they delete the row by hand.

## Retention

- Installs not seen for **180 days** are deleted, together with any registration.
- Replay-protection nonces are kept for 10 minutes.
- Delivered or failed Telegram messages are deleted after 30 days.

## How requests are authenticated

Each install has an Ed25519 key pair. Requests are signed
(`method \n path \n timestamp \n sha256(body)`), checked for clock skew (5 minutes) and
replay, and the first key seen for an `install_id` is pinned. Nobody else can update or
delete someone's registration.

## Who sees the data

Only the maintainer (Shivansh Mishra), through the Telegram bot and the stats endpoint,
which returns aggregate counts only. Data is never sold or shared.
