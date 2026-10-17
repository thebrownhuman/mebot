import { useCallback, useEffect, useRef, useState } from "react";
import { Field, FormError } from "../../components/AuthForm";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import {
  ApiError,
  getKnowledge,
  rebuildKnowledge,
  saveKnowledge,
  type KnowledgeMode,
  type KnowledgeStatus,
} from "../../lib/api";

// How the bot reads a large profile: whole (small profiles) or searched per question,
// the index behind it, and the optional embeddings ranking.

const MODES: { value: KnowledgeMode; label: string; hint: string }[] = [
  {
    value: "auto",
    label: "Automatic (recommended)",
    hint: "Send the whole profile until it passes the size threshold, then switch to retrieval.",
  },
  {
    value: "always",
    label: "Always retrieve",
    hint: "Only the parts relevant to each question are sent, whatever the size.",
  },
  {
    value: "off",
    label: "Never retrieve",
    hint: "Always send the whole profile. Costs more, and may not fit small models.",
  },
];

interface Draft {
  mode: KnowledgeMode;
  embeddings: boolean;
  model: string;
}

const toDraft = (k: KnowledgeStatus): Draft => ({
  mode: k.mode,
  embeddings: k.embeddings.enabled,
  model: k.embeddings.model ?? "",
});

const btn =
  "font-mono text-xs px-2.5 py-1.5 rounded border focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-50";

const fmt = (n: number) => n.toLocaleString("en-US");

