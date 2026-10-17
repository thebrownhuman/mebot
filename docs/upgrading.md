# Upgrading

1. **Back up the data directory** (`./data` next to `docker-compose.yml`). It holds the
   database, `secret.key` and `install.key`: that's everything.

       docker compose stop
       tar czf mebot-data-$(date +%F).tar.gz data

2. Pull and restart:

       docker compose pull && docker compose up -d

3. Migrations run automatically on start. Check `docker compose logs mebot` and
   `/api/health` (it reports the running version).

**Downgrades are not supported.** Migrations only go forward. To go back, restore the backup
taken before the upgrade and run the older image.

To pin a version instead of `latest`, put `MEBOT_VERSION=0.9.0` in `.env`; the compose file
reads it.

## 0.9.0

- **Single image.** One container serves the app, API, embed and widget loader on port 8000
  (published as 8080). The data directory layout is unchanged.
- **IP addresses are hashed.** Migration 0016 replaces stored IPs in the activity log and
  admin sessions with `HMAC-SHA256(SECRET_KEY, ip)`, in batches of 1,000 rows. It uses the
  install's existing `SECRET_KEY` / `secret.key`. The admin log API field is now `ip_hash`
  (a 12-character prefix) instead of `ip`.

### From the two-container compose (`deploy/docker-compose.yml`, before 0.9)

1. `cd deploy && docker compose down`
2. Back up `deploy/data/` (see above).
3. Move it next to the new compose file, e.g. `mkdir -p ~/mebot && mv deploy/data ~/mebot/data`
   (or point the new compose file's volume at the old path). On Linux also run
   `sudo chown -R 10001:10001 ~/mebot/data`.
4. Copy your `.env` next to the new `docker-compose.yml`. Drop `TRUST_PROXY=true` unless
   another reverse proxy sits in front, and set `CORS_ORIGINS` to the address you open.
5. `docker compose up -d` and open `http://localhost:8080`. You log in as before; no setup.

The old nginx layout lives on as an advanced example in `deploy/nginx/`.

### From the prototype (single-file `app.py`)

If the database was created by the old `app.py`, the first start renames its tables to
`legacy_*` (kept, not dropped) and copies the profile, sessions, messages and access log into
the new schema under a `default` bot. Back up the file first if you want a pristine copy.
