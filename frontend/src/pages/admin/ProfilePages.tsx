import { useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { FormError } from "../../components/AuthForm";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import CollectionPage from "../../components/admin/CollectionPage";
import {
  FormField,
  fromItem,
  inputCls,
  toBody,
  validateValues,
  type FieldDef,
  type FormErrors,
  type FormValues,
} from "../../components/admin/fields";
import { LINKS, sectionByRoute } from "../../components/admin/sections";
import {
  getIdentity,
  getNotes,
  getProfilePreview,
  saveIdentity,
  saveNotes,
  type ApiError,
  type ProfilePreview,
} from "../../lib/api";

const primary =
  "font-mono text-xs px-3.5 py-2 rounded border border-term-bright text-term-bright hover:bg-term-bright/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-40";

const TOKEN_WARNING = 6000;
const NOTES_MAX = 20000;

function Loading() {
  return (
    <div role="status" className="text-term-dim text-sm py-6">
      loading…
    </div>
  );
}

// /admin/profile/:page
export default function ProfilePage() {
  const { page } = useParams();
  if (page === "identity") return <IdentityPage />;
  if (page === "notes") return <NotesPage />;
  if (page === "preview") return <PreviewPage />;
  const config = sectionByRoute(page);
  if (!config) return <Navigate to="/admin" replace />;
  return (
    <AdminSection title={config.title} intro={config.intro}>
      <CollectionPage key={config.route} config={config} />
    </AdminSection>
  );
}

const IDENTITY_FIELDS: FieldDef[] = [
  { name: "full_name", label: "Full name", kind: "text", maxLength: 200 },
  {
    name: "headline",
    label: "Headline",
    kind: "text",
    maxLength: 200,
    placeholder: "Backend engineer",
  },
  { name: "location", label: "Location", kind: "text", maxLength: 200 },
  {
    name: "open_to",
    label: "Open to",
    kind: "text",
    maxLength: 200,
    placeholder: "remote, relocation",
  },
  { name: "summary", label: "Summary", kind: "textarea", maxLength: 5000 },
  { name: "email_public", label: "Public email", kind: "email", maxLength: 200 },
  { name: "phone_public", label: "Public phone", kind: "text", maxLength: 200 },
  { name: "notice_period", label: "Notice period", kind: "text", maxLength: 200 },
  { name: "salary_expectation", label: "Salary expectation", kind: "text", maxLength: 200 },
  { name: "work_authorization", label: "Work authorisation", kind: "text", maxLength: 200 },
  { name: "photo_url", label: "Photo URL", kind: "url", placeholder: "https://" },
];
// The backend stores the five main identity fields as "" rather than null.
const NON_NULL = new Set(["full_name", "headline", "location", "open_to", "summary"]);

function IdentityPage() {
  const { setDirty, toast } = useAdmin();
  const [values, setValues] = useState<FormValues | null>(null);
  const [errors, setErrors] = useState<FormErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getIdentity()
      .then((d) => setValues(fromItem(IDENTITY_FIELDS, d)))
      .catch((e: Error) => {
        setValues(fromItem(IDENTITY_FIELDS, null));
        setError(e.message || "Could not load.");
      });
    return () => setDirty(false);
  }, [setDirty]);

  function change(name: string, v: unknown) {
    setValues((s) => ({ ...s, [name]: v }));
    setErrors((e) => ({ ...e, [name]: "" }));
    setDirty(true);
  }

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    if (!values) return;
    const found = validateValues(IDENTITY_FIELDS, values);
    setErrors(found);
    setError(null);
    if (Object.keys(found).length) return;
    setSaving(true);
    try {
      const body = toBody(IDENTITY_FIELDS, values);
      for (const k of NON_NULL) body[k] = body[k] ?? "";
      setValues(fromItem(IDENTITY_FIELDS, await saveIdentity(body)));
      setDirty(false);
      toast("Saved");
    } catch (e) {
      const err = e as ApiError;
      const f: FormErrors = {};
      for (const d of err.details ?? []) f[d.field] = d.message;
      setErrors(f);
      setError(err.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AdminSection title="Identity" intro="Who you are: the basics the bot introduces you with.">
      {values === null ? (
        <Loading />
      ) : (
        <form onSubmit={save} noValidate className="mb-10">
          <FormError message={error} />
          <div className="grid gap-x-4 md:grid-cols-2">
            {IDENTITY_FIELDS.map((def) => (
              <div key={def.name} className={def.kind === "textarea" ? "md:col-span-2" : ""}>
                <FormField
                  idPrefix="identity"
                  def={def}
                  values={values}
                  errors={errors}
                  onChange={change}
                />
              </div>
            ))}
          </div>
          <button type="submit" disabled={saving} className={primary}>
            {saving ? "saving…" : "save identity"}
          </button>
        </form>
      )}
      <h2 className="text-term-bright text-base mb-1">Links</h2>
      <p className="text-term-dim text-xs mb-3">{LINKS.intro}</p>
      <CollectionPage config={LINKS} />
    </AdminSection>
  );
}

