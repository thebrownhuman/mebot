import { useEffect, useState } from "react";
import { listSessions, type SessionSummary } from "../lib/api";

interface Props {
  open: boolean;
  onPick: (sid: string) => void;
}

export default function SessionsDrawer({ open, onPick }: Props) {
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);

  useEffect(() => {
    if (open) listSessions().then(setSessions).catch(() => setSessions([]));
  }, [open]);

  if (!open) return null;
  return (
    <div className="border border-term-line2 bg-term-panel/95 rounded-lg p-3 mb-3">
      <h3 className="text-xs text-term-amber tracking-wide mb-2">// past sessions (stored in db)</h3>
      {sessions === null && <small className="text-term-dim">loading…</small>}
      {sessions?.length === 0 && <small className="text-term-dim">no sessions yet</small>}
      <div className="text-xs">
        {sessions?.map((s) => (
          <button
            key={s.id}
            onClick={() => onPick(s.id)}
            className="w-full text-left flex justify-between gap-3 px-2.5 py-1.5 border border-term-line rounded mb-1.5 hover:border-term-bright"
          >
            <span>
              {s.id.slice(0, 8)} · {s.turns} msgs
            </span>
            <span className="text-term-dim">
              {new Date(s.started_at * 1000).toLocaleString()}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
