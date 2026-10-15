import { useEffect, useState } from "react";
import { Field, FormError } from "../../components/AuthForm";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import {
  ApiError,
  getLimits,
  getUsage,
  saveLimits,
  type Limits,
  type LimitsView,
  type Usage,
} from "../../lib/api";

// Owner controls for the public chat: rate limits, daily caps, pause and Turnstile,
// plus the last 7 days of usage.

type NumKey = Exclude<
  keyof Limits,
  "paused" | "paused_message" | "turnstile_enabled"
>;
type Draft = Record<NumKey, string> & { turnstile_enabled: boolean };

const NUM_FIELDS: {
  key: NumKey;
  label: string;
  hint: string;
  min: number;
  max: number;
}[] = [
  {
    key: "per_ip_per_minute",
    label: "messages per minute per visitor",
    hint: "Stops scripted floods. 1–120.",
    min: 1,
    max: 120,
  },
  {
    key: "per_ip_per_day",
    label: "messages per day per visitor",
    hint: "Per IP address; an office behind one IP shares it.",
    min: 1,
    max: 10000,
  },
  {
    key: "per_session_messages",
    label: "messages per conversation",
    hint: "Long chats cost more and invite jailbreaks.",
    min: 1,
    max: 1000,
  },
  {
    key: "sessions_per_ip_per_hour",
    label: "new chats per hour per visitor",
    hint: "Stops visitors dodging the per-conversation limit.",
    min: 1,
    max: 1000,
  },
  {
    key: "daily_message_cap",
    label: "total messages per day",
    hint: "Hard cap for everyone together; resets at 00:00 UTC.",
    min: 1,
    max: 100000,
  },
  {
    key: "daily_token_cap",
    label: "total tokens per day",
    hint: "Leave empty for no token cap. Your provider bills per token.",
    min: 1000,
    max: 100000000,
  },
  {
    key: "max_message_chars",
    label: "max characters per message",
    hint: "Longer messages are refused. 100–4000.",
    min: 100,
    max: 4000,
  },
  {
    key: "history_turns",
    label: "history turns sent to the AI",
    hint: "Earlier messages are left out of each request. 2–50.",
    min: 2,
    max: 50,
  },
];

const PRESETS: Record<string, Record<NumKey, number | null>> = {
  Strict: {
    per_ip_per_minute: 5,
    per_ip_per_day: 30,
    per_session_messages: 20,
    sessions_per_ip_per_hour: 5,
    daily_message_cap: 200,
    daily_token_cap: 100000,
    max_message_chars: 500,
    history_turns: 8,
  },
  Default: {
    per_ip_per_minute: 10,
    per_ip_per_day: 100,
    per_session_messages: 40,
    sessions_per_ip_per_hour: 10,
    daily_message_cap: 500,
    daily_token_cap: null,
    max_message_chars: 1000,
    history_turns: 12,
  },
  Generous: {
    per_ip_per_minute: 30,
    per_ip_per_day: 300,
    per_session_messages: 100,
    sessions_per_ip_per_hour: 30,
    daily_message_cap: 2000,
    daily_token_cap: null,
    max_message_chars: 2000,
    history_turns: 20,
  },
};

function toDraft(l: LimitsView): Draft {
  const d = { turnstile_enabled: l.turnstile_enabled } as Draft;
  for (const f of NUM_FIELDS)
    d[f.key] = l[f.key] == null ? "" : String(l[f.key]);
  return d;
}

function toBody(d: Draft): Partial<Limits> {
  const body: Partial<Limits> = { turnstile_enabled: d.turnstile_enabled };
  for (const f of NUM_FIELDS) {
    const v = d[f.key].trim();
    (body as Record<string, number | null>)[f.key] =
      v === "" ? null : Number(v);
  }
  return body;
}

const btn =
  "font-mono text-xs px-2.5 py-1.5 rounded border focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-50";