function NotesPage() {
  const { setDirty, toast } = useAdmin();
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getNotes()
      .then(setText)
      .catch((e: Error) => {
        setText("");
        setError(e.message || "Could not load.");
      });
    return () => setDirty(false);
  }, [setDirty]);

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    setSaving(true);
    setError(null);
    try {
      setText(await saveNotes(text ?? ""));
      setDirty(false);
      toast("Saved");
    } catch (e) {
      setError((e as Error).message || "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AdminSection
      title="Notes"
      intro="Anything that doesn't fit elsewhere. Text from the old single profile box lives here."
    >
      {text === null ? (
        <Loading />
      ) : (
        <form onSubmit={save}>
          <FormError message={error} />
          <label htmlFor="notes-content" className="block text-xs text-term-dim mb-1">
            Notes
          </label>
          <textarea
            id="notes-content"
            value={text}
            maxLength={NOTES_MAX}
            spellCheck={false}
            aria-describedby="notes-count"
            onChange={(e) => {
              setText(e.target.value);
              setDirty(true);
            }}
            className={`${inputCls} border-term-line2 min-h-[320px] resize-y leading-relaxed`}
          />
          <div id="notes-count" className="text-term-dim text-xs mt-1 mb-3">
            {text.length.toLocaleString()} / {NOTES_MAX.toLocaleString()} characters
          </div>
          <button type="submit" disabled={saving} className={primary}>
            {saving ? "saving…" : "save notes"}
          </button>
        </form>
      )}
    </AdminSection>
  );
}

function PreviewPage() {
  const [preview, setPreview] = useState<ProfilePreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getProfilePreview()
      .then(setPreview)
      .catch((e: Error) => setError(e.message || "Could not load preview."));
  }, []);

  return (
    <AdminSection
      title="Preview"
      intro="Exactly what the bot knows about you: this text is added to every chat."
    >
      <FormError message={error} />
      {!preview && !error && <Loading />}
      {preview && (
        <>
          <p className="text-term-dim text-xs mb-2">
            {preview.chars.toLocaleString()} characters · ~{preview.approx_tokens.toLocaleString()}{" "}
            tokens
          </p>
          {preview.approx_tokens > TOKEN_WARNING && (
            <div
              role="alert"
              className="border border-term-amber text-term-amber rounded px-3 py-2 mb-3 text-xs"
            >
              Your profile is large (over ~{TOKEN_WARNING.toLocaleString()} tokens). Every chat
              message sends all of it, which costs more and may hit model limits. Consider trimming
              notes or old projects.
            </div>
          )}
          {preview.text ? (
            <pre className="whitespace-pre-wrap break-words bg-term-bg border border-term-line2 rounded p-3 text-xs text-term-fg leading-relaxed">
              {preview.text}
            </pre>
          ) : (
            <p className="text-term-fg text-sm">
              Nothing yet — add your identity and some sections.
            </p>
          )}
        </>
      )}
    </AdminSection>
  );
}
