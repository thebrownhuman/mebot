import { useEffect, useMemo, useState } from "react";
import { Field, FormError } from "../../components/AuthForm";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import {
  ApiError,
  getWidgetSettings,
  getWidgetSnippets,
  saveWidgetSettings,
  type WidgetSettings,
  type WidgetSnippets,
  type WidgetUpdate,
} from "../../lib/api";

// Embed the chat on the owner's own sites: look, allowed sites, snippets, live preview.

export const MAX_ORIGINS = 20;
export const MAX_QUESTIONS = 6;
const MAX_QUESTION_CHARS = 80;
const HEX = /^#[0-9a-f]{6}$/i;

// Same rules as the server (mebot/widget/origins.py); the server has the final say.
export function checkOrigin(raw: string): { origin: string } | { error: string } {
  const m = raw.trim().toLowerCase().match(/^(https?):\/\/([^/?#@:\s]+)(?::(\d{1,5}))?\/?$/);
  if (!m) return { error: "Use https://your-site.com (no path)." };
  const [, scheme, host, port] = m;
  const label = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?";
  if (!new RegExp(`^(?:\\*\\.)?${label}(?:\\.${label})*$`).test(host)) return { error: "That host isn't valid." };
  if (host.startsWith("*.") && host.split(".").length < 3) return { error: "Use a wildcard like https://*.example.com." };
  const local = host === "localhost" || host === "127.0.0.1";
  if (scheme === "http" && !local) return { error: "https is required (http only for localhost)." };
  let out = `${scheme}://${host}`;
  if (port) {
    const n = Number(port);
    if (n < 1 || n > 65535) return { error: "That port isn't valid." };
    if (n !== (scheme === "https" ? 443 : 80)) out += `:${n}`;
  }
  return { origin: out };
}

type Draft = {
  enabled: boolean;
  primary_color: string;
  theme: WidgetSettings["theme"];
  position: WidgetSettings["position"];
  title: string;
  avatar_url: string;
  launcher_label: string;
  suggested_questions: string[];
  show_orb: boolean;
  auto_open: string;
  allowed_origins: string[];
};

function toDraft(w: WidgetSettings): Draft {
  return {
    enabled: w.enabled,
    primary_color: w.primary_color,
    theme: w.theme,
    position: w.position,
    title: w.title ?? "",
    avatar_url: w.avatar_url ?? "",
    launcher_label: w.launcher_label ?? "",
    suggested_questions: w.suggested_questions,
    show_orb: w.show_orb,
    auto_open: w.auto_open_seconds == null ? "" : String(w.auto_open_seconds),
    allowed_origins: w.allowed_origins,
  };
}

function toBody(d: Draft): WidgetUpdate {
  return {
    enabled: d.enabled,
    primary_color: d.primary_color.toLowerCase(),
    theme: d.theme,
    position: d.position,
    title: d.title.trim() || null,
    avatar_url: d.avatar_url.trim() || null,
    launcher_label: d.launcher_label.trim() || null,
    suggested_questions: d.suggested_questions.map((q) => q.trim()).filter(Boolean),
    show_orb: d.show_orb,
    auto_open_seconds: d.auto_open.trim() === "" ? null : Number(d.auto_open),
    allowed_origins: d.allowed_origins,
  };
}

function validate(d: Draft): Record<string, string> {
  const e: Record<string, string> = {};
  if (!HEX.test(d.primary_color)) e.primary_color = "Use a hex colour like #0f766e.";
  if (d.auto_open.trim() !== "") {
    const n = Number(d.auto_open);
    if (!Number.isInteger(n) || n < 5 || n > 120) e.auto_open_seconds = "5–120 seconds, or empty for never.";
  }
  if (d.avatar_url.trim() && !/^https:\/\/\S+$/i.test(d.avatar_url.trim())) e.avatar_url = "Use an https:// image URL.";
  d.suggested_questions.forEach((q, i) => {
    if (q.trim().length > MAX_QUESTION_CHARS) e[`suggested_questions.${i}`] = `Max ${MAX_QUESTION_CHARS} characters.`;
  });
  return e;
}

const btn =
  "font-mono text-xs px-2.5 py-1.5 min-h-[32px] rounded border focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-50";
const ghost = btn + " border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright";
const select =
  "w-full bg-term-bg border border-term-line2 rounded text-term-fg font-mono text-sm px-3 py-2 outline-none focus:border-term-bright";

export default function WidgetPage() {
  const { setDirty, toast } = useAdmin();
  const [saved, setSaved] = useState<WidgetSettings | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [snippets, setSnippets] = useState<WidgetSnippets | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [newOrigin, setNewOrigin] = useState("");
  const [originError, setOriginError] = useState<string | null>(null);
  const [confirmAny, setConfirmAny] = useState(false);

  useEffect(() => {
    getWidgetSettings()
      .then((w) => {
        setSaved(w);
        setDraft(toDraft(w));
      })
      .catch((e: Error) => setLoadError(e.message || "Could not load widget settings."));
    getWidgetSnippets()
      .then(setSnippets)
      .catch(() => setSnippets(null));
  }, []);

  function change(next: Partial<Draft>) {
    setDraft((d) => (d ? { ...d, ...next } : d));
    setDirty(true);
  }

  function showError(e: unknown) {
    if (e instanceof ApiError && e.details.length) {
      setFieldErrors(Object.fromEntries(e.details.map((d) => [d.field, d.message])));
      setError("Please fix the highlighted fields.");
    } else {
      setError((e as Error).message || "Could not save.");
    }
  }

  // Toggling "any site" saves at once but keeps other unsaved edits in the form.
  async function put(body: WidgetUpdate, done: string, resetDraft = true) {
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      const w = await saveWidgetSettings(body);
      setSaved(w);
      if (resetDraft) {
        setDraft(toDraft(w));
        setDirty(false);
      }
      toast(done);
      return true;
    } catch (e) {
      showError(e);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    if (!draft) return;
    const errs = validate(draft);
    if (Object.keys(errs).length) {
      setFieldErrors(errs);
      setError("Please fix the highlighted fields.");
      return;
    }
    await put(toBody(draft), "Widget saved");
  }

  function addOrigin() {
    if (!draft) return;
    const r = checkOrigin(newOrigin);
    if ("error" in r) return setOriginError(r.error);
    if (draft.allowed_origins.includes(r.origin)) return setOriginError("Already on the list.");
    if (draft.allowed_origins.length >= MAX_ORIGINS) return setOriginError(`At most ${MAX_ORIGINS} sites.`);
    change({ allowed_origins: [...draft.allowed_origins, r.origin] });
    setNewOrigin("");
    setOriginError(null);
  }

  function moveQuestion(i: number, by: number) {
    if (!draft) return;
    const qs = draft.suggested_questions.slice();
    const j = i + by;
    if (j < 0 || j >= qs.length) return;
    [qs[i], qs[j]] = [qs[j], qs[i]];
    change({ suggested_questions: qs });
  }

  // Preview reflects unsaved colour/position live; other settings after Save.
  const previewSrc = useMemo(() => {
    if (!draft) return "";
    const q = new URLSearchParams({ open: "1", position: draft.position });
    if (HEX.test(draft.primary_color)) q.set("color", draft.primary_color.toLowerCase());
    return `/widget-test?${q}`;
  }, [draft?.primary_color, draft?.position]); // eslint-disable-line react-hooks/exhaustive-deps
  const [previewUrl, setPreviewUrl] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setPreviewUrl(previewSrc), 400);
    return () => clearTimeout(t);
  }, [previewSrc, saved]);

  if (loadError) {
    return (
      <AdminSection title="Widget">
        <p role="alert" className="text-term-err text-xs">
          {loadError}
        </p>
      </AdminSection>
    );
  }
  if (!saved || !draft) {
    return (
      <AdminSection title="Widget">
        <p className="text-term-dim text-xs">loading…</p>
      </AdminSection>
    );
  }

  const n = saved.allowed_origins.length;
  const status = !saved.enabled
    ? "Widget is off: embeds show “unavailable”."
    : saved.allow_any_origin
      ? "Widget allowed on any site."
      : n === 0
        ? "No sites allowed yet: the widget only works on this install's own pages."
        : `Widget allowed on ${n} site${n === 1 ? "" : "s"}.`;

  return (
    <AdminSection
      title="Widget"
      intro="Put the chat on your own website as a floating bubble or an inline panel. Only the sites you list here can show it."
    >
      <p
        role="status"
        className={
          "border rounded px-3 py-2 mb-5 text-xs " +
          (saved.needs_origins || saved.allow_any_origin
            ? "border-term-amber text-term-amber"
            : "border-term-line2 text-term-dim")
        }
      >
        {status}
      </p>

      <form onSubmit={save} noValidate>
        <FormError message={error} />

        <h2 className="text-term-fg text-sm mb-2">Allowed sites</h2>
        <p className="text-term-dim text-xs mb-2">
          e.g. https://shivansh.dev or https://*.shivansh.dev (one subdomain level). https only; http just for
          localhost.
        </p>
        <ul className="mb-2 space-y-1.5" aria-label="Allowed sites">
          {draft.allowed_origins.map((o) => (
            <li key={o} className="flex items-center gap-2 border border-term-line2 rounded px-3 py-1.5 text-sm">
              <span className="flex-1 min-w-0 truncate font-mono text-term-fg">{o}</span>
              <button
                type="button"
                className={ghost}
                aria-label={`Remove ${o}`}
                onClick={() => change({ allowed_origins: draft.allowed_origins.filter((x) => x !== o) })}
              >
                remove
              </button>
            </li>
          ))}
          {draft.allowed_origins.length === 0 && <li className="text-term-dim text-xs">No sites yet.</li>}
        </ul>
        <div className="flex gap-2 items-start mb-1">
          <div className="flex-1 min-w-0">
            <Field
              id="widget-new-origin"
              label="add a site"
              value={newOrigin}
              placeholder="https://your-site.com"
              inputMode="url"
              error={originError ?? fieldErrors.allowed_origins ?? fieldErrors["allowed_origins.0"]}
              onChange={(e) => {
                setNewOrigin(e.target.value);
                setOriginError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addOrigin();
                }
              }}
            />
          </div>
          <button type="button" className={ghost + " mt-5"} onClick={addOrigin}>
            add
          </button>
        </div>

        <div className={"border rounded-lg p-3 mb-6 " + (saved.allow_any_origin ? "border-term-err bg-term-err/5" : "border-term-line2")}>
          <h3 className="text-term-fg text-sm mb-1">Allow any site</h3>
          <p className="text-term-dim text-xs mb-2">
            Anyone could paste your snippet on their site and chat on your API key. Only for testing.
          </p>
          {saved.allow_any_origin ? (
            <button
              type="button"
              disabled={busy}
              className={btn + " border-term-bright text-term-bright"}
              onClick={() => void put({ allow_any_origin: false }, "Only listed sites allowed", false)}
            >
              turn off
            </button>
          ) : confirmAny ? (
            <div role="alertdialog" aria-label="Confirm allow any site" className="flex flex-wrap items-center gap-2">
              <span className="text-term-err text-xs">Allow any website to embed your chat?</span>
              <button
                type="button"
                disabled={busy}
                className={btn + " border-term-err text-term-err hover:bg-term-err/10"}
                onClick={async () => {
                  if (await put({ allow_any_origin: true, confirm_any_origin: true }, "Any site allowed", false)) setConfirmAny(false);
                }}
              >
                yes, allow any site
              </button>
              <button type="button" className={ghost} onClick={() => setConfirmAny(false)}>
                cancel
              </button>
            </div>
          ) : (
            <button type="button" className={btn + " border-term-err text-term-err"} onClick={() => setConfirmAny(true)}>
              allow any site…
            </button>
          )}
        </div>

        <h2 className="text-term-fg text-sm mb-3">Look</h2>
        <div className="grid gap-x-4 sm:grid-cols-2">
          <div className="mb-4">
            <label htmlFor="widget-color" className="block text-xs text-term-dim mb-1">
              brand colour
            </label>
            <div className="flex gap-2">
              <input
                type="color"
                aria-label="pick colour"
                value={HEX.test(draft.primary_color) ? draft.primary_color : "#0f766e"}
                onChange={(e) => change({ primary_color: e.target.value })}
                className="h-10 w-12 shrink-0 bg-term-bg border border-term-line2 rounded"
              />
              <input
                id="widget-color"
                value={draft.primary_color}
                maxLength={7}
                aria-invalid={Boolean(fieldErrors.primary_color)}
                onChange={(e) => change({ primary_color: e.target.value.trim() })}
                className={select + (fieldErrors.primary_color ? " border-term-err" : "")}
              />
            </div>
            {fieldErrors.primary_color && (
              <div role="alert" className="text-term-err text-xs mt-1">
                {fieldErrors.primary_color}
              </div>
            )}
          </div>
          <div className="mb-4">
            <label htmlFor="widget-theme" className="block text-xs text-term-dim mb-1">
              theme
            </label>
            <select id="widget-theme" className={select} value={draft.theme} onChange={(e) => change({ theme: e.target.value as Draft["theme"] })}>
              <option value="auto">auto (follow visitor)</option>
              <option value="light">light</option>
              <option value="dark">dark</option>
            </select>
          </div>
          <div className="mb-4">
            <label htmlFor="widget-position" className="block text-xs text-term-dim mb-1">
              bubble position
            </label>
            <select
              id="widget-position"
              className={select}
              value={draft.position}
              onChange={(e) => change({ position: e.target.value as Draft["position"] })}
            >
              <option value="right">bottom right</option>
              <option value="left">bottom left</option>
            </select>
          </div>
          <Field
            id="widget-title"
            label="title (optional)"
            maxLength={60}
            value={draft.title}
            placeholder="Defaults to “{first name}'s assistant”"
            error={fieldErrors.title}
            onChange={(e) => change({ title: e.target.value })}
          />
          <Field
            id="widget-launcher"
            label="bubble label (optional)"
            maxLength={40}
            value={draft.launcher_label}
            placeholder="Ask about me"
            error={fieldErrors.launcher_label}
            onChange={(e) => change({ launcher_label: e.target.value })}
          />
          <Field
            id="widget-avatar"
            label="avatar image URL (optional)"
            maxLength={500}
            inputMode="url"
            value={draft.avatar_url}
            placeholder="https://…/me.jpg"
            error={fieldErrors.avatar_url}
            onChange={(e) => change({ avatar_url: e.target.value })}
          />
          <Field
            id="widget-auto-open"
            label="auto-open after (seconds)"
            type="number"
            inputMode="numeric"
            min={5}
            max={120}
            value={draft.auto_open}
            hint="Empty = never. Opens once per visit."
            error={fieldErrors.auto_open_seconds}
            onChange={(e) => change({ auto_open: e.target.value })}
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-term-fg mb-1">
          <input type="checkbox" checked={draft.show_orb} onChange={(e) => change({ show_orb: e.target.checked })} />
          show the 3D orb
        </label>
        <p className="text-term-dim text-xs mb-4 ml-6">Adds ~220 KB to the chat; loaded only when on.</p>
        <label className="flex items-center gap-2 text-xs text-term-fg mb-6">
          <input type="checkbox" checked={draft.enabled} onChange={(e) => change({ enabled: e.target.checked })} />
          widget on
        </label>

        <h2 className="text-term-fg text-sm mb-1">Suggested questions</h2>
        <p className="text-term-dim text-xs mb-2">
          Shown as buttons before the first message. Up to {MAX_QUESTIONS}, {MAX_QUESTION_CHARS} characters each.
        </p>
        <ol className="mb-2 space-y-2" aria-label="Suggested questions">
          {draft.suggested_questions.map((q, i) => (
            <li key={i} className="flex items-start gap-1.5">
              <div className="flex-1 min-w-0">
                <input
                  aria-label={`Question ${i + 1}`}
                  value={q}
                  maxLength={MAX_QUESTION_CHARS}
                  onChange={(e) => {
                    const qs = draft.suggested_questions.slice();
                    qs[i] = e.target.value;
                    change({ suggested_questions: qs });
                  }}
                  className={select + (fieldErrors[`suggested_questions.${i}`] ? " border-term-err" : "")}
                />
                {fieldErrors[`suggested_questions.${i}`] && (
                  <div role="alert" className="text-term-err text-xs mt-1">
                    {fieldErrors[`suggested_questions.${i}`]}
                  </div>
                )}
              </div>
              <button type="button" className={ghost} aria-label={`Move question ${i + 1} up`} disabled={i === 0} onClick={() => moveQuestion(i, -1)}>
                ↑
              </button>
              <button
                type="button"
                className={ghost}
                aria-label={`Move question ${i + 1} down`}
                disabled={i === draft.suggested_questions.length - 1}
                onClick={() => moveQuestion(i, 1)}
              >
                ↓
              </button>
              <button
                type="button"
                className={ghost}
                aria-label={`Remove question ${i + 1}`}
                onClick={() => change({ suggested_questions: draft.suggested_questions.filter((_, j) => j !== i) })}
              >
                ✕
              </button>
            </li>
          ))}
        </ol>
        {fieldErrors.suggested_questions && (
          <div role="alert" className="text-term-err text-xs mb-2">
            {fieldErrors.suggested_questions}
          </div>
        )}
        <button
          type="button"
          className={ghost + " mb-6"}
          disabled={draft.suggested_questions.length >= MAX_QUESTIONS}
          onClick={() => change({ suggested_questions: [...draft.suggested_questions, ""] })}
        >
          + add question
        </button>

        <div className="mb-8">
          <button
            type="submit"
            disabled={busy}
            className={btn + " text-sm px-4 py-2 border-term-bright text-term-bright hover:bg-term-bright/10"}
          >
            {busy ? "saving…" : "save widget"}
          </button>
        </div>
      </form>

      <h2 className="text-term-fg text-sm mb-1">Preview</h2>
      <p className="text-term-dim text-xs mb-2">Colour and position update live; save to see the rest.</p>
      <div className="border border-term-line2 rounded-lg overflow-hidden mb-8 bg-white">
        {previewUrl && (
          <iframe key={previewUrl + saved.primary_color + saved.title} title="Widget preview" src={previewUrl} className="w-full h-[680px] border-0 block" />
        )}
      </div>

      <h2 className="text-term-fg text-sm mb-1">Add it to your site</h2>
      <p className="text-term-dim text-xs mb-3">
        Paste before <code>&lt;/body&gt;</code>. See the README for Next.js, WordPress and Webflow.
      </p>
      {snippets ? (
        <div className="space-y-4">
          <Snippet label="Floating bubble (recommended)" code={snippets.script} />
          <Snippet label="Inline panel" code={snippets.inline} />
          <Snippet label="Plain iframe (no script)" code={snippets.iframe} />
        </div>
      ) : (
        <p className="text-term-dim text-xs">Snippets unavailable right now.</p>
      )}
    </AdminSection>
  );
}

function Snippet({ label, code }: { label: string; code: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs text-term-dim flex-1">{label}</span>
        <button type="button" className={ghost} onClick={() => void copy()} aria-label={`Copy ${label}`}>
          {copied ? "copied" : "copy"}
        </button>
      </div>
      <pre className="bg-term-bg border border-term-line2 rounded p-3 text-xs text-term-fg overflow-x-auto whitespace-pre-wrap break-all">
        <code>{code}</code>
      </pre>
    </div>
  );
}
