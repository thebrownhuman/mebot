import { useCallback, useEffect, useRef, useState } from "react";
import type { OrbState } from "../components/Orb";
import { getHealth, startSession, streamChat, getSessionMessages } from "../lib/api";

export type Line =
  | { kind: "recruiter"; text: string }
  | { kind: "me"; text: string; streaming?: boolean; thinking?: boolean }
  | { kind: "sys"; text: string; err?: boolean };

export function useChat() {
  const [conn, setConn] = useState<{ ok: boolean; text: string }>({ ok: false, text: "connecting…" });
  const [model, setModel] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  const [orbState, setOrbState] = useState<OrbState>("idle");

  const sessionId = useRef<string | null>(null);
  const pulseRef = useRef(0);

  const connect = useCallback(async (recruiterName?: string) => {
    const h = await getHealth();
    if (!h.ollama) {
      setConn({ ok: false, text: "offline — model unreachable" });
      return false;
    }
    if (!h.model) {
      setConn({ ok: false, text: h.message ?? "no model" });
      return false;
    }
    setModel(h.model);
    setConn({ ok: true, text: "online · " + h.model });
    setReady(true);
    try {
      sessionId.current = await startSession(recruiterName);
    } catch {
      /* non-fatal */
    }
    return true;
  }, []);

  const newSession = useCallback(async (recruiterName?: string) => {
    try {
      sessionId.current = await startSession(recruiterName);
      setLines([]);
    } catch (e) {
      setLines((l) => [...l, { kind: "sys", text: "could not start session: " + (e as Error).message, err: true }]);
    }
  }, []);

  const send = useCallback(
    async (text: string) => {
      const t = text.trim();
      if (!t || busy || !sessionId.current) return;
      setLines((l) => [
        ...l,
        { kind: "recruiter", text: t },
        { kind: "me", text: "", thinking: true },
      ]);
      setBusy(true);
      setOrbState("think");
      try {
        let acc = "";
        let first = true;
        await streamChat(sessionId.current, t, (chunk) => {
          if (first) {
            setOrbState("talk");
            first = false;
          }
          acc += chunk;
          pulseRef.current = Math.min(pulseRef.current + 0.5, 1.2);
          setLines((l) => {
            const c = l.slice();
            c[c.length - 1] = { kind: "me", text: acc, streaming: true };
            return c;
          });
        });
        setLines((l) => {
          const c = l.slice();
          c[c.length - 1] = { kind: "me", text: acc.trim() };
          return c;
        });
      } catch (e) {
        setLines((l) => {
          const c = l.slice();
          c[c.length - 1] = { kind: "me", text: "[connection error: " + (e as Error).message + "]" };
          return c;
        });
      } finally {
        setBusy(false);
        setOrbState("idle");
      }
    },
    [busy],
  );

  const loadSession = useCallback(async (sid: string) => {
    const msgs = await getSessionMessages(sid);
    sessionId.current = sid;
    setLines(
      msgs.map((m) =>
        m.role === "user"
          ? ({ kind: "recruiter", text: m.content } as Line)
          : ({ kind: "me", text: m.content } as Line),
      ),
    );
  }, []);

  return {
    conn,
    model,
    ready,
    lines,
    busy,
    orbState,
    pulseRef,
    connect,
    newSession,
    send,
    loadSession,
    setLines,
  };
}

// small helper to scroll a ref to bottom on deps change
export function useAutoScroll(ref: React.RefObject<HTMLElement>, deps: unknown[]) {
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
