# FAQ

**Does mebot come with an AI key?** No. You bring your own, or run Ollama locally for free.
See [providers](providers.md).

**What does it cost to run?** The server is one small container with SQLite. The real cost
is your AI provider's per-message price, which [limits](limits.md) cap. A portfolio bot on a
cheap model typically costs cents a day.

**Will it make things up about me?** It answers only from your profile, computes numbers
like years of experience on the server, and otherwise says it doesn't know and files the
question for you. Models can still slip; run the golden evals ([profile](profile.md)).

**Does it pretend to be me?** No. It is your assistant: it talks about you in the third
person and says it's an AI when asked.

**Can several people share one install?** Not yet: one install is one owner and one bot.

**Postgres?** SQLite is the default and plenty for this workload. `DATABASE_URL` takes other
SQLAlchemy URLs, but only SQLite is tested in this release.

**Can I turn off every outbound call?** Set `TELEMETRY=off`. mebot then contacts only your
AI provider, Telegram (if linked) and GitHub (during an import). See
[telemetry](telemetry.md).

**Where is my data?** In the data directory (`./data` with Docker). Back it up; see
[upgrading](upgrading.md) and [security](security.md).

**Why a single worker process?** Background jobs and in-memory limits assume one process,
and it is enough for this kind of traffic.

**Raspberry Pi?** Yes: images are published for `linux/arm64` as well as `linux/amd64`.
