# Telegram notifications

Get a Telegram message when recruiters chat with your bot, and answer the questions it
couldn't from Telegram — the reply shows up in the recruiter's open chat.

**Set up (about 2 minutes).**

1. In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name
   and a username ending in `bot`. BotFather replies with a token like `123456789:AAH…`.
2. In Admin → Notifications, paste the token and save. It's checked with Telegram,
   stored encrypted with your `SECRET_KEY`, and only its last 4 characters are shown again.
3. Press **Connect Telegram**, then open the link (or scan the QR code) and press
   **Start**. The page shows "Linked ✓" once Telegram confirms. Only that chat can
   receive notifications or send commands; the link code works once, for 10 minutes.
4. Pick what to be told about, the hour and timezone of the daily digest, and press
   **Send test** to check.

**What gets sent to Telegram.** Only what you need to act on: the recruiter's name
(as they typed it), their questions, the bot's "couldn't answer" notices, contact
details a recruiter chose to leave, limit / leak-guard alerts and daily counts. All
visitor text is HTML-escaped. Personal-topic questions are never sent (see *What mebot
will never discuss*). Never sent: IP addresses, your profile notes, the system
prompt or any API key. Telegram itself stores those messages like any other chat.

**Replying.** On a "couldn't answer" notice, press **Reply** (or reply to the message)
and type your answer. It's added to the recruiter's chat as "{your first name}
replied:" — their chat checks every 5 seconds while the tab is open, and the session
is remembered in their browser, so they see it when they come back. **Save to memory**
turns your answer into a learned fact (cleaned by the AI, then Approve / Edit / Reject;
see *How mebot learns*). Commands in the linked chat: `/status`, `/pause`, `/resume`,
`/today`, `/questions`, `/help`.

**Recruiter contact.** The chat has a "Leave my contact" button (also suggested after
an unanswered question). Entries appear in Admin → Contacts and, if enabled, in
Telegram. A hidden honeypot field and a 3-per-hour limit per visitor keep spam out.

**Polling vs webhook.** Long polling (default) works anywhere, including localhost:
mebot asks Telegram for new messages. A webhook is instant and lighter but needs
`PUBLIC_URL` set to a public https address; switch to it in Admin → Notifications.
Outgoing messages go through a queue (max one per second per chat, retries with
backoff, given up after 6 tries); the page shows pending / retrying / dead counts.
With several server processes, only one receives updates at a time (a database lease);
set `TELEGRAM_WORKERS=false` on processes that shouldn't run the background tasks.

**Troubleshooting.**

- *"Telegram rejected this token"* — copy it again from BotFather (`/mybots` → API
  Token); revoking it there invalidates the old one.
- *Never shows "Linked ✓"* — press Start in the chat the link opened; if 10 minutes
  passed, get a new link. Check that `TELEGRAM_WORKERS` isn't `false` on every process.
- *Webhook option greyed out* — set `PUBLIC_URL` and restart.
- *Webhook set but nothing arrives* — the address must be reachable from the internet
  over https with a valid certificate; switch back to polling to confirm the rest works.
- *Dead messages in the outbox* — you blocked the bot or the token was revoked; send a
  test after fixing it. Error text shown on the page never contains the token.
- *Changed `SECRET_KEY`* — the saved token can't be decrypted; paste it again.
