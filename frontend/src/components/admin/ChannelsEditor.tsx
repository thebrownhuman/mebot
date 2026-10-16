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
import {
  CHANNEL_KINDS,
  PHONE_SHARE_CONFIRM,
  PHONE_SHARE_WARNING,
  kindMeta,
  type ChannelKind,
} from "../../lib/channels";
import { FormError } from "../AuthForm";
import { inputCls } from "./fields";
import { useAdmin } from "./AdminLayout";

const btn =
  "font-mono text-xs px-2.5 py-1.5 rounded border focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-40";
const ghost = `${btn} border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright`;
const primary = `${btn} border-term-bright text-term-bright hover:bg-term-bright/10`;

const str = (v: unknown) => (typeof v === "string" ? v : "");

interface Form {
  kind: ChannelKind;
  label: string;
  value: string;
  share: boolean;
}

function toForm(item: ProfileItem | null): Form {
  if (!item) return { kind: "portfolio", label: "", value: "", share: true };
  return {
    kind: kindMeta(item.kind).kind,
    label: str(item.label),
    value: str(item.value),
    share: item.share !== false,
  };
}

function errorsFrom(err: unknown): { form: string; fields: Record<string, string> } {
  const e = err as ApiError;
  const fields: Record<string, string> = {};
  for (const d of e?.details ?? []) if (d.field) fields[d.field.split(".")[0]] = d.message;
  return { form: e?.message || "Something went wrong.", fields };
}

