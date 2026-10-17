import { useCallback, useEffect, useState } from "react";
import { useAdmin } from "./AdminLayout";
import { inputCls } from "./fields";
import { CONSENT_LABEL, WhatIsSent } from "./TelemetryText";
import { getTelemetry, saveTelemetry, type TelemetryStatus, type TelemetryView } from "../../lib/api";

const btn =
  "font-mono text-xs px-3 py-1.5 rounded border border-term-line2 text-term-fg hover:border-term-bright hover:text-term-bright disabled:opacity-50";
const primaryBtn =
  "font-mono text-xs px-3 py-1.5 rounded border border-term-bright text-term-bright bg-term-bright/10 hover:bg-term-bright/20 disabled:opacity-50";

const when = (iso: string) =>
  new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );

const TONE: Record<TelemetryStatus, string> = {
  registered: "text-term-bright",
  pending: "text-term-amber",
  unregister_pending: "text-term-amber",
  waiting_for_public_url: "text-term-amber",
  unavailable: "text-term-err",
  not_registered: "text-term-dim",
  off: "text-term-dim",
};

function statusText(v: TelemetryView): string {
  switch (v.status) {
    case "registered":
      return `Registered${v.registered_at ? ` on ${when(v.registered_at)}` : ""} as ${v.effective_email ?? "?"} for ${v.public_url ?? "your site"}.`;
    case "pending":
      return v.last_register_error
        ? `Registration not confirmed yet. The last attempt failed (${v.last_register_error}); mebot retries every 10 minutes.`
        : "Registration pending. mebot is contacting the registry.";
    case "waiting_for_public_url":
      return "Set PUBLIC_URL to register. mebot needs your site address first.";
    case "unregister_pending":
      return "Removing your registration. The registry has not confirmed yet; mebot keeps retrying until it does.";
    case "off":
      return "Telemetry is off by server setting (TELEMETRY=off). Nothing is sent to the registry.";
    case "unavailable":
      return "The install key (data/install.key) could not be read, so nothing is sent. Fix or remove the file and restart.";
    default:
      return "Not registered.";
  }
}

