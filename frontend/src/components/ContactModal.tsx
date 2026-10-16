import { useEffect, useRef, useState } from "react";
import { ApiError, leaveContact } from "../lib/api";

// "Leave my contact": a recruiter shares their details with the owner (POST /api/contact).

const NOTE_MAX = 1000;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const inputCls =
  "w-full bg-term-bg border rounded text-term-fg font-mono text-sm px-3 py-2 outline-none focus:border-term-bright";

type Values = { name: string; email: string; company: string; role: string; note: string };
type Errors = Partial<Record<keyof Values, string>>;

export default function ContactModal({
  ownerName,
  sessionId,
  onClose,
}: {
  ownerName: string;
  sessionId: string | null;
  onClose: () => void;
}) {
  const [v, setV] = useState<Values>({ name: "", email: "", company: "", role: "", note: "" });
  const [website, setWebsite] = useState(""); // honeypot
  const [errors, setErrors] = useState<Errors>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const firstRef = useRef<HTMLInputElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    firstRef.current?.focus();
    return () => {
      (opener.current as HTMLElement | null)?.focus?.();
    };
  }, []);

  function set(k: keyof Values, val: string) {
    setV((x) => ({ ...x, [k]: val }));
  }

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    const errs: Errors = {};
    if (!v.name.trim()) errs.name = "Enter your name.";
    if (!EMAIL_RE.test(v.email.trim())) errs.email = "Enter a valid email address.";
    setErrors(errs);
    setError(null);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const body: Record<string, string> = { name: v.name.trim(), email: v.email.trim() };
      if (sessionId) body.session_id = sessionId;
      for (const k of ["company", "role", "note"] as const) {
        if (v[k].trim()) body[k] = v[k].trim();
      }
      if (website) body.website = website;
      await leaveContact(body as never);
      setDone(true);
    } catch (e) {
      if (e instanceof ApiError && e.details.length) {
        const fe: Errors = {};
        for (const d of e.details) if (d.field in v) fe[d.field as keyof Values] = d.message;
        setErrors(fe);
      }
      setError((e as Error).message || "Could not send your details.");
    } finally {
      setBusy(false);
    }
  }

  const field = (
    k: keyof Values,
    label: string,
    props: React.ComponentPropsWithRef<"input"> = {},
  ) => (
    <div className="mb-3">
      <label htmlFor={`contact-${k}`} className="block text-xs text-term-dim mb-1">
        {label}
      </label>
      <input
        id={`contact-${k}`}
        value={v[k]}
        maxLength={k === "email" ? 254 : k === "name" ? 120 : 200}
        aria-invalid={errors[k] ? true : undefined}
        aria-describedby={errors[k] ? `contact-${k}-error` : undefined}
        onChange={(e) => set(k, e.target.value)}
        className={`${inputCls} ${errors[k] ? "border-term-err" : "border-term-line2"}`}
        {...props}
      />
      {errors[k] && (
        <div id={`contact-${k}-error`} className="text-term-err text-xs mt-1">
          {errors[k]}
        </div>
      )}
    </div>
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 p-0 sm:p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="contact-title"
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
        className="relative w-full sm:max-w-md max-h-[100dvh] overflow-y-auto border border-term-line bg-term-panel rounded-t-lg sm:rounded-lg px-4 py-4 font-mono"
      >
        <div className="flex items-start gap-3 mb-3">
          <h2 id="contact-title" className="flex-1 text-term-bright text-sm">
            Leave your contact for {ownerName}
          </h2>
          <button
            type="button"
            aria-label="close"
            onClick={onClose}
            className="text-term-dim hover:text-term-fg text-xs px-2 py-1 rounded border border-term-line2"
          >
            ✕
          </button>
        </div>
        {done ? (
          <div role="status" className="text-xs text-term-fg">
            <p className="mb-3">Thanks — {ownerName} will get back to you by email.</p>
            <button
              type="button"
              onClick={onClose}
              className="font-mono text-xs px-3 py-1.5 rounded border border-term-bright text-term-bright"
            >
              back to the chat
            </button>
          </div>
        ) : (
          <form onSubmit={submit} noValidate>
            {error && (
              <p role="alert" className="text-term-err text-xs mb-3">
                {error}
              </p>
            )}
            {field("name", "name (required)", { ref: firstRef, autoComplete: "name", required: true })}
            {field("email", "email (required)", {
              type: "email",
              autoComplete: "email",
              required: true,
            })}
            <div className="grid gap-x-3 sm:grid-cols-2">
              {field("company", "company", { autoComplete: "organization" })}
              {field("role", "role", { autoComplete: "organization-title" })}
            </div>
            <div className="mb-3">
              <label htmlFor="contact-note" className="block text-xs text-term-dim mb-1">
                note
              </label>
              <textarea
                id="contact-note"
                rows={3}
                maxLength={NOTE_MAX}
                value={v.note}
                aria-describedby="contact-note-count"
                onChange={(e) => set("note", e.target.value)}
                className={`${inputCls} border-term-line2 resize-y`}
              />
              <div id="contact-note-count" className="text-term-dim text-[11px] text-right">
                {v.note.length}/{NOTE_MAX}
              </div>
            </div>
            {/* Honeypot: invisible to people, filled in by form bots. */}
            <div aria-hidden="true" className="absolute -left-[9999px] w-px h-px overflow-hidden">
              <label htmlFor="contact-website">website</label>
              <input
                id="contact-website"
                name="website"
                tabIndex={-1}
                autoComplete="off"
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
              />
            </div>
            <p className="text-term-dim text-xs mb-3">
              Your details are shared only with {ownerName}.
            </p>
            <button
              type="submit"
              disabled={busy}
              className="font-mono text-xs px-3 py-1.5 rounded border border-term-bright text-term-bright bg-term-bright/10 hover:bg-term-bright/20 disabled:opacity-50"
            >
              {busy ? "sending…" : "send my details"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
