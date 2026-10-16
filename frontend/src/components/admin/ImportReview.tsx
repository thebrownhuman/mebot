import { useMemo, useState } from "react";
import { FormError } from "../AuthForm";
import {
  ApiError,
  applyImport,
  type DraftEntry,
  type ImportAction,
  type ImportDecision,
  type ImportJob,
  type ImportSummary,
} from "../../lib/api";

// Review an import draft: every proposed item with its match against the profile,
// Add / Update / Skip, inline edit, then one Apply for everything.

export const SECTION_LABEL: Record<string, string> = {
  identity: "Identity",
  experiences: "Experience",
  educations: "Education",
  certifications: "Certifications",
  skills: "Skills",
  projects: "Projects",
  interests: "Interests",
  links: "Contact channels",
  notes: "Notes",
};

const FIELD_LABEL: Record<string, string> = {
  start_month: "start",
  end_month: "end",
  live_url: "live URL",
  repo_url: "repo URL",
  employment_type: "type",
};

function show(v: unknown): string {
  if (v == null || v === "") return "—";
  if (Array.isArray(v)) return v.join(", ") || "—";
  return String(v);
}

export function titleOf(section: string, d: Record<string, unknown>): string {
  const s = (k: string) => (d[k] == null ? "" : String(d[k]));
  switch (section) {
    case "identity":
      return `${s("field").replace("_", " ")}: ${s("value")}`;
    case "experiences":
      return [s("title"), s("company")].filter(Boolean).join(" — ");
    case "educations":
      return [s("degree"), s("institution")].filter(Boolean).join(" — ");
    case "links":
      return `${s("kind")}: ${s("value")}`;
    case "notes":
      return s("content").split("\n")[0];
    default:
      return s("name");
  }
}

function dates(d: Record<string, unknown>): string | null {
  if (!d.start_month && !d.end_month) return null;
  return `${d.start_month ?? "?"} – ${d.end_month ?? "present"}`;
}

const BADGE: Record<DraftEntry["match"]["status"], { text: string; cls: string }> = {
  new: { text: "New", cls: "border-term-bright text-term-bright" },
  same: { text: "Already in profile", cls: "border-term-line2 text-term-dim" },
  changed: { text: "Changed", cls: "border-term-amber text-term-amber" },
};

const btn =
  "font-mono text-xs px-2.5 py-1.5 min-h-[32px] rounded border focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-50";
const ghost = btn + " border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright";
const inputCls =
  "w-full bg-term-bg border border-term-line2 rounded text-term-fg font-mono text-xs px-2 py-1.5 outline-none focus:border-term-bright";

type Choice = { action: ImportAction; data?: Record<string, unknown> };

function SourceSnippet({ source, snippet }: { source: string; snippet: string }) {
  const i = source.indexOf(snippet);
  if (i < 0) return <p className="text-term-dim text-xs">Not found in the extracted text.</p>;
  const a = Math.max(0, i - 160);
  const b = Math.min(source.length, i + snippet.length + 160);
  return (
    <pre className="mt-2 whitespace-pre-wrap break-words text-[11px] text-term-dim bg-term-bg border border-term-line2 rounded p-2 max-h-48 overflow-y-auto">
      {a > 0 && "…"}
      {source.slice(a, i)}
      <mark className="bg-term-amber/30 text-term-fg">{snippet}</mark>
      {source.slice(i + snippet.length, b)}
      {b < source.length && "…"}
    </pre>
  );
}

