# Troubleshooting

**Container exits with "/data is not writable".** The image runs as uid 10001. On the host:
`sudo chown -R 10001:10001 ./data`, and check the volume isn't mounted `:ro`.

**Every page redirects to `/setup`.** No admin exists yet, so this is a fresh data directory.
If you expected your old data, the volume points at the wrong folder (see
[upgrading](upgrading.md)).

**Visitors see "assistant unavailable".** The provider call failed. Admin shows a banner with
the reason, and the log has `LLM_ERROR` with the provider and status code. Common causes: an
expired key, no credit, a retired model id, or Ollama unreachable from the container (use
`host.docker.internal`, not `localhost`).

**Admin asks to re-enter the API key after a move.** `SECRET_KEY` (or `secret.key`) changed,
so stored keys can't be decrypted. Restore the old `secret.key` from your backup, or re-enter
the keys.

**Forgot the admin password.** There is no web reset. On the server:

    docker compose exec mebot python -m mebot.cli reset-password --email you@example.com
    # from source: cd backend && python -m mebot.cli reset-password --email you@example.com

It prompts for a new password and signs out every session.

**Login says "too many attempts".** Login limits are in memory: wait 15 minutes or restart.

**Cookies don't stick behind HTTPS.** If a proxy terminates TLS, set `COOKIE_SECURE=true`,
and `TRUST_PROXY=true` only if mebot is reachable solely through that proxy.

**The widget doesn't appear.** The site isn't under Admin → Widget → Allowed sites, the
site's CSP blocks mebot, or the widget is off. The browser console shows a `[mebot]`
warning. See [widget](widget.md).

**Telegram never links, or the webhook stays silent.** See the list in
[telegram](telegram.md).

**Running with `--workers 2` or `WEB_CONCURRENCY`.** mebot is single-process by design:
background jobs and in-memory limits would run once per worker. The entrypoint keeps one
worker and prints a warning. Give the machine more CPU instead; one worker easily handles a
portfolio's traffic.

**Data gone after a redeploy on a hosting platform.** No persistent disk was mounted at
`/data`. See [platform deploys](deploy/platforms.md).
