import { useCallback, useEffect, useState } from "react";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import FactCard from "../../components/admin/FactCard";
import { inputCls } from "../../components/admin/fields";
import { addLearnedFact, listLearnedFacts, type LearnedFact } from "../../lib/api";

// What the bot has learned from you: facts waiting for approval, the approved ones the
// bot uses, and the ones you rejected.
export default function MemoryPage() {
  const { toast, refreshOpenCount } = useAdmin();
  const [facts, setFacts] = useState<LearnedFact[] | null>(null);
  const [maxActive, setMaxActive] = useState(200);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const load = useCallback(() => {
    listLearnedFacts()
      .then((r) => {
        setFacts(r.items);
        setMaxActive(r.max_active);
        setError(null);
      })
      .catch((e: Error) => {
        setFacts([]);
        setError(e.message || "Could not load memory.");
      });
  }, []);
  useEffect(load, [load]);

  const upsert = (f: LearnedFact) => {
    setFacts((xs) => (xs ?? []).map((x) => (x.id === f.id ? f : x)));
    refreshOpenCount();
  };
  const remove = (id: string) => {
    setFacts((xs) => (xs ?? []).filter((x) => x.id !== id));
    refreshOpenCount();
  };

  async function add(ev: React.FormEvent) {
    ev.preventDefault();
    if (!text.trim()) return;
    setAdding(true);
    setAddError(null);
    try {
      const f = await addLearnedFact(text.trim());
      setFacts((xs) => [f, ...(xs ?? [])]);
      setText("");
    } catch (e) {
      setAddError((e as Error).message || "Could not add the fact.");
    } finally {
      setAdding(false);
    }
  }

  const pending = (facts ?? []).filter((f) => f.status === "pending");
  const approved = (facts ?? []).filter((f) => f.status === "approved");
  const rejected = (facts ?? []).filter((f) => f.status === "rejected");
  const active = approved.filter((f) => f.suggested_section === "learned").length;

  return (
    <AdminSection
      title="Memory"
      intro="Facts the bot learned from you. The AI cleans up your wording, but nothing is used in chat until you approve it."
    >
      <form onSubmit={add} className="mb-6">
        <label htmlFor="new-fact" className="block text-xs text-term-dim mb-1">
          Teach the bot something
        </label>
        <textarea
          id="new-fact"
          value={text}
          rows={2}
          maxLength={2000}
          placeholder="e.g. Speaks Hindi, English and some German"
          onChange={(e) => setText(e.target.value)}
          className={`${inputCls} border-term-line2 resize-y`}
        />
        <button
          type="submit"
          disabled={adding || !text.trim()}
          className="mt-2 font-mono text-xs px-3 py-1.5 rounded border border-term-bright text-term-bright hover:bg-term-bright/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-40"
        >
          {adding ? "cleaning up…" : "Add fact"}
        </button>
        {addError && (
          <p role="alert" className="text-term-err text-xs mt-2">
            {addError}
          </p>
        )}
      </form>

      {error && (
        <p role="alert" className="text-term-err text-xs mb-3">
          {error}
        </p>
      )}
      {facts === null ? (
        <p role="status" className="text-term-dim text-xs">
          loading…
        </p>
      ) : (
        <>
          <Group title="Waiting for your approval" count={pending.length}>
            {pending.length === 0 ? (
              <Empty>Nothing waiting. New answers land here for you to approve.</Empty>
            ) : (
              pending.map((f) => (
                <FactCard key={f.id} fact={f} onChange={upsert} onRemoved={remove} toast={toast} />
              ))
            )}
          </Group>

          <Group title="Approved" count={approved.length}>
            {active >= maxActive && (
              <p role="alert" className="text-term-amber text-xs">
                The bot uses only the newest {maxActive} learned facts. Move older ones into
                your FAQ, projects or notes to keep them.
              </p>
            )}
            {approved.length === 0 ? (
              <Empty>The bot hasn’t learned anything yet.</Empty>
            ) : (
              approved.map((f) => (
                <FactCard key={f.id} fact={f} onChange={upsert} onRemoved={remove} toast={toast} />
              ))
            )}
          </Group>

          {rejected.length > 0 && (
            <details className="mb-6">
              <summary className="cursor-pointer text-term-dim text-xs mb-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright">
                Rejected ({rejected.length})
              </summary>
              <div className="space-y-2">
                {rejected.map((f) => (
                  <FactCard key={f.id} fact={f} onChange={upsert} onRemoved={remove} toast={toast} />
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </AdminSection>
  );
}

function Group({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} className="mb-6">
      <h2 className="text-term-bright text-base mb-2">
        {title} <span className="text-term-dim text-xs">({count})</span>
      </h2>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-term-dim text-xs border border-dashed border-term-line rounded px-3 py-5 text-center">
      {children}
    </p>
  );
}
