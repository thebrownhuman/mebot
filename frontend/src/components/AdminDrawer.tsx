import { useEffect, useState } from "react";
import { getLog, listSessions, type LogEntry, type SessionSummary } from "../lib/api";

interface Props {
  open: boolean;
}

export default function AdminDrawer({ open }: Props) {
  const [log, setLog] = useState<LogEntry[] | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);

  useEffect(() => {
    if (!open) return;
    getLog(50).then(setLog).catch(() => setLog([]));
    listSessions().then(setSessions).catch(() => setSessions([]));
  }, [open]);

  if (!open) return null;

  const totalQuestions = log?.filter((l) => l.event === "question").length ?? 0;

  return (
    <div className="border border-term-line2 bg-term-panel/95 rounded-lg p-3 mb-3">
      <h3 className="text-xs text-term-amber tracking-wide mb-2">// admin — activity from the db</h3>

      <div className="flex gap-4 text-xs text-term-dim mb-3">
        <span>
          sessions: <span className="text-term-fg">{sessions?.length ?? "…"}</span>
        </span>
        <span>
          questions logged: <span className="text-term-fg">{totalQuestions}</span>
        </span>
      </div>

      <div className="text-[11px] text-term-dim mb-1">recent events</div>
      <div className="max-h-[220px] overflow-y-auto text-xs font-mono">
        {log === null && <small className="text-term-dim">loading…</small>}
        {log?.length === 0 && <small className="text-term-dim">no activity yet</small>}
        {log?.map((e, i) => (
          <div key={i} className="flex gap-3 py-1 border-b border-term-line/50">
            <span className="text-term-dim shrink-0 w-[140px]">
              {new Date(e.ts * 1000).toLocaleString()}
            </span>
            <span
              className={
                "shrink-0 w-[150px] " +
                (e.event.startsWith("WARN") ? "text-term-err" : "text-term-amber")
              }
            >
              {e.event}
            </span>
            <span className="text-term-fg truncate">{e.detail ?? ""}</span>
            <span className="text-term-dim ml-auto shrink-0">{e.ip ?? ""}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
