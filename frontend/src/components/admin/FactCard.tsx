import { useState } from "react";
import {
  ApiError,
  approveLearnedFact,
  deleteLearnedFact,
  rejectLearnedFact,
  updateLearnedFact,
  type ApproveMode,
  type FactEdit,
  type LearnedFact,
} from "../../lib/api";
import { inputCls } from "./fields";

// One learned fact: the AI-cleaned wording, with Approve / Edit / Reject (pending),
// Edit / Delete (approved). The AI only proposes; nothing is known to the bot until
// the owner approves it. Used by the Open questions and Memory pages.

interface Conflict {
  field: string;
  current: string;
  next: string;
}

const btn =
  "font-mono text-xs px-2.5 py-1.5 rounded border focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-40";
const btnPrimary = `${btn} border-term-bright text-term-bright hover:bg-term-bright/10`;
const btnQuiet = `${btn} border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright`;
const btnDanger = `${btn} border-term-line2 text-term-dim hover:text-term-err hover:border-term-err`;

export const fieldLabel = (f: string) => f.replace(/_/g, " ");

export default function FactCard({
  fact,
  onChange,
  onRemoved,
  toast,
}: {
  fact: LearnedFact;
  onChange: (fact: LearnedFact) => void;
  onRemoved?: (id: string) => void;
  toast?: (text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(fact.fact_text);
  const [fillField, setFillField] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);

  const identity =
    fact.suggested_section === "identity" && fact.suggested_field && fact.suggested_value;
  const pending = fact.status === "pending";

  function fail(e: unknown, fallback: string) {
    setError(e instanceof Error && e.message ? e.message : fallback);
  }

  function edits(): FactEdit {
    const out: FactEdit = {};
    if (editing && draft.trim() !== fact.fact_text) out.fact_text = draft.trim();
    if (editing && identity && !fillField) {
      out.field = null;
      out.value = null;
    }
    return out;
  }

  async function approve(mode?: ApproveMode) {
    setBusy(true);
    setError(null);
    try {
      const saved = await approveLearnedFact(fact.id, { ...edits(), ...(mode ? { mode } : {}) });
      setConflict(null);
      setEditing(false);
      onChange(saved);
      toast?.("Saved to memory");
    } catch (e) {
      if (e instanceof ApiError && e.code === "IDENTITY_FIELD_SET" && e.details[0]) {
        const d = e.details[0] as unknown as { field: string; current: string; new: string };
        setConflict({ field: d.field, current: d.current, next: d.new });
      } else {
        fail(e, "Could not save this fact.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    setBusy(true);
    setError(null);
    try {
      const saved = await rejectLearnedFact(fact.id);
      setEditing(false);
      setConflict(null);
      onChange(saved);
      toast?.("Rejected");
    } catch (e) {
      fail(e, "Could not reject this fact.");
    } finally {
      setBusy(false);
    }
  }

  async function saveText() {
    setBusy(true);
    setError(null);
    try {
      const saved = await updateLearnedFact(fact.id, { fact_text: draft.trim() });
      setEditing(false);
      onChange(saved);
      toast?.("Saved");
    } catch (e) {
      fail(e, "Could not save the change.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm("Delete this fact? The bot will stop using it.")) return;
    setBusy(true);
    setError(null);
    try {
      await deleteLearnedFact(fact.id);
      onRemoved?.(fact.id);
      toast?.("Fact deleted");
    } catch (e) {
      fail(e, "Could not delete this fact.");
      setBusy(false);
    }
  }

  return (
    <article
      aria-label={`fact: ${fact.fact_text}`}
      className="border border-term-line rounded bg-term-panel/60 px-3 py-2.5 text-xs"
    >
      {editing ? (
        <div>
          <label htmlFor={`fact-${fact.id}`} className="block text-term-dim mb-1">
            Fact
          </label>
          <textarea
            id={`fact-${fact.id}`}
            value={draft}
            rows={3}
            maxLength={300}
            onChange={(e) => setDraft(e.target.value)}
            className={`${inputCls} border-term-line2 resize-y leading-relaxed`}
          />
          <div className="text-term-dim mt-1">{draft.length}/300</div>
        </div>
      ) : (
        <p className="text-term-fg text-sm leading-relaxed break-words">{fact.fact_text}</p>
      )}

      {fact.needs_review && pending && (
        <p className="text-term-amber mt-1.5">
          The AI couldn’t rewrite this safely, so it stays close to your own words. Check it
          before approving.
        </p>
      )}

      {identity && pending && (
        <div className="text-term-dim mt-1.5">
          {editing ? (
            <label className="flex items-start gap-2 text-term-fg">
              <input
                type="checkbox"
                checked={fillField}
                onChange={(e) => setFillField(e.target.checked)}
                className="mt-0.5 accent-term-bright"
              />
              <span>
                Also set {fieldLabel(fact.suggested_field!)} on your Identity page to “
                {fact.suggested_value}”
              </span>
            </label>
          ) : (
            <>
              Also fills your profile: <b className="text-term-fg">{fieldLabel(fact.suggested_field!)}</b>{" "}
              = “{fact.suggested_value}”
              {fact.current_value && <> (currently “{fact.current_value}”)</>}
            </>
          )}
        </div>
      )}

      {conflict && (
        <div
          role="alert"
          className="mt-2 border border-term-amber rounded px-3 py-2 text-term-fg"
        >
          {fieldLabel(conflict.field)} is already “{conflict.current}”. Replace it with “
          {conflict.next}”, or keep both?
          <div className="flex flex-wrap gap-2 mt-2">
            <button type="button" disabled={busy} onClick={() => void approve("replace")} className={btnPrimary}>
              Replace
            </button>
            <button type="button" disabled={busy} onClick={() => void approve("keep_both")} className={btnQuiet}>
              Keep both
            </button>
            <button type="button" disabled={busy} onClick={() => setConflict(null)} className={btnQuiet}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="text-term-err mt-2">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 mt-2.5">
        {pending && !conflict && (
          <>
            <button type="button" disabled={busy || !draft.trim()} onClick={() => void approve()} className={btnPrimary}>
              {busy ? "saving…" : editing ? "Save & approve" : "Approve"}
            </button>
            {editing ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setEditing(false);
                  setDraft(fact.fact_text);
                  setFillField(true);
                }}
                className={btnQuiet}
              >
                Cancel
              </button>
            ) : (
              <button type="button" disabled={busy} onClick={() => setEditing(true)} className={btnQuiet}>
                Edit
              </button>
            )}
            <button type="button" disabled={busy} onClick={() => void reject()} className={btnDanger}>
              Reject
            </button>
          </>
        )}
        {fact.status === "approved" && (
          <>
            <span className="text-term-bright">approved</span>
            {editing ? (
              <>
                <button type="button" disabled={busy || !draft.trim()} onClick={() => void saveText()} className={btnPrimary}>
                  Save
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setEditing(false);
                    setDraft(fact.fact_text);
                  }}
                  className={btnQuiet}
                >
                  Cancel
                </button>
              </>
            ) : (
              <button type="button" disabled={busy} onClick={() => setEditing(true)} className={btnQuiet}>
                Edit
              </button>
            )}
            <button type="button" disabled={busy} onClick={() => void remove()} className={btnDanger}>
              Delete
            </button>
          </>
        )}
        {fact.status === "rejected" && (
          <>
            <span className="text-term-dim">rejected</span>
            <button type="button" disabled={busy} onClick={() => void remove()} className={btnDanger}>
              Delete
            </button>
          </>
        )}
        <span className="text-term-dim ml-auto">
          {fact.source === "telegram" ? "via Telegram" : "from admin"}
        </span>
      </div>
    </article>
  );
}
