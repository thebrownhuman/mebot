import { useCallback, useEffect, useState } from "react";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import FactCard from "../../components/admin/FactCard";
import { inputCls } from "../../components/admin/fields";
import {
  answerOpenQuestion,
  dismissOpenQuestion,
  listOpenQuestions,
  neverAnswerOpenQuestion,
  type LearnedFact,
  type OpenQuestion,
} from "../../lib/api";

const btn =
  "font-mono text-xs px-2.5 py-1.5 rounded border focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-40";

// Questions the bot couldn't answer, grouped with their rephrasings. The owner answers
// once; an AI turns it into a clean fact; the owner approves; the bot knows it.
export default function OpenQuestionsPage() {
  const { toast, refreshOpenCount } = useAdmin();
  const [items, setItems] = useState<OpenQuestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listOpenQuestions("open")
      .then((r) => {
        setItems(r.items);
        setError(null);
      })
      .catch((e: Error) => {
        setItems([]);
        setError(e.message || "Could not load open questions.");
      });
  }, []);
  useEffect(load, [load]);

  function gone(id: string) {
    setItems((xs) => (xs ?? []).filter((x) => x.id !== id));
    refreshOpenCount();
  }

  return (
    <AdminSection
      title="Open questions"
      intro="Professional questions recruiters asked that the bot couldn’t answer, most asked first. Answer once and the bot will know next time. Personal questions never show up here."
    >
      {error && (
        <p role="alert" className="text-term-err text-xs mb-3">
          {error}
        </p>
      )}
      {items === null ? (
        <p role="status" className="text-term-dim text-xs">
          loading…
        </p>
      ) : items.length === 0 ? (
        !error && (
          <p className="text-term-dim text-xs border border-dashed border-term-line rounded px-3 py-6 text-center">
            No open questions. When a recruiter asks something the profile can’t answer, it
            lands here.
          </p>
        )
      ) : (
        <ul className="space-y-3">
          {items.map((q) => (
            <li key={q.id}>
              <QuestionCard q={q} onGone={() => gone(q.id)} toast={toast} />
            </li>
          ))}
        </ul>
      )}
    </AdminSection>
  );
}

function QuestionCard({
  q,
  onGone,
  toast,
}: {
  q: OpenQuestion;
  onGone: () => void;
  toast: (t: string) => void;
}) {
  const [answer, setAnswer] = useState("");
  const [fact, setFact] = useState<LearnedFact | null>(null);
  const [busy, setBusy] = useState<"answer" | "dismiss" | "never" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    if (!answer.trim()) return;
    setBusy("answer");
    setError(null);
    try {
      setFact(await answerOpenQuestion(q.id, answer.trim()));
    } catch (e) {
      setError((e as Error).message || "Could not clean up your answer.");
    } finally {
      setBusy(null);
    }
  }

  async function dismiss() {
    setBusy("dismiss");
    setError(null);
    try {
      await dismissOpenQuestion(q.id);
      toast("Dismissed");
      onGone();
    } catch (e) {
      setError((e as Error).message || "Could not dismiss.");
      setBusy(null);
    }
  }

  async function never() {
    if (!window.confirm("Stop the bot discussing this? It will be added to Avoid topics.")) return;
    setBusy("never");
    setError(null);
    try {
      await neverAnswerOpenQuestion(q.id);
      toast("Added to Avoid topics");
      onGone();
    } catch (e) {
      setError((e as Error).message || "Could not save.");
      setBusy(null);
    }
  }

  function changed(f: LearnedFact) {
    if (f.status === "approved") onGone();
    else setFact(f.status === "rejected" ? null : f);
  }

  return (
    <article
      aria-label={`question: ${q.question}`}
      className="border border-term-line rounded bg-term-panel/60 px-3 py-3 text-xs"
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <h2 className="flex-1 min-w-[12rem] text-term-bright text-sm break-words">{q.question}</h2>
        <span className="text-term-amber whitespace-nowrap">asked {q.ask_count}×</span>
        <time dateTime={q.last_asked_at} className="text-term-dim whitespace-nowrap">
          last{" "}
          {new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
            new Date(q.last_asked_at),
          )}
        </time>
      </div>

      {fact ? (
        <div className="mt-3">
          <FactCard fact={fact} onChange={changed} toast={toast} />
        </div>
      ) : (
        <form onSubmit={submit} className="mt-3">
          <label htmlFor={`answer-${q.id}`} className="block text-term-dim mb-1">
            Your answer
          </label>
          <textarea
            id={`answer-${q.id}`}
            value={answer}
            rows={2}
            maxLength={2000}
            placeholder="e.g. Bangalore, open to remote"
            onChange={(e) => setAnswer(e.target.value)}
            className={`${inputCls} border-term-line2 resize-y`}
          />
          <div className="flex flex-wrap gap-2 mt-2">
            <button
              type="submit"
              disabled={busy !== null || !answer.trim()}
              className={`${btn} border-term-bright text-term-bright hover:bg-term-bright/10`}
            >
              {busy === "answer" ? "cleaning up…" : "Answer"}
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void dismiss()}
              className={`${btn} border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright`}
            >
              {busy === "dismiss" ? "…" : "Dismiss"}
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void never()}
              className={`${btn} border-term-line2 text-term-dim hover:text-term-err hover:border-term-err`}
            >
              Never answer this
            </button>
          </div>
        </form>
      )}
      {error && (
        <p role="alert" className="text-term-err mt-2">
          {error}
        </p>
      )}
    </article>
  );
}
