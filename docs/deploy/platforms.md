# Railway, Render and Fly.io

All three run the same image. Whatever the platform, mebot needs:

- **a persistent disk mounted at `/data`** (database, `secret.key`, `install.key`). Without
  one, every redeploy or restart starts from an empty install and you lose everything.
- **one instance.** Background jobs and in-memory limits assume a single process; don't
  scale horizontally.
- the env vars `PUBLIC_URL` and `CORS_ORIGINS` set to the public https address, plus
  `COOKIE_SECURE=true` and `TRUST_PROXY=true` (these platforms terminate TLS for you).
- `SETUP_TOKEN` until you've finished setup: the URL is public from the first second.

`SECRET_KEY` is optional (one is generated into `/data/secret.key`), but setting it on the
platform keeps it out of the disk backup.

## Railway

`deploy/railway/railway.json` builds the root `Dockerfile` and health-checks
`/api/health`. Create a service from the repo, then add a **Volume** mounted at `/data` in
the service settings (volumes can't be declared in `railway.json`), and the variables above.

## Render

`render.yaml` in the repo root is a Blueprint: a web service from the Dockerfile, a 1 GB disk
at `/data` and a generated `SECRET_KEY`. **Disks need a paid instance**; on the free plan the
filesystem is wiped on every deploy and restart, so data does not survive.

## Fly.io

```bash
fly launch --no-deploy --copy-config      # uses fly.toml from the repo; pick an app name
fly volumes create mebot_data --size 1 --region <region>
fly secrets set SETUP_TOKEN=$(openssl rand -hex 16)
fly deploy
```

`fly.toml` mounts the volume at `/data`, health-checks `/api/health` and keeps exactly one
machine (`fly scale count 1`). Set `PUBLIC_URL` / `CORS_ORIGINS` in `[env]` to your
`https://<app>.fly.dev` (or custom domain) address.
