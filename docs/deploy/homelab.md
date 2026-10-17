# Homelab / VPS with Docker Compose

Any Linux box with Docker works, including a Raspberry Pi 4/5 (arm64).

```bash
mkdir -p ~/mebot && cd ~/mebot
curl -O https://raw.githubusercontent.com/thebrownhuman/mebot/main/docker-compose.yml
mkdir data && sudo chown -R 10001:10001 data   # the container runs as uid 10001
docker compose up -d
```

Open `http://<server>:8080` and finish setup. If the box is reachable from the internet
before you finish, set `SETUP_TOKEN` first (see [configuration](../configuration.md)).

## Putting it on a domain

mebot speaks plain http on port 8000 inside the container. Terminate TLS in front of it and
tell mebot so: in `.env` next to the compose file set

```dotenv
PUBLIC_URL=https://bot.example.com
CORS_ORIGINS=https://bot.example.com
COOKIE_SECURE=true
TRUST_PROXY=true          # only if mebot is reachable solely through the proxy
```

Then `docker compose up -d` again.

### Caddy

```caddyfile
bot.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Caddy gets the certificate itself. Bind mebot to localhost so it's only reachable through
Caddy: change the port line to `"127.0.0.1:8080:8000"`.

### Cloudflare Tunnel (no open ports)

```bash
cloudflared tunnel create mebot
cloudflared tunnel route dns mebot bot.example.com
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: mebot
credentials-file: /home/you/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: bot.example.com
    service: http://localhost:8080
  - service: http_status:404
```

Run `cloudflared tunnel run mebot` (or install it as a service). With a tunnel, mebot sees
requests from `cloudflared`, so `TRUST_PROXY=true` is right.

## Backups

Everything lives in `./data`: `mebot.db`, `secret.key`, `install.key`. A nightly cron job:

```bash
# crontab -e
15 3 * * * cd ~/mebot && sqlite3 data/mebot.db ".backup data/backup.db" && \
  tar czf ~/backups/mebot-$(date +\%F).tar.gz -C data backup.db secret.key install.key && \
  rm data/backup.db
```

`sqlite3 .backup` takes a consistent copy while mebot is running. Keep backups private: with
`secret.key` they can decrypt your stored API keys. To restore, stop the container, put the
files back in `data/` (renaming `backup.db` to `mebot.db`) and start it again.

## Ollama on the same box

Either keep Ollama on the host (the compose file maps `host.docker.internal`) or start the
bundled one with `docker compose --profile ollama up -d`. See [providers](../providers.md).
