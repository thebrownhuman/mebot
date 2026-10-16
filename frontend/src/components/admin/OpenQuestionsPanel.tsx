import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listOpenQuestions, type OpenQuestionList } from "../../lib/api";

// Dashboard summary of the open-questions inbox (the full list lives on its own page).
export default function OpenQuestionsPanel() {
  const [data, setData] = useState<OpenQuestionList | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listOpenQuestions("open")
      .then(setData)
      .catch((e: Error) => {
        setData({ items: [], open_count: 0 });
        setError(e.message || "Could not load.");
      });
  }, []);

  const top = data?.items.slice(0, 5) ?? [];
  return (
    <section
      aria-labelledby="open-questions-title"
      className="border border-term-line2 bg-term-panel/95 rounded-lg p-3 mb-3"
    >
      <h3 id="open-questions-title" className="text-xs text-term-amber tracking-wide mb-1">
        // Open questions
      </h3>
      {data === null && <p className="text-term-dim text-xs">loading…</p>}
      {error && <p className="text-term-err text-xs">{error}</p>}
      {data && data.open_count === 0 && !error && (
        <p className="text-term-fg text-xs">No open questions. The bot answered everything.</p>
      )}
      {data && data.open_count > 0 && (
        <>
          <p className="text-term-dim text-xs mb-2">
            {data.open_count} {data.open_count === 1 ? "question" : "questions"} the bot couldn’t
            answer. Answer once and it will know next time.
          </p>
          <ul className="space-y-1.5 mb-2">
            {top.map((q) => (
              <li key={q.id} className="flex items-baseline gap-2 text-xs">
                <span className="text-term-fg flex-1 min-w-0 break-words">{q.question}</span>
                <span className="text-term-amber whitespace-nowrap">{q.ask_count}×</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <Link to="/admin/open-questions" className="text-term-bright underline text-xs">
        {data && data.open_count > 0 ? "Answer them" : "Open questions"}
      </Link>
    </section>
  );
}
