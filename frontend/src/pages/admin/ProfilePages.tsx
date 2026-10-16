import { useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { FormError } from "../../components/AuthForm";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import ChannelsEditor from "../../components/admin/ChannelsEditor";
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
import { sectionByRoute } from "../../components/admin/sections";
import { DEFAULT_GREETING, PRONOUNS, renderGreeting } from "../../lib/greeting";
import {
  getIdentity,
  getNotes,
  getProfileFacts,
  getProfilePreview,
  saveIdentity,
  saveNotes,
  type ApiError,
  type ProfileFacts,
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
    name: "pronouns",
    label: "Pronouns",
    kind: "select",
    required: true,
    options: PRONOUNS.map((p) => [p, p]),
    hint: "How the bot refers to you. With they/them it uses your name or “they”.",
  },
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
  { name: "notice_period", label: "Notice period", kind: "text", maxLength: 200 },
  { name: "salary_expectation", label: "Salary expectation", kind: "text", maxLength: 200 },
  { name: "work_authorization", label: "Work authorisation", kind: "text", maxLength: 200 },
  { name: "photo_url", label: "Photo URL", kind: "url", placeholder: "https://" },
  {
    name: "assistant_greeting",
    label: "Assistant greeting",
    kind: "textarea",
    maxLength: 300,
    placeholder: DEFAULT_GREETING,
    hint: "The first message recruiters see. Placeholders: {first_name} {name} {pronoun_subj} {pronoun_obj}. Leave empty for the default.",
  },
  {
    name: "count_internships",
    label: "Count internships in my total experience",
    kind: "checkbox",
    hint: "Off by default: recruiters usually mean full-time experience.",
  },
  {
    name: "count_freelance",
    label: "Count freelance and contract work in my total experience",
    kind: "checkbox",
    hint: "On by default.",
  },
];
// The backend stores the five main identity fields as "" rather than null.
const NON_NULL = new Set(["full_name", "headline", "location", "open_to", "summary"]);

const withDefaults = (v: FormValues): FormValues => ({ ...v, pronouns: v.pronouns || "they/them" });

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function IdentityPage() {
  const { setDirty, toast } = useAdmin();
  const [values, setValues] = useState<FormValues | null>(null);
  const [errors, setErrors] = useState<FormErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getIdentity()
      .then((d) => setValues(withDefaults(fromItem(IDENTITY_FIELDS, d))))
      .catch((e: Error) => {
        setValues(withDefaults(fromItem(IDENTITY_FIELDS, null)));
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
      setValues(withDefaults(fromItem(IDENTITY_FIELDS, await saveIdentity(body))));
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
          <div className="mb-4 border border-term-line2 rounded px-3 py-2 text-xs">
            <div className="text-term-dim mb-1">Greeting preview (what recruiters see first)</div>
            <p data-testid="greeting-preview" className="text-term-fg leading-relaxed">
              {renderGreeting(
                str(values.assistant_greeting),
                str(values.full_name),
                str(values.pronouns) || "they/them",
              )}
            </p>
          </div>
          <button type="submit" disabled={saving} className={primary}>
            {saving ? "saving…" : "save identity"}
          </button>
        </form>
      )}
      <ChannelsEditor />
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

function FactsCard() {
  const [facts, setFacts] = useState<ProfileFacts | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getProfileFacts()
      .then(setFacts)
      .catch((e: Error) => setError(e.message || "Could not compute facts."));
  }, []);

  const total = facts?.total_experience;
  const skills = facts?.skills.filter((s) => s.text) ?? [];
  const edu = facts?.education.latest;
  return (
    <section
      aria-labelledby="facts-title"
      className="border border-term-line2 bg-term-panel/80 rounded-lg p-4 mb-5"
    >
      <h2 id="facts-title" className="text-term-amber text-sm mb-1">
        Computed facts
      </h2>
      <p className="text-term-dim text-xs mb-3">
        Worked out by mebot from your dates{facts ? ` as of ${facts.as_of}` : ""}. The bot quotes
        these numbers and never does its own date math.
      </p>
      {error && <p className="text-term-err text-xs">{error}</p>}
      {!facts && !error && <p className="text-term-dim text-xs">computing…</p>}
      {facts && (
        <dl className="grid grid-cols-1 sm:grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
          <dt className="text-term-dim">Total experience</dt>
          <dd className="text-term-fg">
            {!total
              ? "no jobs added yet"
              : total.months === 0
                ? "no full-time experience yet"
                : `${total.text} (${total.years.toFixed(1)} years), ${total.from} – ${total.to}`}
            {total && (
              <span className="text-term-dim">
                {" "}
                · internships {total.internships_counted ? "included" : "excluded"}
                {facts.internship_months > 0 && !total.internships_counted
                  ? ` (${facts.internship_months} months)`
                  : ""}
                {total.freelance_counted ? "" : " · freelance/contract excluded"}
              </span>
            )}
          </dd>
          <dt className="text-term-dim">Current role</dt>
          <dd className="text-term-fg">
            {facts.current_roles.length
              ? facts.current_roles.map((r) => `${r.title} at ${r.company} (${r.text})`).join("; ")
              : facts.last_role_end
                ? `none — last role ended ${facts.last_role_end}`
                : "—"}
          </dd>
          {skills.length > 0 && (
            <>
              <dt className="text-term-dim">Skills</dt>
              <dd className="text-term-fg">
                {skills
                  .map((s) => `${s.name}: ${s.text}${s.source === "stated" ? " (stated)" : ""}`)
                  .join(" · ")}
              </dd>
            </>
          )}
          {edu && (
            <>
              <dt className="text-term-dim">Education</dt>
              <dd className="text-term-fg">
                {edu.degree}
                {edu.field ? ` in ${edu.field}` : ""}, {edu.institution}
                {edu.in_progress ? " (in progress)" : edu.end_month ? ` (${edu.end_month})` : ""}
              </dd>
            </>
          )}
          <dt className="text-term-dim">Counts</dt>
          <dd className="text-term-fg">
            {facts.counts.projects} projects · {facts.counts.companies} companies
          </dd>
        </dl>
      )}
    </section>
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
      <FactsCard />
      <FormError message={error} />
      {preview?.warnings?.map((w) => (
        <div
          key={w}
          role="alert"
          className="border border-term-amber text-term-amber rounded px-3 py-2 mb-3 text-xs"
        >
          {w}
        </div>
      ))}
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
