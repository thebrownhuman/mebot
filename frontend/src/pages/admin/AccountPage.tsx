import { useEffect, useMemo, useState } from "react";
import { Field, FormError, SubmitButton } from "../../components/AuthForm";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import { inputCls } from "../../components/admin/fields";
import TelemetrySection from "../../components/admin/TelemetrySection";
import {
  changePassword,
  conversationExportUrl,
  deleteAllConversations,
  getAccount,
  saveAccount,
  type AccountSettings,
} from "../../lib/api";
import { browserTimezone, timezones } from "../../lib/timezones";

const MIN_PASSWORD = 10;
const FOREVER = "forever";

const btn =
  "font-mono text-xs px-3 py-1.5 rounded border border-term-line2 text-term-fg hover:border-term-bright hover:text-term-bright disabled:opacity-50";

// Timezone and conversation retention.
function Settings() {
  const { toast } = useAdmin();
  const [saved, setSaved] = useState<AccountSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tz, setTz] = useState("UTC");
  const [keep, setKeep] = useState("180");
  const [willDelete, setWillDelete] = useState<number | null>(null);
  const [busy, setBusy] = useState<"tz" | "keep" | null>(null);

  useEffect(() => {
    getAccount()
      .then((a) => {
        setSaved(a);
        setTz(a.timezone);
        setKeep(a.retention_days === null ? FOREVER : String(a.retention_days));
      })
      .catch((e: Error) => setError(e.message || "Could not load your settings."));
  }, []);

  // Preview how many conversations a shorter window removes, before it is saved.
  useEffect(() => {
    setWillDelete(null);
    if (!saved || keep === FOREVER || Number(keep) === saved.retention_days) return;
    let live = true;
    getAccount(Number(keep))
      .then((a) => live && setWillDelete(a.will_delete ?? 0))
      .catch(() => live && setWillDelete(null));
    return () => {
      live = false;
    };
  }, [keep, saved]);

  const zones = useMemo(() => timezones(saved?.timezone ?? "UTC"), [saved?.timezone]);
  const browserTz = browserTimezone();

  async function saveTz() {
    setBusy("tz");
    setError(null);
    try {
      setSaved(await saveAccount({ timezone: tz }));
      toast("Timezone saved");
    } catch (e) {
      setError((e as Error).message || "Could not save the timezone.");
    } finally {
      setBusy(null);
    }
  }

  async function saveKeep() {
    setBusy("keep");
    setError(null);
    try {
      setSaved(await saveAccount({ retention_days: keep === FOREVER ? null : Number(keep) }));
      toast("Retention saved");
    } catch (e) {
      setError((e as Error).message || "Could not save the retention setting.");
    } finally {
      setBusy(null);
    }
  }

  if (!saved) {
    return error ? (
      <p role="alert" className="text-term-err text-xs mb-6">
        {error}
      </p>
    ) : (
      <p className="text-term-dim text-xs mb-6">loading…</p>
    );
  }
  const keepChanged = (keep === FOREVER ? null : Number(keep)) !== saved.retention_days;
  return (
    <>
      {error && (
        <p role="alert" className="text-term-err text-xs mb-3">
          {error}
        </p>
      )}
      <section aria-labelledby="acct-tz-h" className="max-w-sm mb-8">
        <h2 id="acct-tz-h" className="text-term-fg text-sm mb-1">
          Timezone
        </h2>
        <p className="text-term-dim text-xs mb-3">
          Decides what counts as “today” on the dashboard, in the daily digest and in exports.
        </p>
        <label htmlFor="acct-tz" className="block text-xs text-term-dim mb-1">
          your timezone
        </label>
        <select
          id="acct-tz"
          value={tz}
          onChange={(e) => setTz(e.target.value)}
          className={`${inputCls} border-term-line2 mb-1`}
        >
          {zones.map((z) => (
            <option key={z} value={z}>
              {z}
            </option>
          ))}
        </select>
        <div className="text-term-dim text-xs mb-3">
          {tz === browserTz ? (
            "Matches this browser."
          ) : (
            <button
              type="button"
              onClick={() => setTz(browserTz)}
              className="underline text-term-bright"
            >
              use this browser's timezone ({browserTz})
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={saveTz}
          disabled={busy !== null || tz === saved.timezone}
          className={btn}
        >
          {busy === "tz" ? "saving…" : "save timezone"}
        </button>
      </section>

      <section aria-labelledby="acct-keep-h" className="max-w-sm mb-8">
        <h2 id="acct-keep-h" className="text-term-fg text-sm mb-1">
          Conversation retention
        </h2>
        <p className="text-term-dim text-xs mb-3">
          Conversations (messages, contact details and their activity log) older than this are
          deleted for good, once a day. Only counts are logged.
        </p>
        <label htmlFor="acct-keep" className="block text-xs text-term-dim mb-1">
          delete conversations older than
        </label>
        <select
          id="acct-keep"
          value={keep}
          onChange={(e) => setKeep(e.target.value)}
          className={`${inputCls} border-term-line2 mb-1`}
        >
          {saved.retention_choices.map((d) => (
            <option key={d} value={d}>
              {d} days
            </option>
          ))}
          <option value={FOREVER}>Keep forever</option>
        </select>
        <div role="status" className="text-xs mb-3 min-h-[1.25rem]">
          {willDelete !== null && keepChanged && (
            <span className={willDelete > 0 ? "text-term-amber" : "text-term-dim"}>
              {willDelete > 0
                ? `Will delete ${willDelete} existing ${willDelete === 1 ? "conversation" : "conversations"} at the next daily clean-up.`
                : "Nothing existing is older than that."}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={saveKeep}
          disabled={busy !== null || !keepChanged}
          className={btn}
        >
          {busy === "keep" ? "saving…" : "save retention"}
        </button>
      </section>
    </>
  );
}

// Export everything, or wipe it (type-to-confirm).
function YourData() {
  const { toast } = useAdmin();
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function wipe() {
    setBusy(true);
    setError(null);
    try {
      const r = await deleteAllConversations(confirm);
      setConfirm("");
      toast(
        `Deleted ${r.deleted_sessions} ${r.deleted_sessions === 1 ? "conversation" : "conversations"}`,
      );
    } catch (e) {
      setError((e as Error).message || "Could not delete the conversations.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="acct-data-h" className="max-w-sm mb-8">
      <h2 id="acct-data-h" className="text-term-fg text-sm mb-1">
        Your visitors' data
      </h2>
      <p className="text-term-dim text-xs mb-3">
        Download everything first if you want a copy:{" "}
        <a className="underline text-term-bright" href={conversationExportUrl({}, "csv")} download>
          all conversations (CSV)
        </a>
        {" · "}
        <a className="underline text-term-bright" href={conversationExportUrl({}, "json")} download>
          JSON
        </a>
        . Single conversations can be deleted on the Conversations page.
      </p>
      <div className="border border-term-err/60 rounded p-3">
        <h3 className="text-term-err text-xs mb-1">Delete all conversations now</h3>
        <p className="text-term-dim text-xs mb-2">
          Permanently removes every conversation, message and contact. This cannot be undone.
        </p>
        {error && (
          <p role="alert" className="text-term-err text-xs mb-2">
            {error}
          </p>
        )}
        <label htmlFor="acct-wipe" className="block text-xs text-term-dim mb-1">
          type DELETE to confirm
        </label>
        <input
          id="acct-wipe"
          value={confirm}
          autoComplete="off"
          onChange={(e) => setConfirm(e.target.value)}
          className={`${inputCls} border-term-line2 mb-2`}
        />
        <button
          type="button"
          onClick={wipe}
          disabled={busy || confirm !== "DELETE"}
          className="font-mono text-xs px-3 py-1.5 rounded border border-term-err text-term-err hover:bg-term-err/10 disabled:opacity-40"
        >
          {busy ? "deleting…" : "delete all conversations"}
        </button>
      </div>
    </section>
  );
}

export default function AccountPage() {
  const { me, toast } = useAdmin();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    setError(null);
    if (next.length < MIN_PASSWORD) return setError(`Use at least ${MIN_PASSWORD} characters.`);
    if (next !== confirm) return setError("Passwords do not match.");
    setBusy(true);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      toast("Password changed — other devices were signed out");
    } catch (e) {
      setError((e as Error).message || "Could not change password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AdminSection title="Account" intro={`Signed in as ${me.email}.`}>
      <Settings />
      <YourData />
      <TelemetrySection />
      <form onSubmit={submit} className="max-w-sm">
        <h2 className="text-term-fg text-sm mb-3">Change password</h2>
        <FormError message={error} />
        <Field
          id="acct-current"
          label="current password"
          type="password"
          autoComplete="current-password"
          required
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <Field
          id="acct-new"
          label="new password"
          type="password"
          autoComplete="new-password"
          required
          value={next}
          hint={`At least ${MIN_PASSWORD} characters.`}
          onChange={(e) => setNext(e.target.value)}
        />
        <Field
          id="acct-confirm"
          label="confirm new password"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <SubmitButton busy={busy}>change password</SubmitButton>
      </form>
    </AdminSection>
  );
}