export default function LimitsPage() {
  const { setDirty, toast } = useAdmin();
  const [limits, setLimits] = useState<LimitsView | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [pausedMsg, setPausedMsg] = useState("");

  useEffect(() => {
    getLimits()
      .then((l) => {
        setLimits(l);
        setDraft(toDraft(l));
        setPausedMsg(l.paused_message ?? "");
      })
      .catch((e: Error) => setLoadError(e.message || "Could not load limits."));
    getUsage(7)
      .then(setUsage)
      .catch(() => setUsage({ days: [], top_visitors: [] }));
  }, []);

  function change(next: Draft) {
    setDraft(next);
    setDirty(true);
  }

  function applied(l: LimitsView) {
    setLimits(l);
    setDraft(toDraft(l));
    setPausedMsg(l.paused_message ?? "");
  }

  function showError(e: unknown) {
    if (e instanceof ApiError && e.details.length) {
      setFieldErrors(
        Object.fromEntries(e.details.map((d) => [d.field, d.message])),
      );
      setError("Please fix the highlighted fields.");
    } else {
      setError((e as Error).message || "Could not save.");
    }
  }

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    if (!draft) return;
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      applied(await saveLimits(toBody(draft)));
      setDirty(false);
      toast("Limits saved");
    } catch (e) {
      showError(e);
    } finally {
      setBusy(false);
    }
  }

  async function togglePause() {
    if (!limits) return;
    setBusy(true);
    setError(null);
    try {
      const l = await saveLimits({
        paused: !limits.paused,
        paused_message: pausedMsg.trim() || null,
      });
      setLimits(l);
      setPausedMsg(l.paused_message ?? "");
      toast(l.paused ? "Bot paused" : "Bot resumed");
    } catch (e) {
      showError(e);
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <AdminSection title="Limits">
        <p role="alert" className="text-term-err text-xs">
          {loadError}
        </p>
      </AdminSection>
    );
  }
  if (!limits || !draft) {
    return (
      <AdminSection title="Limits">
        <p className="text-term-dim text-xs">loading…</p>
      </AdminSection>
    );
  }

  return (
    <AdminSection
      title="Limits"
      intro="Every visitor message is a paid call to your AI provider. These limits cap what one visitor, and everyone together, can spend each day."
    >
      <div
        className={
          "border rounded-lg p-3 mb-5 " +
          (limits.paused
            ? "border-term-err bg-term-err/5"
            : "border-term-line2 bg-term-panel/80")
        }
      >
        <h2 className="text-term-fg text-sm mb-1">
          {limits.paused ? "The bot is paused" : "Emergency pause"}
        </h2>
        <p className="text-term-dim text-xs mb-3">
          {limits.paused
            ? "Visitors see the message below and no AI calls are made."
            : "Stops all chats instantly, without calling your AI provider."}
        </p>
        <Field
          id="lim-paused-message"
          label="message shown while paused (optional)"
          maxLength={500}
          value={pausedMsg}
          placeholder="The assistant is paused right now. Please try again later."
          onChange={(e) => setPausedMsg(e.target.value)}
          error={fieldErrors.paused_message}
        />
        <button
          type="button"
          onClick={togglePause}
          disabled={busy}
          className={
            btn +
            " text-sm px-4 py-2 " +
            (limits.paused
              ? "border-term-bright text-term-bright hover:bg-term-bright/10"
              : "border-term-err text-term-err hover:bg-term-err/10")
          }
        >
          {limits.paused ? "resume the bot" : "pause the bot"}
        </button>
      </div>

      <form onSubmit={save} noValidate>
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <span className="text-term-dim text-xs">presets:</span>
          {Object.entries(PRESETS).map(([name, p]) => (
            <button
              key={name}
              type="button"
              className={
                btn +
                " border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright"
              }
              onClick={() => {
                const next = { ...draft };
                for (const f of NUM_FIELDS)
                  next[f.key] = p[f.key] == null ? "" : String(p[f.key]);
                change(next);
              }}
            >
              {name}
            </button>
          ))}
        </div>
        <FormError message={error} />
        <div className="grid gap-x-4 sm:grid-cols-2">
          {NUM_FIELDS.map((f) => (
            <Field
              key={f.key}
              id={`lim-${f.key}`}
              label={f.label}
              type="number"
              inputMode="numeric"
              min={f.min}
              max={f.max}
              value={draft[f.key]}
              hint={f.hint}
              error={fieldErrors[f.key]}
              onChange={(e) => change({ ...draft, [f.key]: e.target.value })}
            />
          ))}
        </div>
        <div className="mb-4">
          <label className="flex items-center gap-2 text-xs text-term-fg">
            <input
              type="checkbox"
              checked={draft.turnstile_enabled}
              disabled={!limits.turnstile_available}
              aria-describedby="lim-turnstile-hint"
              onChange={(e) =>
                change({ ...draft, turnstile_enabled: e.target.checked })
              }
            />
            require Cloudflare Turnstile for new chats
          </label>
          <div id="lim-turnstile-hint" className="text-term-dim text-xs mt-1">
            {limits.turnstile_available
              ? "Visitors pass an invisible bot check before a chat starts."
              : "Set TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY on the server to enable this."}
          </div>
          {fieldErrors.turnstile_enabled && (
            <div className="text-term-err text-xs mt-1">
              {fieldErrors.turnstile_enabled}
            </div>
          )}
        </div>
        <button
          type="submit"
          disabled={busy}
          aria-busy={busy}
          className={
            btn +
            " text-sm px-4 py-2 border-term-bright text-term-bright hover:bg-term-bright/10"
          }
        >
          {busy ? "saving…" : "save limits"}
        </button>
      </form>

      <UsageTable usage={usage} />
    </AdminSection>
  );
}

