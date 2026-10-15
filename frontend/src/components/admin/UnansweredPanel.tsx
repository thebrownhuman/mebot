import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getUnanswered, type UnansweredItem } from "../../lib/api";

// Latest questions the bot couldn't answer from the profile (full analytics come later).
export default function UnansweredPanel({ onOpen }: { onOpen: (sessionId: string) => void }) {
  const [items, setItems] = useState<UnansweredItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getUnanswered(10)
      .then(setItems)
      .catch((e: Error) => {
        setItems([]);
        setError(e.message || "Could not load.");
      });
  }, []);

  return (
    <section
      aria-labelledby="unanswered-title"
      className="border border-term-line2 bg-term-panel/95 rounded-lg p-3 mb-3"
    >
      <h3 id="unanswered-title" className="text-xs text-term-amber tracking-wide mb-1">
        // Unanswered questions
      </h3>
      <p className="text-term-dim text-xs mb-2">
        Add this to your FAQ or profile so the bot can answer next time.{" "}
        <Link to="/admin/profile/faq" className="text-term-bright underline">
          Open FAQ
        </Link>
      </p>
      {items === null && <p className="text-term-dim text-xs">loading…</p>}
      {error && <p className="text-term-err text-xs">{error}</p>}
      {items && items.length === 0 && !error && (
        <p className="text-term-fg text-xs">Nothing unanswered yet.</p>
      )}
      {items && items.length > 0 && (
        <ul className="space-y-1.5">
          {items.map((it, i) => (
            <li key={`${it.created_at}-${i}`} className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-term-fg flex-1 min-w-[10rem] break-words">{it.question}</span>
              <time className="text-term-dim" dateTime={it.created_at}>
                {new Date(it.created_at).toLocaleString()}
              </time>
              {it.session_id && (
                <button
                  type="button"
                  aria-label={`Open session for: ${it.question ?? ""}`}
                  onClick={() => onOpen(it.session_id!)}
                  className="font-mono px-2 py-1 rounded border border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright"
                >
                  open session
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
