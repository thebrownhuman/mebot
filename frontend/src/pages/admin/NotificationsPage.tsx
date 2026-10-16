import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import QRCode from "qrcode";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import { inputCls } from "../../components/admin/fields";
import {
  ApiError,
  createTelegramLink,
  getTelegram,
  patchTelegram,
  saveTelegramToken,
  sendTelegramTest,
  unlinkTelegram,
  type TelegramSettings,
  type TelegramToggles,
  type TelegramView,
} from "../../lib/api";

// Owner's Telegram setup: bot token, linking (deep link + QR), what to be told about,
// the daily digest, receive mode and the outbox's health.

const LINK_POLL_MS = 3000;
const LINK_POLL_MAX_MS = 10 * 60 * 1000; // link codes expire after 10 minutes

const TOGGLES: { key: keyof TelegramToggles; label: string }[] = [
  { key: "notify_new_session", label: "a new chat starts" },
  { key: "notify_every_question", label: "every question (noisy)" },
  { key: "notify_unanswered", label: "a question the bot couldn't answer (you can reply)" },
  { key: "notify_contact", label: "a recruiter leaves contact details" },
  { key: "notify_limits", label: "limits are hit or a leak is blocked" },
  { key: "daily_digest", label: "daily digest" },
];

const SETTING_KEYS: (keyof TelegramSettings)[] = [
  ...TOGGLES.map((t) => t.key),
  "digest_hour",
  "timezone",
  "mode",
];

const btn =
  "font-mono text-xs px-3 py-1.5 rounded border border-term-line2 text-term-fg hover:border-term-bright hover:text-term-bright disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright";
const primaryBtn =
  "font-mono text-xs px-3 py-1.5 rounded border border-term-bright text-term-bright bg-term-bright/10 hover:bg-term-bright/20 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright";

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

// Always offered: some browsers can't list zones, and ICU lists legacy names
// (Asia/Calcutta) where people look for the current ones (Asia/Kolkata).
const COMMON_ZONES = [
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "Africa/Lagos",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Australia/Sydney",
];

function timezones(current: string): string[] {
  let list: string[] = [];
  try {
    const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] };
    list = intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    list = [];
  }
  const all = new Set(["UTC", ...COMMON_ZONES, ...list, browserTimezone(), current]);
  return [...all].sort((a, b) => (a === "UTC" ? -1 : b === "UTC" ? 1 : a.localeCompare(b)));
}