// Account page, "mebot project": consent to register, contact e-mail, status and the
// literal data that is sent.
export default function TelemetrySection() {
  const { toast } = useAdmin();
  const [view, setView] = useState<TelemetryView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<boolean | null>(null); // the value being confirmed
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState<"consent" | "email" | null>(null);

  const load = useCallback(() => {
    setError(null);
    getTelemetry()
      .then((v) => {
        setView(v);
        setEmail(v.update_contact_email ?? "");
      })
      .catch((e: Error) => setError(e.message || "Could not load these settings."));
  }, []);

  useEffect(load, [load]);

  async function apply(body: { consent?: boolean; update_contact_email?: string | null }, kind: "consent" | "email") {
    setBusy(kind);
    setError(null);
    try {
      const v = await saveTelemetry(body);
      setView(v);
      setEmail(v.update_contact_email ?? "");
      setConfirming(null);
      toast(kind === "consent" ? (v.consent ? "Registration requested" : "Registration removal requested") : "Contact e-mail saved");
    } catch (e) {
      setError((e as Error).message || "Could not save.");
    } finally {
      setBusy(null);
    }
  }

  if (!view) {
    return (
      <section aria-labelledby="acct-mebot-h" className="max-w-lg mb-8">
        <h2 id="acct-mebot-h" className="text-term-fg text-sm mb-1">
          mebot project
        </h2>
        {error ? (
          <p role="alert" className="text-term-err text-xs">
            {error}{" "}
            <button type="button" onClick={load} className="underline text-term-bright">
              Try again
            </button>
          </p>
        ) : (
          <p className="text-term-dim text-xs">loading…</p>
        )}
      </section>
    );
  }

  const off = view.telemetry === "off";
  const preview = view.last_heartbeat?.payload ?? view.payload_preview;
  const emailChanged = (view.update_contact_email ?? "") !== email.trim();
  return (
    <section aria-labelledby="acct-mebot-h" className="max-w-lg mb-8">
      <h2 id="acct-mebot-h" className="text-term-fg text-sm mb-1">
        mebot project
      </h2>
      <p className={`text-xs mb-3 ${TONE[view.status]}`} role="status">
        {statusText(view)}
      </p>
      {error && (
        <p role="alert" className="text-term-err text-xs mb-3">
          {error}
        </p>
      )}

      <div className="flex gap-2 items-start mb-2">
        <input
          id="acct-consent"
          type="checkbox"
          checked={view.consent}
          disabled={off || busy !== null}
          onChange={(e) => setConfirming(e.target.checked)}
          className="mt-1 accent-term-bright"
        />
        <label htmlFor="acct-consent" className="text-xs text-term-fg leading-relaxed">
          {CONSENT_LABEL}
        </label>
      </div>
      {confirming !== null && (
        <div role="group" aria-label="Confirm" className="border border-term-line2 rounded p-3 mb-3 text-xs">
          {confirming ? (
            <p className="text-term-fg mb-2">
              This registers <b>{view.effective_email ?? "your e-mail"}</b> and{" "}
              <b>{view.public_url ?? "your site URL (set PUBLIC_URL first)"}</b> with the mebot
              project, with version {view.update.current}. The maintainer is notified.
            </p>
          ) : (
            <p className="text-term-fg mb-2">
              This deletes your registration from the registry. Anonymous heartbeats continue
              unless the server sets TELEMETRY=off.
            </p>
          )}
          <div className="flex gap-2">
            <button type="button" className={primaryBtn} disabled={busy !== null} onClick={() => void apply({ consent: confirming }, "consent")}>
              {busy === "consent" ? "saving…" : confirming ? "Yes, register" : "Yes, remove registration"}
            </button>
            <button type="button" className={btn} onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="mb-3 max-w-sm">
        <label htmlFor="acct-contact" className="block text-xs text-term-dim mb-1">
          contact e-mail for mebot updates
        </label>
        <input
          id="acct-contact"
          type="email"
          value={email}
          disabled={off}
          placeholder={view.effective_email ?? ""}
          onChange={(e) => setEmail(e.target.value)}
          className={`${inputCls} border-term-line2 mb-1`}
        />
        <div className="text-term-dim text-xs mb-2">
          Leave empty to use your login e-mail.
        </div>
        <button
          type="button"
          className={btn}
          disabled={off || busy !== null || !emailChanged}
          onClick={() => void apply({ update_contact_email: email.trim() || null }, "email")}
        >
          {busy === "email" ? "saving…" : "save e-mail"}
        </button>
      </div>

      <dl className="text-xs grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 mb-3">
        <dt className="text-term-dim">telemetry</dt>
        <dd className="text-term-fg">{view.telemetry} <span className="text-term-dim">(server setting)</span></dd>
        <dt className="text-term-dim">registry</dt>
        <dd className="text-term-fg break-all">{view.registry_url}</dd>
        <dt className="text-term-dim">install id</dt>
        <dd className="text-term-fg">{view.install_id_prefix ? `${view.install_id_prefix}…` : "—"}</dd>
        <dt className="text-term-dim">last check</dt>
        <dd className="text-term-fg">{view.last_check_at ? when(view.last_check_at) : "never"}</dd>
        <dt className="text-term-dim">last heartbeat</dt>
        <dd className="text-term-fg">{view.last_heartbeat ? when(view.last_heartbeat.sent_at) : "never"}</dd>
      </dl>

      <details className="text-xs mb-2">
        <summary className="cursor-pointer text-term-bright">What's sent</summary>
        <div className="mt-2">
          <WhatIsSent registryUrl={view.registry_url} />
          {preview && !off && (
            <>
              <p className="text-term-dim mt-3 mb-1">
                {view.last_heartbeat ? "The last heartbeat, exactly as sent:" : "Nothing sent yet. The next heartbeat will contain exactly:"}
              </p>
              <pre className="border border-term-line rounded bg-term-bg p-2 overflow-x-auto text-term-fg">
                {JSON.stringify(preview, null, 2)}
              </pre>
            </>
          )}
        </div>
      </details>
      <a
        href={`${view.registry_url}/privacy`}
        target="_blank"
        rel="noreferrer"
        className="text-term-bright underline text-xs"
      >
        Registry privacy notice
      </a>
    </section>
  );
}
