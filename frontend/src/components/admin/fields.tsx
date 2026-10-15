import { useState } from "react";

// Labelled form controls for the admin data pages. Every control gets a visible label,
// aria-invalid + aria-describedby for errors, and the terminal theme.

export type FieldKind =
  "text" | "textarea" | "url" | "email" | "month" | "select" | "tags" | "number";

export interface FieldDef {
  name: string;
  label: string;
  kind: FieldKind;
  required?: boolean;
  options?: [string, string][];
  hint?: string;
  placeholder?: string;
  maxLength?: number;
  // month fields: show an "ongoing" checkbox that clears this field
  currentLabel?: string;
}

export type FormValues = Record<string, unknown>;
export type FormErrors = Record<string, string>;

export const inputCls =
  "w-full bg-term-bg border rounded text-term-fg font-mono text-sm px-3 py-2 outline-none focus:border-term-bright disabled:opacity-50";

function describedBy(id: string, error?: string, hint?: string) {
  return [error && `${id}-error`, hint && `${id}-hint`].filter(Boolean).join(" ") || undefined;
}

function Help({ id, error, hint }: { id: string; error?: string; hint?: string }) {
  return (
    <>
      {hint && (
        <div id={`${id}-hint`} className="text-term-dim text-xs mt-1">
          {hint}
        </div>
      )}
      {error && (
        <div id={`${id}-error`} className="text-term-err text-xs mt-1">
          {error}
        </div>
      )}
    </>
  );
}

function TagInput({
  id,
  value,
  onChange,
  invalid,
  describedBy: db,
}: {
  id: string;
  value: string[];
  onChange: (v: string[]) => void;
  invalid: boolean;
  describedBy?: string;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const t = draft.trim();
    if (t && !value.includes(t)) onChange([...value, t]);
    setDraft("");
  };
  return (
    <div>
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5 mb-1.5" aria-label="added">
          {value.map((t) => (
            <li
              key={t}
              className="flex items-center gap-1 border border-term-line2 rounded px-2 py-0.5 text-xs text-term-fg"
            >
              {t}
              <button
                type="button"
                aria-label={`remove ${t}`}
                onClick={() => onChange(value.filter((x) => x !== t))}
                className="text-term-dim hover:text-term-err"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <input
        id={id}
        value={draft}
        aria-invalid={invalid || undefined}
        aria-describedby={db}
        placeholder="type and press Enter"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add();
          } else if (e.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={add}
        className={`${inputCls} ${invalid ? "border-term-err" : "border-term-line2"}`}
      />
    </div>
  );
}

export function FormField({
  idPrefix,
  def,
  values,
  errors,
  onChange,
}: {
  idPrefix: string;
  def: FieldDef;
  values: FormValues;
  errors: FormErrors;
  onChange: (name: string, value: unknown) => void;
}) {
  const id = `${idPrefix}-${def.name}`;
  const error = errors[def.name];
  const raw = values[def.name];
  const str = raw === null || raw === undefined ? "" : String(raw);
  const db = describedBy(id, error, def.hint);
  const cls = `${inputCls} ${error ? "border-term-err" : "border-term-line2"}`;
  const label = def.label + (def.required ? " *" : "");
  const current = def.currentLabel ? values[`__current_${def.name}`] === true : false;

  let control: React.ReactNode;
  switch (def.kind) {
    case "textarea":
      control = (
        <textarea
          id={id}
          value={str}
          rows={4}
          maxLength={def.maxLength}
          aria-invalid={error ? true : undefined}
          aria-describedby={db}
          placeholder={def.placeholder}
          onChange={(e) => onChange(def.name, e.target.value)}
          className={cls + " resize-y leading-relaxed"}
        />
      );
      break;
    case "select":
      control = (
        <select
          id={id}
          value={str}
          aria-invalid={error ? true : undefined}
          aria-describedby={db}
          onChange={(e) => onChange(def.name, e.target.value)}
          className={cls}
        >
          {!def.required && <option value="">—</option>}
          {def.options?.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      );
      break;
    case "tags":
      control = (
        <TagInput
          id={id}
          value={Array.isArray(raw) ? (raw as string[]) : []}
          invalid={!!error}
          describedBy={db}
          onChange={(v) => onChange(def.name, v)}
        />
      );
      break;
    default:
      control = (
        <input
          id={id}
          type={def.kind === "number" ? "number" : def.kind}
          value={str}
          step={def.kind === "number" ? "0.5" : undefined}
          min={def.kind === "number" ? 0 : undefined}
          maxLength={def.maxLength}
          disabled={current}
          aria-invalid={error ? true : undefined}
          aria-describedby={db}
          placeholder={def.placeholder ?? (def.kind === "month" ? "YYYY-MM" : undefined)}
          onChange={(e) => onChange(def.name, e.target.value)}
          className={cls}
        />
      );
  }

  return (
    <div className="mb-4">
      <label htmlFor={id} className="block text-xs text-term-dim mb-1">
        {label}
      </label>
      {control}
      {def.currentLabel && (
        <label className="flex items-center gap-2 text-xs text-term-fg mt-1.5">
          <input
            type="checkbox"
            checked={current}
            onChange={(e) => {
              onChange(`__current_${def.name}`, e.target.checked);
              if (e.target.checked) onChange(def.name, "");
            }}
            className="accent-term-bright"
          />
          {def.currentLabel}
        </label>
      )}
      <Help id={id} error={error} hint={def.hint} />
    </div>
  );
}

// Form values -> API body: blank strings become null, internal "__" keys dropped,
// numbers parsed.
export function toBody(defs: FieldDef[], values: FormValues): FormValues {
  const out: FormValues = {};
  for (const d of defs) {
    const v = values[d.name];
    if (d.kind === "tags") out[d.name] = Array.isArray(v) ? v : [];
    else if (d.kind === "number") out[d.name] = v === "" || v == null ? null : Number(v);
    else if (typeof v === "string") out[d.name] = v.trim() === "" ? null : v.trim();
    else out[d.name] = v ?? null;
  }
  return out;
}

export function fromItem(defs: FieldDef[], item: FormValues | null): FormValues {
  const out: FormValues = {};
  for (const d of defs) {
    const v = item?.[d.name];
    out[d.name] = d.kind === "tags" ? (Array.isArray(v) ? v : []) : (v ?? "");
    if (d.currentLabel) out[`__current_${d.name}`] = !!item && !v;
  }
  return out;
}

// Client-side checks that mirror the backend, so most errors show before a request.
export function validateValues(defs: FieldDef[], values: FormValues): FormErrors {
  const e: FormErrors = {};
  for (const d of defs) {
    const v = values[d.name];
    const s = typeof v === "string" ? v.trim() : "";
    if (d.required && d.kind !== "tags" && !s) e[d.name] = "Required.";
    else if (s && d.kind === "url" && !/^https?:\/\/[^\s/?#]+/i.test(s))
      e[d.name] = "Use an http(s) URL.";
    else if (s && d.kind === "month" && !/^\d{4}-(0[1-9]|1[0-2])$/.test(s))
      e[d.name] = "Use YYYY-MM.";
  }
  const start = values.start_month;
  const end = values.end_month;
  if (typeof start === "string" && typeof end === "string" && start && end && end < start)
    e.end_month = e.end_month ?? "End month is before start month.";
  return e;
}