function fmtTime(iso: string | null): string {
  if (!iso) return "never";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

function pickSettings(v: TelegramView): TelegramSettings {
  const out = {} as Record<string, unknown>;
  for (const k of SETTING_KEYS) out[k] = v[k];
  return out as unknown as TelegramSettings;
}

export default function NotificationsPage() {
  const { toast, setDirty } = useAdmin();
  const [view, setView] = useState<TelegramView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setView(await getTelegram());
      setLoadError(null);
    } catch (e) {
      setLoadError((e as Error).message || "Could not load Telegram settings.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loadError && !view) {
    return (
      <AdminSection title="Notifications">
        <p role="alert" className="text-term-err text-xs">
          {loadError}
        </p>
      </AdminSection>
    );
  }
  if (!view) {
    return (
      <AdminSection title="Notifications">
        <p className="text-term-dim text-xs">loading…</p>
      </AdminSection>
    );
  }

  return (
    <AdminSection
      title="Notifications"
      intro="Get a Telegram message when recruiters chat with your bot, and reply to questions it couldn't answer straight from Telegram."
    >
      {view.error && (
        <p role="alert" className="border border-term-err text-term-err rounded px-3 py-2 mb-4 text-xs">
          Telegram problem: {view.error}
        </p>
      )}
      <TokenSection view={view} onSaved={setView} toast={toast} />
      {view.configured && <LinkSection view={view} onChange={setView} reload={load} toast={toast} />}
      {view.configured && (
        <SettingsSection
          key={JSON.stringify(pickSettings(view))}
          view={view}
          onSaved={setView}
          toast={toast}
          setDirty={setDirty}
        />
      )}
      {view.configured && <OutboxSection view={view} />}
    </AdminSection>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border border-term-line rounded bg-term-panel/60 p-4 mb-4">
      <h2 className="text-term-fg text-sm mb-3">{title}</h2>
      {children}
    </section>
  );
}

function TokenSection({
  view,
  onSaved,
  toast,
}: {
  view: TelegramView;
  onSaved: (v: TelegramView) => void;
  toast: (m: string) => void;
}) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    if (!token.trim()) return setError("Paste the token from @BotFather.");
    setBusy(true);
    setError(null);
    try {
      onSaved(await saveTelegramToken(token));
      setToken("");
      toast("Bot token saved");
    } catch (e) {
      const fe = e instanceof ApiError ? e.details.find((d) => d.field === "bot_token") : undefined;
      setError(
        [(e as Error).message, fe && fe.message !== (e as Error).message ? fe.message : null]
          .filter(Boolean)
          .join(" — ") || "Could not save the token.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="1. Your Telegram bot">
      {view.configured && (
        <p className="text-xs text-term-fg mb-3">
          Bot <span className="text-term-bright">@{view.bot_username}</span> · token{" "}
          <span className="font-mono">••••{view.bot_token_last4}</span>
        </p>
      )}
      <details className="mb-3 text-xs text-term-dim">
        <summary className="cursor-pointer text-term-fg">How to create a bot with @BotFather</summary>
        <ol className="list-decimal pl-5 mt-2 space-y-1 leading-relaxed">
          <li>
            In Telegram, open{" "}
            <a
              href="https://t.me/BotFather"
              target="_blank"
              rel="noreferrer"
              className="underline text-term-bright"
            >
              @BotFather
            </a>{" "}
            and send <code>/newbot</code>.
          </li>
          <li>Pick a display name, then a username ending in “bot” (e.g. jane_mebot).</li>
          <li>BotFather replies with a token like <code>123456789:AAH…</code>. Paste it below.</li>
          <li>Keep the token secret. It's stored encrypted and never shown again in full.</li>
        </ol>
      </details>
      <form onSubmit={save} className="flex flex-wrap items-end gap-2">
        <div className="flex-1 min-w-[14rem]">
          <label htmlFor="tg-token" className="block text-xs text-term-dim mb-1">
            {view.configured ? "replace bot token" : "bot token"}
          </label>
          <input
            id="tg-token"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={token}
            maxLength={200}
            placeholder="123456789:AAH…"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "tg-token-error" : undefined}
            onChange={(e) => setToken(e.target.value)}
            className={`${inputCls} ${error ? "border-term-err" : "border-term-line2"}`}
          />
        </div>
        <button type="submit" disabled={busy} className={primaryBtn}>
          {busy ? "checking…" : "save token"}
        </button>
      </form>
      {error && (
        <div id="tg-token-error" className="text-term-err text-xs mt-1">
          {error}
        </div>
      )}
    </Card>
  );
}