function EditForm({
  data,
  onSave,
  onCancel,
}: {
  data: Record<string, unknown>;
  onSave: (d: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const keys = Object.keys(data).filter((k) => k !== "field");
  const [draft, setDraft] = useState<Record<string, string>>(
    Object.fromEntries(keys.map((k) => [k, Array.isArray(data[k]) ? (data[k] as string[]).join(", ") : show(data[k]).replace(/^—$/, "")])),
  );
  return (
    <div className="mt-2 grid gap-2 sm:grid-cols-2">
      {keys.map((k) => {
        const long = k === "description" || k === "summary" || k === "content" || (k === "value" && String(data.field) === "summary");
        return (
          <label key={k} className={"text-[11px] text-term-dim " + (long ? "sm:col-span-2" : "")}>
            {FIELD_LABEL[k] ?? k.replace("_", " ")}
            {long ? (
              <textarea
                rows={3}
                className={inputCls + " mt-0.5"}
                value={draft[k]}
                onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
              />
            ) : (
              <input
                className={inputCls + " mt-0.5"}
                value={draft[k]}
                onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
              />
            )}
          </label>
        );
      })}
      <div className="flex gap-2 sm:col-span-2">
        <button
          type="button"
          className={btn + " border-term-bright text-term-bright"}
          onClick={() =>
            onSave({
              ...data,
              ...Object.fromEntries(
                keys.map((k) => [
                  k,
                  Array.isArray(data[k])
                    ? draft[k].split(",").map((x) => x.trim()).filter(Boolean)
                    : draft[k].trim() === ""
                      ? null
                      : draft[k].trim(),
                ]),
              ),
            })
          }
        >
          done
        </button>
        <button type="button" className={ghost} onClick={onCancel}>
          cancel
        </button>
      </div>
    </div>
  );
}

function ItemCard({
  section,
  entry,
  choice,
  onChoose,
  source,
  error,
}: {
  section: string;
  entry: DraftEntry;
  choice: Choice;
  onChoose: (c: Choice) => void;
  source: string | null;
  error?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const data = choice.data ?? entry.data;
  const badge = BADGE[entry.match.status];
  const canUpdate = Boolean(entry.match.existing_id) || section === "identity";
  const options: ImportAction[] = canUpdate && entry.match.status !== "new" ? ["update", "skip"] : ["add", "skip"];
  const name = `act-${entry.temp_id}`;
  const when = dates(data);
  return (
    <li
      className={
        "border rounded-lg p-3 " +
        (error ? "border-term-err" : choice.action === "skip" ? "border-term-line opacity-80" : "border-term-line2")
      }
    >
      <div className="flex flex-wrap items-start gap-2">
        <div className="flex-1 min-w-[12rem]">
          <div className="text-sm text-term-fg break-words">{titleOf(section, data) || "(untitled)"}</div>
          {when && <div className="text-[11px] text-term-dim">{when}</div>}
        </div>
        <span className={"shrink-0 text-[10px] uppercase tracking-wide border rounded px-1.5 py-0.5 " + badge.cls}>
          {badge.text}
        </span>
      </div>
      {entry.needs_review && entry.reason && (
        <p role="note" className="mt-2 text-xs text-term-amber">
          ⚠ Check this: {entry.reason}
        </p>
      )}
      {entry.match.status === "changed" && entry.match.diff && (
        <dl className="mt-2 text-xs grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          {Object.entries(entry.match.diff).map(([k, d]) => (
            <div key={k} className="contents">
              <dt className="text-term-dim">{FIELD_LABEL[k] ?? k.replace("_", " ")}</dt>
              <dd className="min-w-0 break-words">
                <del className="text-term-err/80">{show(d.from)}</del> → <ins className="no-underline text-term-bright">{show(d.to)}</ins>
              </dd>
            </div>
          ))}
        </dl>
      )}
      {section !== "identity" && entry.match.status !== "changed" && typeof data.description === "string" && (
        <p className="mt-2 text-xs text-term-dim line-clamp-3">{data.description}</p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-xs text-term-err">
          {error}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <fieldset className="flex gap-1">
          <legend className="sr-only">Action for {titleOf(section, data)}</legend>
          {options.map((a) => (
            <label
              key={a}
              className={
                "cursor-pointer font-mono text-xs px-2.5 py-1.5 min-h-[32px] inline-flex items-center rounded border focus-within:outline focus-within:outline-2 focus-within:outline-term-bright " +
                (choice.action === a
                  ? a === "skip"
                    ? "border-term-dim text-term-fg bg-term-panel"
                    : "border-term-bright text-term-bright bg-term-bright/10"
                  : "border-term-line2 text-term-dim")
              }
            >
              <input
                type="radio"
                className="sr-only"
                name={name}
                value={a}
                checked={choice.action === a}
                onChange={() => onChoose({ ...choice, action: a })}
              />
              {a === "add" ? "Add" : a === "update" ? "Update" : "Skip"}
            </label>
          ))}
        </fieldset>
        <button type="button" className={ghost} onClick={() => setEditing((e) => !e)} aria-expanded={editing}>
          edit
        </button>
        {entry.evidence && entry.evidence.length > 0 && (
          <button type="button" className={ghost} aria-expanded={showEvidence} onClick={() => setShowEvidence((s) => !s)}>
            {showEvidence ? "hide evidence" : "evidence"}
          </button>
        )}
        {source && entry.snippet && (
          <button type="button" className={ghost} aria-expanded={showSource} onClick={() => setShowSource((s) => !s)}>
            {showSource ? "hide source" : "show in source"}
          </button>
        )}
      </div>
      {editing && (
        <EditForm
          data={data}
          onCancel={() => setEditing(false)}
          onSave={(d) => {
            setEditing(false);
            onChoose({ action: choice.action === "skip" ? options[0] : choice.action, data: d });
          }}
        />
      )}
      {showSource && source && entry.snippet && <SourceSnippet source={source} snippet={entry.snippet} />}
      {showEvidence && entry.evidence && (
        <table className="mt-2 w-full text-[11px] text-term-dim">
          <caption className="sr-only">Where each tech was detected</caption>
          <thead>
            <tr className="text-left">
              <th className="font-normal pr-3">tech</th>
              <th className="font-normal">found in</th>
            </tr>
          </thead>
          <tbody>
            {entry.evidence.map((e) => (
              <tr key={e.tech + e.file}>
                <td className="pr-3 text-term-fg align-top">{e.tech}</td>
                <td className="font-mono break-all">
                  {e.file}
                  {e.key && e.key !== e.file ? ` (${e.key})` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </li>
  );
}

export function summaryText(s: ImportSummary): string {
  const nouns: Record<string, [string, string]> = {
    experiences: ["job", "jobs"],
    educations: ["education entry", "education entries"],
    skills: ["skill", "skills"],
    projects: ["project", "projects"],
    interests: ["interest", "interests"],
    links: ["contact channel", "contact channels"],
    notes: ["note", "notes"],
    identity: ["identity field", "identity fields"],
  };
  const added: string[] = [];
  let updated = 0;
  for (const [k, v] of Object.entries(s)) {
    const [one, many] = nouns[k] ?? [k, k];
    if (k === "identity") updated += v.updated;
    else {
      if (v.added) added.push(`${v.added} ${v.added === 1 ? one : many}`);
      updated += v.updated;
    }
  }
  const parts = [];
  if (added.length) parts.push("Added " + added.join(", "));
  if (updated) parts.push(`updated ${updated}`);
  return parts.length ? parts.join("; ") + "." : "Nothing changed.";
}

export default function ImportReview({
  job,
  onApplied,
  onDiscard,
}: {
  job: ImportJob;
  onApplied: (s: ImportSummary) => void;
  onDiscard: () => void;
}) {
  const sections = job.draft?.sections ?? {};
  const entries = useMemo(() => Object.values(sections).flat(), [sections]);
  const [choices, setChoices] = useState<Record<string, Choice>>(() =>
    Object.fromEntries(entries.map((e) => [e.temp_id, { action: e.default_action }])),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [itemErrors, setItemErrors] = useState<Record<string, string>>({});

  const groups: [string, string, DraftEntry[]][] = [];
  for (const [slug, list] of Object.entries(sections)) {
    if (slug === "educations") {
      const plain = list.filter((e) => e.kind !== "certification");
      const certs = list.filter((e) => e.kind === "certification");
      if (plain.length) groups.push([slug, "educations", plain]);
      if (certs.length) groups.push([slug, "certifications", certs]);
    } else groups.push([slug, slug, list]);
  }
  const selected = entries.filter((e) => choices[e.temp_id]?.action !== "skip").length;
  const newOnes = entries.filter((e) => e.match.status === "new" && !e.needs_review);

  async function apply() {
    setBusy(true);
    setError(null);
    setItemErrors({});
    const decisions: ImportDecision[] = entries.map((e) => {
      const c = choices[e.temp_id];
      return c.data ? { temp_id: e.temp_id, action: c.action, data: c.data } : { temp_id: e.temp_id, action: c.action };
    });
    try {
      onApplied(await applyImport(job.id, decisions));
    } catch (e) {
      if (e instanceof ApiError && e.details.length) {
        const map: Record<string, string> = {};
        for (const d of e.details) {
          const [tid, ...rest] = d.field.split(".");
          map[tid] = (map[tid] ? map[tid] + "; " : "") + (rest.length ? `${rest.join(".")}: ` : "") + d.message;
        }
        setItemErrors(map);
      }
      setError((e as Error).message || "Could not apply the import.");
    } finally {
      setBusy(false);
    }
  }

  if (!entries.length) {
    return (
      <div className="border border-term-line2 rounded-lg p-4">
        <p className="text-term-fg text-sm mb-1">Nothing to import</p>
        <p className="text-term-dim text-xs mb-3">The file had nothing we could use for your profile.</p>
        <button type="button" className={ghost} onClick={onDiscard}>
          start over
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <p className="text-term-dim text-xs flex-1 min-w-[12rem]">
          {entries.length} items found in {job.filename ?? "your file"}. Nothing is saved until you press Apply.
        </p>
        {newOnes.length > 0 && (
          <button
            type="button"
            className={ghost}
            onClick={() =>
              setChoices((c) => ({
                ...c,
                ...Object.fromEntries(newOnes.map((e) => [e.temp_id, { ...c[e.temp_id], action: "add" as const }])),
              }))
            }
          >
            accept all new ({newOnes.length})
          </button>
        )}
      </div>
      <FormError message={error} />
      {(job.draft?.errors ?? []).length > 0 && (
        <div role="alert" className="border border-term-amber rounded px-3 py-2 mb-4 text-xs text-term-amber">
          <p className="mb-1">Some sources couldn't be imported:</p>
          <ul className="space-y-0.5">
            {job.draft!.errors!.map((e) => (
              <li key={e.source}>
                <span className="font-mono text-term-fg">{e.source}</span>: {e.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {groups.map(([slug, label, list]) => (
        <section key={label} className="mb-6" aria-labelledby={`imp-${label}`}>
          <h2 id={`imp-${label}`} className="text-term-fg text-sm mb-2">
            {SECTION_LABEL[label] ?? label} <span className="text-term-dim text-xs">({list.length})</span>
          </h2>
          <ul className="space-y-2">
            {list.map((e) => (
              <ItemCard
                key={e.temp_id}
                section={slug}
                entry={e}
                choice={choices[e.temp_id]}
                onChoose={(c) => setChoices((all) => ({ ...all, [e.temp_id]: c }))}
                source={job.source_text}
                error={itemErrors[e.temp_id]}
              />
            ))}
          </ul>
        </section>
      ))}
      <div className="sticky bottom-0 -mx-4 px-4 py-3 bg-term-bg/95 border-t border-term-line flex flex-wrap gap-2 items-center">
        <button
          type="button"
          disabled={busy || selected === 0}
          onClick={() => void apply()}
          className={btn + " text-sm px-4 py-2 border-term-bright text-term-bright hover:bg-term-bright/10"}
        >
          {busy ? "applying…" : `apply ${selected} item${selected === 1 ? "" : "s"}`}
        </button>
        <button
          type="button"
          className={ghost}
          disabled={busy}
          onClick={() => {
            if (window.confirm("Discard this import? Nothing from it will be saved.")) onDiscard();
          }}
        >
          discard
        </button>
      </div>
    </div>
  );
}