// The contact channels list: what recruiters may be given, one Share switch per channel.
// Replaces the old Links list. A phone number is never shared without an explicit yes.
export default function ChannelsEditor() {
  const { setDirty, confirmLeave, toast } = useAdmin();
  const [items, setItems] = useState<ProfileItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ProfileItem | "new" | null>(null);
  const [form, setForm] = useState<Form>(toForm(null));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    setLoadError(null);
    listProfileItems("links")
      .then(setItems)
      .catch((e: Error) => {
        setItems([]);
        setLoadError(e.message || "Could not load.");
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (editing) dialogRef.current?.querySelector<HTMLElement>("select,input")?.focus();
  }, [editing]);

  useEffect(() => () => setDirty(false), [setDirty]);

  function open(item: ProfileItem | "new") {
    setEditing(item);
    setForm(toForm(item === "new" ? null : item));
    setErrors({});
    setFormError(null);
    setDirty(false);
  }

  function close() {
    if (!confirmLeave()) return;
    setEditing(null);
    setDirty(false);
  }

  function change(patch: Partial<Form>) {
    setForm((f) => ({ ...f, ...patch }));
    setErrors({});
    setDirty(true);
  }

  function changeKind(kind: ChannelKind) {
    // A phone number starts not shared; everything else starts shared.
    change({ kind, ...(editing === "new" ? { share: kind !== "phone" } : {}) });
  }

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    const found: Record<string, string> = {};
    if (!form.value.trim()) found.value = "Enter a value.";
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    const wasShared = editing !== "new" && editing !== null && editing.share !== false;
    const sharingPhone = form.kind === "phone" && form.share && !wasShared;
    if (sharingPhone && !window.confirm(PHONE_SHARE_CONFIRM)) return;
    setSaving(true);
    try {
      const body = {
        kind: form.kind,
        label: form.label.trim(),
        value: form.value.trim(),
        share: form.share,
        ...(sharingPhone ? { confirm_share_phone: true } : {}),
      };
      if (editing === "new") {
        const created = await createProfileItem("links", body);
        setItems((list) => [...(list ?? []), created]);
      } else if (editing) {
        const updated = await updateProfileItem("links", editing.id, body);
        setItems((list) => (list ?? []).map((i) => (i.id === updated.id ? updated : i)));
      }
      setDirty(false);
      setEditing(null);
      toast("Saved");
    } catch (e) {
      const { form: msg, fields } = errorsFrom(e);
      setErrors(fields);
      setFormError(msg);
    } finally {
      setSaving(false);
    }
  }

  async function toggleShare(item: ProfileItem) {
    const next = item.share === false;
    const phone = item.kind === "phone";
    if (next && phone && !window.confirm(PHONE_SHARE_CONFIRM)) return;
    setBusyId(item.id);
    setLoadError(null);
    try {
      const updated = await updateProfileItem("links", item.id, {
        share: next,
        ...(next && phone ? { confirm_share_phone: true } : {}),
      });
      setItems((list) => (list ?? []).map((i) => (i.id === updated.id ? updated : i)));
      toast(next ? "Shared with recruiters" : "No longer shared");
    } catch (e) {
      setLoadError((e as Error).message || "Could not change sharing.");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(item: ProfileItem) {
    const name = str(item.label) || str(item.value);
    if (!window.confirm(`Delete “${name}”? This can't be undone here.`)) return;
    setBusyId(item.id);
    try {
      await deleteProfileItem("links", item.id);
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
        "links",
        next.map((i) => i.id),
      );
    } catch (e) {
      setItems(previous);
      setLoadError((e as Error).message || "Reorder failed.");
    } finally {
      setBusyId(null);
    }
  }

  const meta = kindMeta(form.kind);
  const shared = items?.filter((i) => i.share !== false).length ?? 0;

  return (
    <section aria-labelledby="channels-title" className="mb-10">
      <div className="flex flex-wrap items-end gap-3 mb-1">
        <h2 id="channels-title" className="text-term-bright text-base">
          Contact channels
        </h2>
        <button type="button" onClick={() => open("new")} className={`${primary} ml-auto`}>
          Add channel
        </button>
      </div>
      <p className="text-term-dim text-xs mb-3">
        How recruiters can reach you. Only channels with <b>Share with recruiters</b> on are shown
        in the Contact panel or given by the bot. Switched-off channels are kept for you and are
        never revealed.
      </p>
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
          <p className="text-term-fg text-sm">
            Add how recruiters can reach you: email, LinkedIn, your portfolio…
          </p>
        </div>
      ) : (
        <>
          <ul className="space-y-2">
            {items.map((item, i) => {
              const m = kindMeta(item.kind);
              const title = str(item.label) || m.label;
              const on = item.share !== false;
              return (
                <li
                  key={item.id}
                  className="border border-term-line2 bg-term-panel/80 rounded-lg px-3 py-2.5 flex flex-wrap items-center gap-2"
                >
                  <span aria-hidden="true" className="w-6 text-center">
                    {m.icon}
                  </span>
                  <div className="flex-1 min-w-[9rem]">
                    <div className="text-term-fg text-sm break-words">{title}</div>
                    <div className="text-term-dim text-xs mt-0.5 break-all">{str(item.value)}</div>
                    {item.kind === "phone" && !on && (
                      <div className="text-term-amber text-[11px] mt-0.5">
                        Not shared: only you can see this number.
                      </div>
                    )}
                  </div>
                  <label className="flex items-center gap-2 text-xs text-term-dim min-h-[44px] sm:min-h-0">
                    <input
                      type="checkbox"
                      role="switch"
                      aria-label={`Share ${title} with recruiters`}
                      checked={on}
                      disabled={busyId !== null}
                      onChange={() => void toggleShare(item)}
                      className="accent-[#7dffb0] w-4 h-4"
                    />
                    <span>{on ? "shared" : "private"}</span>
                  </label>
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
          {shared === 0 && (
            <p className="text-term-dim text-xs mt-2">
              Nothing is shared yet: the bot will only offer the “Leave your contact” form.
            </p>
          )}
        </>
      )}

      {editing && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/60" onClick={close}>
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="channel-panel-title"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape") close();
            }}
            className="w-full sm:max-w-lg h-full overflow-y-auto bg-term-panel border-l border-term-line2 p-5"
          >
            <h2 id="channel-panel-title" className="text-term-bright text-base mb-4">
              {editing === "new" ? "Add channel" : "Edit channel"}
            </h2>
            <form onSubmit={save} noValidate>
              <FormError message={formError} />
              <div className="mb-4">
                <label htmlFor="channel-kind" className="block text-xs text-term-dim mb-1">
                  Type
                </label>
                <select
                  id="channel-kind"
                  value={form.kind}
                  onChange={(e) => changeKind(e.target.value as ChannelKind)}
                  className={`${inputCls} border-term-line2`}
                >
                  {CHANNEL_KINDS.map((k) => (
                    <option key={k.kind} value={k.kind}>
                      {k.icon} {k.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="mb-4">
                <label htmlFor="channel-value" className="block text-xs text-term-dim mb-1">
                  Value *
                </label>
                <input
                  id="channel-value"
                  value={form.value}
                  maxLength={500}
                  placeholder={meta.placeholder}
                  aria-invalid={errors.value ? true : undefined}
                  aria-describedby="channel-value-help"
                  onChange={(e) => change({ value: e.target.value })}
                  className={`${inputCls} ${errors.value ? "border-term-err" : "border-term-line2"}`}
                />
                <div id="channel-value-help">
                  {meta.hint && <div className="text-term-dim text-xs mt-1">{meta.hint}</div>}
                  {errors.value && <div className="text-term-err text-xs mt-1">{errors.value}</div>}
                </div>
              </div>
              <div className="mb-4">
                <label htmlFor="channel-label" className="block text-xs text-term-dim mb-1">
                  Label
                </label>
                <input
                  id="channel-label"
                  value={form.label}
                  maxLength={200}
                  placeholder={meta.label}
                  onChange={(e) => change({ label: e.target.value })}
                  className={`${inputCls} border-term-line2`}
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-term-fg mb-2 min-h-[44px] sm:min-h-0">
                <input
                  type="checkbox"
                  checked={form.share}
                  onChange={(e) => change({ share: e.target.checked })}
                  className="accent-[#7dffb0] w-4 h-4"
                />
                Share with recruiters
              </label>
              {form.kind === "phone" && (
                <p role="note" className="text-term-amber text-xs mb-4">
                  {PHONE_SHARE_WARNING}
                </p>
              )}
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
    </section>
  );
}
