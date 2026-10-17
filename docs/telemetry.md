# Telemetry & registration

mebot can talk to the **mebot registry** (`https://registry.shivanshmishra.in`, source in
[`registry/`](../registry/)) for two things: so the maintainer knows roughly how many installs
are alive, and so you hear about new versions and security advisories. Both are visible and
under your control.

**What is sent, exactly.**

1. *Anonymous heartbeat* (on by default). About once a day (plus a few minutes after start-up):

        {"install_id": "…", "public_key": "…", "version": "0.9.0", "mode": "single"}

   The id is a random key pair generated on first start (`install.key` in your data directory, `/data` in Docker; it never leaves your
   server; keep it out of backups you share). The registry stores those four values and the
   first/last time it saw you. No IP address, hostname, URL, e-mail or usage data. At the same
   time mebot fetches the latest version and advisories.
2. *Registration* (opt-in, off by default). Only if you tick **Register this install with the
   mebot project** in setup or under **Account → mebot project**: your contact e-mail
   (your login e-mail unless you enter another), your `PUBLIC_URL` and the mebot version.
   The maintainer is notified. It is re-sent when the e-mail, the site or the major version
   changes. Without `PUBLIC_URL` the status reads "waiting" until you set it.

Chats, your profile, contacts, API keys and everything else stay on your server. Requests
are signed with your install key, so nobody else can change or delete your registration.
The Account page shows the exact JSON of the last heartbeat, and the registry's
[privacy notice](../registry/PRIVACY.md) lists everything it stores.

**Turn it off.** Set `TELEMETRY=off` and restart: no heartbeat, registration or update check;
mebot makes no request to the registry at all (so no update banner either). Do this *after*
unticking registration if you were registered, because with telemetry off mebot can't delete
it for you; to remove a registration you can no longer reach, email the maintainer.

**Unregister.** Untick the box under Account → mebot project. mebot deletes the registration
at the registry; if the registry is unreachable it keeps retrying until the deletion is
confirmed (the status shows "removing your registration"). The anonymous heartbeat record
remains until it expires (180 days without a heartbeat).

**Updates.** With telemetry on, the admin panel shows "Update available" (dismiss it per
version) or a red, non-dismissible "Security advisory" while your version is affected.
Dev builds (such as `0.9.0-dev`) never show an update for their own release.

**Safety limits.** mebot only contacts `REGISTRY_URL` (default above; change it only to run
your own registry), follows no redirects, waits at most 5 seconds, reads at most 64 KB and
discards anything that doesn't match the expected shape. A registry outage never affects the
app. If you delete `install.key`, mebot creates a new identity on the next start and the
old registration is orphaned (the registry purges it after 180 days); unregister first.