function UsageTable({ usage }: { usage: Usage | null }) {
  return (
    <div className="mt-8">
      <h2 className="text-term-fg text-sm mb-2">Usage</h2>
      {usage === null && <p className="text-term-dim text-xs">loading…</p>}
      {usage && usage.days.length === 0 && (
        <p className="text-term-dim text-xs">No usage recorded yet.</p>
      )}
      {usage && usage.days.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <caption className="sr-only">Usage, last 7 days</caption>
            <thead>
              <tr className="text-term-dim text-left">
                <th scope="col" className="py-1 pr-3 font-normal">
                  date (UTC)
                </th>
                <th scope="col" className="py-1 pr-3 font-normal text-right">
                  messages
                </th>
                <th scope="col" className="py-1 pr-3 font-normal text-right">
                  tokens
                </th>
                <th scope="col" className="py-1 pr-3 font-normal text-right">
                  rate limited
                </th>
                <th scope="col" className="py-1 font-normal text-right">
                  leaks blocked
                </th>
              </tr>
            </thead>
            <tbody>
              {usage.days.map((d) => (
                <tr
                  key={d.date}
                  className="border-t border-term-line text-term-fg"
                >
                  <td className="py-1 pr-3">{d.date}</td>
                  <td className="py-1 pr-3 text-right">{d.messages}</td>
                  <td className="py-1 pr-3 text-right">
                    {d.tokens.toLocaleString("en-US")}
                    {d.tokens_estimated && (
                      <span
                        className="text-term-dim"
                        title="Provider did not report usage; estimated as characters / 4"
                      >
                        {" "}
                        (est.)
                      </span>
                    )}
                  </td>
                  <td className="py-1 pr-3 text-right">{d.rate_limited}</td>
                  <td className="py-1 text-right">{d.leak_blocked}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {usage && usage.top_visitors.length > 0 && (
        <div className="mt-4">
          <h3 className="text-term-dim text-xs mb-1">
            Top visitors (hashed IP, 7 days)
          </h3>
          <ul className="text-xs font-mono space-y-0.5">
            {usage.top_visitors.map((v) => (
              <li key={v.ip_hash} className="text-term-fg">
                <span>{v.ip_hash}</span>{" "}
                <span className="text-term-dim">· {v.messages} messages</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
