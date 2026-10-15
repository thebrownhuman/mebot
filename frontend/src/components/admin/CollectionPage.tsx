import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  createProfileItem,
  deleteProfileItem,
  listProfileItems,
  reorderProfileItems,
  updateProfileItem,
  type ProfileItem,
} from "../../lib/api";
import { FormError } from "../AuthForm";
import { useAdmin } from "./AdminLayout";
import {
  FormField,
  fromItem,
  toBody,
  validateValues,
  type FormErrors,
  type FormValues,
} from "./fields";
import type { SectionConfig } from "./sections";

const btn =
  "font-mono text-xs px-2.5 py-1.5 rounded border focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-40";
const ghost = `${btn} border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright`;
const primary = `${btn} border-term-bright text-term-bright hover:bg-term-bright/10`;

function errorsFrom(err: unknown): { form: string; fields: FormErrors } {
  const e = err as ApiError;
  const fields: FormErrors = {};
  for (const d of e?.details ?? []) if (d.field) fields[d.field.split(".")[0]] = d.message;
  return { form: e?.message || "Something went wrong.", fields };
}

// A list of cards with add / edit (side panel) / delete / reorder, for one section.
export default function CollectionPage({ config }: { config: SectionConfig }) {
  const { setDirty, confirmLeave, toast } = useAdmin();
  const [items, setItems] = useState<ProfileItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ProfileItem | "new" | null>(null);
  const [values, setValues] = useState<FormValues>({});
  const [errors, setErrors] = useState<FormErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    setLoadError(null);
    listProfileItems(config.api)
      .then(setItems)
      .catch((e: Error) => {
        setItems([]);
        setLoadError(e.message || "Could not load.");
      });
  }, [config.api]);

  useEffect(() => {
    setItems(null);
    setEditing(null);
    load();
  }, [load]);

  useEffect(() => {
    if (editing) dialogRef.current?.querySelector<HTMLElement>("input,textarea,select")?.focus();
  }, [editing]);

  // Leaving the page with the panel open and edited asks first (see AdminLayout).
  useEffect(() => () => setDirty(false), [setDirty]);

  function open(item: ProfileItem | "new") {
    setEditing(item);
    setValues(fromItem(config.fields, item === "new" ? null : item));
    setErrors({});
    setFormError(null);
    setDirty(false);
  }

  function close() {
    if (!confirmLeave()) return;
    setEditing(null);
    setDirty(false);
  }

  function change(name: string, value: unknown) {
    setValues((v) => ({ ...v, [name]: value }));
    setErrors((e) => ({ ...e, [name]: "" }));
    setDirty(true);
  }

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    const found = validateValues(config.fields, values);
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    setSaving(true);
    try {
      const body = toBody(config.fields, values);
      if (editing === "new") {
        const created = await createProfileItem(config.api, body);
        setItems((list) => [...(list ?? []), created]);
      } else if (editing) {
        const updated = await updateProfileItem(config.api, editing.id, body);
        setItems((list) => (list ?? []).map((i) => (i.id === updated.id ? updated : i)));
      }
      setDirty(false);
      setEditing(null);
      toast("Saved");
    } catch (e) {
      const { form, fields } = errorsFrom(e);
      setErrors(fields);
      setFormError(form);
    } finally {
      setSaving(false);
    }
  }

  async function remove(item: ProfileItem) {
    if (!window.confirm(`Delete “${config.cardTitle(item)}”? This can't be undone here.`)) return;
    setBusyId(item.id);
    try {
      await deleteProfileItem(config.api, item.id);
      setItems((list) => (list ?? []).filter((i) => i.id !== item.id));
      toast("Deleted");
    } catch (e) {
      setLoadError((e as Error).message || "Delete failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function move(index: number, delta: number) {
    if (!items) return;
    const next = [...items];
    const [moved] = next.splice(index, 1);
    next.splice(index + delta, 0, moved);
    const previous = items;
    setItems(next); // optimistic; rolled back on error
    setBusyId(moved.id);
    try {
      await reorderProfileItems(
        config.api,
        next.map((i) => i.id),
      );
    } catch (e) {
      setItems(previous);
      setLoadError((e as Error).message || "Reorder failed.");
    } finally {
      setBusyId(null);
    }
  }

  const titleId = `${config.route}-panel-title`;

  return (
    <div>
      <div className="flex justify-end mb-3">
        <button type="button" onClick={() => open("new")} className={primary}>
          Add {config.noun}
        </button>
      </div>
      <FormError message={loadError} />

      {items === null ? (
        <div role="status" className="space-y-2">
          {[0, 1].map((k) => (
            <div
              key={k}
              className="h-16 rounded border border-term-line bg-term-panel/60 animate-pulse"
            />
          ))}
          <span className="sr-only">loading…</span>
        </div>
      ) : items.length === 0 && !loadError ? (
        <div className="border border-dashed border-term-line2 rounded-lg p-6 text-center">
          <p className="text-term-fg text-sm">{config.empty}</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map((item, i) => {
            const title = config.cardTitle(item);
            const meta = config.cardMeta?.(item);
            return (
              <li
                key={item.id}
                className="border border-term-line2 bg-term-panel/80 rounded-lg px-3 py-2.5 flex flex-wrap items-center gap-2"
              >
                <div className="flex-1 min-w-[10rem]">
                  <div className="text-term-fg text-sm break-words">{title}</div>
                  {meta && <div className="text-term-dim text-xs mt-0.5 break-words">{meta}</div>}
                </div>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    aria-label={`Move ${title} up`}
                    disabled={i === 0 || busyId !== null}
                    onClick={() => move(i, -1)}
                    className={ghost}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    aria-label={`Move ${title} down`}
                    disabled={i === items.length - 1 || busyId !== null}
                    onClick={() => move(i, 1)}
                    className={ghost}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    aria-label={`Edit ${title}`}
                    onClick={() => open(item)}
                    className={ghost}
                  >
                    edit
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${title}`}
                    disabled={busyId === item.id}
                    onClick={() => remove(item)}
                    className={`${btn} border-term-line2 text-term-dim hover:text-term-err hover:border-term-err`}
                  >
                    delete
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {editing && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/60" onClick={close}>
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape") close();
            }}
            className="w-full sm:max-w-lg h-full overflow-y-auto bg-term-panel border-l border-term-line2 p-5"
          >
            <h2 id={titleId} className="text-term-bright text-base mb-4">
              {editing === "new" ? `Add ${config.noun}` : `Edit ${config.noun}`}
            </h2>
            <form onSubmit={save} noValidate>
              <FormError message={formError} />
              {config.fields.map((def) => (
                <FormField
                  key={def.name}
                  idPrefix={`${config.route}-form`}
                  def={def}
                  values={values}
                  errors={errors}
                  onChange={change}
                />
              ))}
              <div className="flex gap-2 sticky bottom-0 bg-term-panel pt-2">
                <button type="button" onClick={close} className={ghost + " flex-1 py-2"}>
                  cancel
                </button>
                <button type="submit" disabled={saving} className={primary + " flex-1 py-2"}>
                  {saving ? "saving…" : "save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