function LinkSection({
  view,
  onChange,
  reload,
  toast,
}: {
  view: TelegramView;
  onChange: (v: TelegramView) => void;
  reload: () => Promise<void>;
  toast: (m: string) => void;
}) {
  const [link, setLink] = useState<string | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [busy, setBusy] = useState<"link" | "test" | "unlink" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const waitingSince = useRef(0);

  // While a link is shown, poll until the owner presses Start in Telegram.
  useEffect(() => {
    if (!link || view.linked) return;
    const t = setInterval(async () => {
      if (Date.now() - waitingSince.current > LINK_POLL_MAX_MS) {
        clearInterval(t);
        setTimedOut(true);
        return;
      }
      try {
        const v = await getTelegram();
        if (v.linked) {
          setLink(null);
          setQr(null);
          onChange(v);
          toast("Telegram linked");
        }
      } catch {
        // transient: keep polling
      }
    }, LINK_POLL_MS);
    return () => clearInterval(t);
  }, [link, view.linked, onChange, toast]);

  async function connect() {
    setBusy("link");
    setError(null);
    setTimedOut(false);
    try {
      const { deep_link } = await createTelegramLink();
      setLink(deep_link);
      waitingSince.current = Date.now();
      try {
        const svg = await QRCode.toString(deep_link, { type: "svg", margin: 1, width: 192 });
        setQr(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
      } catch {
        setQr(null); // the link still works without the QR code
      }
    } catch (e) {
      setError((e as Error).message || "Could not create a link.");
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    setBusy("test");
    setError(null);
    try {
      await sendTelegramTest();
      toast("Test message sent — check Telegram");
    } catch (e) {
      setError((e as Error).message || "Could not send a test message.");
    } finally {
      setBusy(null);
    }
  }

  async function unlink() {
    if (!window.confirm("Unlink Telegram? Your bot token is deleted and notifications stop.")) return;
    setBusy("unlink");
    setError(null);
    try {
      await unlinkTelegram();
      await reload();
      toast("Telegram unlinked");
    } catch (e) {
      setError((e as Error).message || "Could not unlink.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card title="2. Link your Telegram account">
      {error && (
        <p role="alert" className="text-term-err text-xs mb-2">
          {error}
        </p>
      )}
      {view.linked ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-term-bright text-xs mr-2">Linked ✓</span>
          <button type="button" onClick={test} disabled={busy !== null} className={btn}>
            {busy === "test" ? "sending…" : "send test"}
          </button>
          <button
            type="button"
            onClick={unlink}
            disabled={busy !== null}
            className={btn + " hover:!border-term-err hover:!text-term-err"}
          >
            {busy === "unlink" ? "unlinking…" : "unlink"}
          </button>
        </div>
      ) : link ? (
        <div className="flex flex-wrap gap-4 items-start">
          {qr && (
            <img
              src={qr}
              alt="QR code for the Telegram link"
              width={192}
              height={192}
              className="bg-white rounded p-1 w-40 h-40 sm:w-48 sm:h-48"
            />
          )}
          <div className="flex-1 min-w-[12rem] text-xs text-term-dim space-y-2">
            <p>Open this link on the phone or computer where you use Telegram, then press Start:</p>
            <a
              href={link}
              target="_blank"
              rel="noreferrer"
              className="block break-all underline text-term-bright"
            >
              {link.replace(/^https:\/\//, "").replace(/\?.*$/, "")}
            </a>
            {timedOut ? (
              <p className="text-term-amber">
                The link expired.{" "}
                <button type="button" onClick={connect} className="underline text-term-bright">
                  Get a new one
                </button>
              </p>
            ) : (
              <p role="status" aria-label="waiting for Telegram" className="flex items-center gap-2">
                <span
                  aria-hidden
                  className="inline-block w-3 h-3 rounded-full border-2 border-term-bright border-t-transparent animate-spin motion-reduce:animate-none"
                />
                waiting for you to press Start…
              </p>
            )}
          </div>
        </div>
      ) : (
        <button type="button" onClick={connect} disabled={busy !== null} className={primaryBtn}>
          {busy === "link" ? "creating link…" : "connect Telegram"}
        </button>
      )}
    </Card>
  );
}

function SettingsSection({
  view,
  onSaved,
  toast,
  setDirty,
}: {
  view: TelegramView;
  onSaved: (v: TelegramView) => void;
  toast: (m: string) => void;
  setDirty: (d: boolean) => void;
}) {
  const saved = useMemo(() => pickSettings(view), [view]);
  const [draft, setDraft] = useState<TelegramSettings>(saved);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const zones = useMemo(() => timezones(saved.timezone), [saved.timezone]);
  const browserTz = browserTimezone();

  const changed = useMemo(() => {
    const out: Partial<TelegramSettings> = {};
    for (const k of SETTING_KEYS) {
      if (draft[k] !== saved[k]) (out as Record<string, unknown>)[k] = draft[k];
    }
    return out;
  }, [draft, saved]);
  const dirty = Object.keys(changed).length > 0;

  useEffect(() => {
    setDirty(dirty);
    return () => setDirty(false);
  }, [dirty, setDirty]);

  function set<K extends keyof TelegramSettings>(k: K, v: TelegramSettings[K]) {
    setDraft((d) => ({ ...d, [k]: v }));
  }

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    if (!dirty) return;
    setBusy(true);
    setError(null);
    try {
      const v = await patchTelegram(changed);
      setDirty(false);
      onSaved(v);
      toast("Notification settings saved");
    } catch (e) {
      const details = e instanceof ApiError ? e.details.map((d) => `${d.field}: ${d.message}`) : [];
      setError([(e as Error).message, ...details].join(" — ") || "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="3. What to send">
      <form onSubmit={save}>
        <fieldset className="mb-4">
          <legend className="text-xs text-term-dim mb-2">Tell me when…</legend>
          <div className="space-y-2">
            {TOGGLES.map((t) => (
              <label key={t.key} className="flex items-start gap-2 text-xs text-term-fg">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={draft[t.key]}
                  onChange={(e) => set(t.key, e.target.checked)}
                />
                {t.label}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="grid gap-3 sm:grid-cols-2 mb-4">
          <div>
            <label htmlFor="tg-hour" className="block text-xs text-term-dim mb-1">
              digest hour
            </label>
            <select
              id="tg-hour"
              value={draft.digest_hour}
              disabled={!draft.daily_digest}
              onChange={(e) => set("digest_hour", Number(e.target.value))}
              className={`${inputCls} border-term-line2`}
            >
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>
                  {String(h).padStart(2, "0")}:00
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="tg-tz" className="block text-xs text-term-dim mb-1">
              timezone
            </label>
            <select
              id="tg-tz"
              value={draft.timezone}
              aria-describedby="tg-tz-hint"
              onChange={(e) => set("timezone", e.target.value)}
              className={`${inputCls} border-term-line2`}
            >
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
            <div id="tg-tz-hint" className="text-term-dim text-xs mt-1">
              {draft.timezone === browserTz ? (
                "Matches this browser."
              ) : (
                <button
                  type="button"
                  onClick={() => set("timezone", browserTz)}
                  className="underline text-term-bright"
                >
                  use this browser's timezone ({browserTz})
                </button>
              )}
            </div>
          </div>
        </div>
        <fieldset className="mb-4">
          <legend className="text-xs text-term-dim mb-2">How mebot receives your replies</legend>
          <label className="flex items-start gap-2 text-xs text-term-fg mb-1">
            <input
              type="radio"
              name="tg-mode"
              className="mt-0.5"
              checked={draft.mode === "polling"}
              onChange={() => set("mode", "polling")}
            />
            long polling (works anywhere, including localhost)
          </label>
          <label className="flex items-start gap-2 text-xs text-term-fg">
            <input
              type="radio"
              name="tg-mode"
              className="mt-0.5"
              checked={draft.mode === "webhook"}
              disabled={!view.webhook_available}
              aria-describedby="tg-mode-hint"
              onChange={() => set("mode", "webhook")}
            />
            webhook (instant; needs a public HTTPS address)
          </label>
          {!view.webhook_available && (
            <div id="tg-mode-hint" className="text-term-dim text-xs mt-1 pl-5">
              Set PUBLIC_URL on the server to enable webhooks.
            </div>
          )}
        </fieldset>
        {error && (
          <p role="alert" className="text-term-err text-xs mb-2">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy || !dirty} className={primaryBtn}>
          {busy ? "saving…" : "save settings"}
        </button>
      </form>
    </Card>
  );
}

function OutboxSection({ view }: { view: TelegramView }) {
  const o = view.outbox;
  const bad = o.failed > 0 || o.dead > 0;
  return (
    <Card title="Delivery">
      <ul aria-label="outbox health" className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <Stat label="pending" value={o.pending} />
        <Stat label="retrying" value={o.failed} warn={o.failed > 0} />
        <Stat label="dead" value={o.dead} warn={o.dead > 0} />
        <li className="border border-term-line rounded px-2 py-1.5">
          <span className="block text-term-dim">last sent</span>
          <span className="text-term-fg">{fmtTime(o.last_sent_at)}</span>
        </li>
      </ul>
      {bad && (
        <p className="text-term-amber text-xs mt-2">
          Some messages failed. Dead ones gave up after 6 tries — check the bot token and that
          you haven't blocked the bot.
        </p>
      )}
    </Card>
  );
}

function Stat({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <li className="border border-term-line rounded px-2 py-1.5">
      <span className="block text-term-dim">{label}</span>
      <span className={warn ? "text-term-err" : "text-term-fg"}>{value}</span>
    </li>
  );
}