function when(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function KnowledgePage() {
  const { setDirty, toast } = useAdmin();
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

  const polls = useRef(0);

  const load = useCallback(() => {
    setLoadError(null);
    return getKnowledge()
      .then((k) => {
        setStatus(k);
        setDraft(toDraft(k));
      })
      .catch((e: Error) => setLoadError(e.message || "Could not load this page."));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Embeddings are computed in the background after a save or rebuild: look again a few
  // times until they are all in (or an error stops them).
  useEffect(() => {
    const e = status?.embeddings;
    if (!status || !e || !e.enabled || e.last_error || status.effective !== "retrieval") return;
    if (e.embedded >= e.total || polls.current >= 8) return;
    const t = setTimeout(() => {
      polls.current += 1;
      void load();
    }, 2000);
    return () => clearTimeout(t);
  }, [status, load]);

  function applied(k: KnowledgeStatus) {
    polls.current = 0;
    setStatus(k);
    setDraft(toDraft(k));
    setDirty(false);
  }

  function change(next: Draft) {
    setDraft(next);
    setDirty(true);
  }

  function showError(e: unknown) {
    if (e instanceof ApiError && e.details.length) {
      setFieldErrors(Object.fromEntries(e.details.map((d) => [d.field, d.message])));
    }
    setError((e as Error).message || "Could not save.");
  }

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    if (!status || !draft) return;
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      const body: Parameters<typeof saveKnowledge>[0] = { mode: draft.mode };
      if (status.embeddings.supported) {
        body.embeddings_enabled = draft.embeddings;
        if (draft.embeddings) body.embedding_model = draft.model.trim() || null;
      }
      applied(await saveKnowledge(body));
      toast("Knowledge settings saved");
    } catch (e) {
      showError(e);
    } finally {
      setBusy(false);
    }
  }

  async function rebuild() {
    setRebuilding(true);
    setError(null);
    setFieldErrors({});
    try {
      applied(await rebuildKnowledge());
      toast("Index rebuilt");
    } catch (e) {
      showError(e);
    } finally {
      setRebuilding(false);
    }
  }

  const title = "Knowledge";
  if (loadError) {
    return (
      <AdminSection title={title}>
        <div role="alert" className="border border-term-err text-term-err rounded px-3 py-2 text-xs">
          {loadError}{" "}
          <button type="button" onClick={() => void load()} className="underline text-term-bright">
            Try again
          </button>
        </div>
      </AdminSection>
    );
  }
  if (!status || !draft) {
    return (
      <AdminSection title={title}>
        <p className="text-term-dim text-xs">loading…</p>
      </AdminSection>
    );
  }

  const emb = status.embeddings;
  const retrieval = status.effective === "retrieval";

  return (
    <AdminSection
      title={title}
      intro="Small profiles are sent to the AI whole. Large ones are searched, and only the parts relevant to each question are sent, which keeps answers grounded and your provider bill down."
    >
      <section
        aria-labelledby="kn-status"
        className="border border-term-line2 bg-term-panel/80 rounded-lg p-3 mb-5"
      >
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <h2 id="kn-status" className="text-term-fg text-sm">
            Current mode
          </h2>
          <span
            className={
              "font-mono text-[11px] px-2 py-0.5 rounded border " +
              (retrieval ? "border-term-bright text-term-bright" : "border-term-line2 text-term-dim")
            }
          >
            {retrieval ? "retrieval" : "whole profile"}
          </span>
        </div>
        <p className="text-term-dim text-xs leading-relaxed mb-3">{status.reason}</p>
        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2 text-xs font-mono">
          <Stat label="profile size" value={`~${fmt(status.profile_tokens)} tokens`} />
          <Stat label="threshold" value={`${fmt(status.threshold_tokens)} tokens`} />
          <Stat label="excerpt budget" value={`${fmt(status.budget_tokens)} tokens`} />
          <Stat label="indexed chunks" value={fmt(status.chunk_count)} />
          <Stat label="last indexed" value={when(status.last_indexed_at)} />
          <Stat
            label="ranking"
            value={emb.enabled && emb.embedded > 0 ? "keywords + embeddings" : "keywords"}
          />
        </dl>
        {status.chunk_count === 0 && (
          <p className="text-term-dim text-xs mt-3">
            Nothing is indexed yet. The index builds when you change your profile or the first
            visitor asks a question in retrieval mode, or when you press “rebuild index”.
          </p>
        )}
        {retrieval && status.index_stale && status.chunk_count > 0 && (
          <p className="text-term-amber text-xs mt-3">
            Your profile changed since the last index. It updates automatically in a moment, or on
            the next question.
          </p>
        )}
        <UsageLine usage={status.usage} />
      </section>

      <form onSubmit={save} noValidate>
        <FormError message={error} />
        <fieldset className="mb-5">
          <legend className="text-term-fg text-sm mb-2">When to use retrieval</legend>
          <div className="space-y-2">
            {MODES.map((m) => (
              <label key={m.value} className="flex items-start gap-2 text-xs text-term-fg cursor-pointer">
                <input
                  type="radio"
                  name="kn-mode"
                  className="mt-0.5"
                  checked={draft.mode === m.value}
                  onChange={() => change({ ...draft, mode: m.value })}
                />
                <span>
                  {m.label}
                  <span className="block text-term-dim">{m.hint}</span>
                </span>
              </label>
            ))}
          </div>
          {fieldErrors.mode && <div className="text-term-err text-xs mt-1">{fieldErrors.mode}</div>}
        </fieldset>

        <fieldset className="mb-5">
          <legend className="text-term-fg text-sm mb-2">Ranking with embeddings (optional)</legend>
          <label className="flex items-start gap-2 text-xs text-term-fg">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={draft.embeddings}
              disabled={!emb.supported}
              aria-describedby="kn-emb-hint"
              onChange={(e) => change({ ...draft, embeddings: e.target.checked })}
            />
            <span>
              also rank by meaning, not only keywords
              <span id="kn-emb-hint" className="block text-term-dim">
                {emb.supported
                  ? "Uses your AI provider's embeddings API, so it costs tokens on your key. Off by default; keyword ranking works without it."
                  : emb.reason}
              </span>
            </span>
          </label>
          {emb.supported && draft.embeddings && (
            <div className="mt-3">
              <Field
                id="kn-model"
                label="embedding model"
                value={draft.model}
                placeholder={emb.default_model ?? "model name"}
                maxLength={200}
                hint="Leave empty for your provider's default."
                error={fieldErrors.embedding_model}
                onChange={(e) => change({ ...draft, model: e.target.value })}
              />
            </div>
          )}
          {emb.enabled && (
            <p className="text-term-dim text-xs mt-2">
              {fmt(emb.embedded)} of {fmt(emb.total)} chunks embedded
              {emb.model ? ` with ${emb.model}` : ""}.
            </p>
          )}
          {emb.enabled && emb.last_error && (
            <p role="alert" className="text-term-err text-xs mt-2">
              Embeddings paused: {emb.last_error} Chat keeps using keyword ranking.
            </p>
          )}
          {fieldErrors.embeddings_enabled && (
            <div className="text-term-err text-xs mt-1">{fieldErrors.embeddings_enabled}</div>
          )}
        </fieldset>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="submit"
            disabled={busy || rebuilding}
            aria-busy={busy}
            className={btn + " text-sm px-4 py-2 border-term-bright text-term-bright hover:bg-term-bright/10"}
          >
            {busy ? "saving…" : "save"}
          </button>
          <button
            type="button"
            onClick={() => void rebuild()}
            disabled={busy || rebuilding}
            aria-busy={rebuilding}
            className={
              btn +
              " text-sm px-4 py-2 border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright"
            }
          >
            {rebuilding ? "rebuilding…" : "rebuild index"}
          </button>
        </div>
        <p className="text-term-dim text-xs mt-2">
          Rebuilding re-splits your profile and recomputes embeddings if they are on.
        </p>
      </form>
    </AdminSection>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-term-dim">{label}</dt>
      <dd className="text-term-fg break-words">{value}</dd>
    </div>
  );
}

function UsageLine({ usage }: { usage: KnowledgeStatus["usage"] }) {
  if (usage.retrieval_replies === 0) {
    return (
      <p className="text-term-dim text-xs mt-3">
        Last {usage.days} days: no replies used retrieval yet.
      </p>
    );
  }
  return (
    <p className="text-term-dim text-xs mt-3">
      Last {usage.days} days: {fmt(usage.retrieval_replies)} of {fmt(usage.questions)} questions
      used retrieval, sending about {fmt(usage.avg_prompt_tokens)} profile tokens instead of{" "}
      {fmt(usage.avg_profile_tokens)} (
      <span className="text-term-bright">{usage.saved_percent}% less</span>).
    </p>
  );
}
