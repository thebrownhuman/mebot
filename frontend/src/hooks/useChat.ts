import { useCallback, useEffect, useRef, useState } from "react";
import type { OrbState } from "../components/Orb";
import {
  ApiError,
  getHealth,
  getPublicConfig,
  getSessionMessages,
  startSession,
  streamChat,
  type PublicConfig,
} from "../lib/api";

export type Line =
  | { kind: "recruiter"; text: string }
  | { kind: "me"; text: string; streaming?: boolean; thinking?: boolean }
  | { kind: "sys"; text: string; err?: boolean };

const DEFAULT_CONFIG: PublicConfig = {
  turnstile_site_key: null,
  max_message_chars: 1000,
  paused: false,
};
export const PAUSED_TEXT = "The assistant is paused right now. Please try again later.";

export function useChat() {
  const [conn, setConn] = useState<{ ok: boolean; text: string }>({ ok: false, text: "connecting…" });
  const [model, setModel] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  const [orbState, setOrbState] = useState<OrbState>("idle");
  const [config, setConfig] = useState<PublicConfig>(DEFAULT_CONFIG);
  // Site key while a Turnstile check must pass before the session can start.
  const [turnstileKey, setTurnstileKey] = useState<string | null>(null);
  // Seconds left before the server accepts another message (from Retry-After).
  const [cooldown, setCooldown] = useState(0);

  const sessionId = useRef<string | null>(null);
  // Same id as state, for UI that needs to re-render when it changes.
  const [sid, setSidState] = useState<string | null>(null);
  const setSid = useCallback((id: string | null) => {
    sessionId.current = id;
    setSidState(id);
  }, []);
  const pendingName = useRef<string | undefined>(undefined);
  const pulseRef = useRef(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => Math.max(0, c - 1)), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const sysLine = useCallback((text: string, err = false) => {
    setLines((l) => [...l, { kind: "sys", text, err }]);
  }, []);

  const connect = useCallback(
    async (recruiterName?: string) => {
      const h = await getHealth();
      if (!h.ready || !h.model) {
        setConn({ ok: false, text: h.message ?? "assistant unavailable" });
        return false;
      }
      const cfg = await getPublicConfig().catch(() => DEFAULT_CONFIG);
      setConfig(cfg ?? DEFAULT_CONFIG);
      setModel(h.model);
      if (cfg?.paused) {
        setConn({ ok: false, text: "paused" });
        sysLine(PAUSED_TEXT);
        return false;
      }
      setConn({ ok: true, text: "online · " + h.model });
      if (cfg?.turnstile_site_key) {
        pendingName.current = recruiterName;
        setTurnstileKey(cfg.turnstile_site_key);
        return true;
      }
      setReady(true);
      try {
        setSid(await startSession(recruiterName));
      } catch (e) {
        if (e instanceof ApiError) sysLine(e.message, true);
      }
      return true;
    },
    [sysLine, setSid],
  );

  // Turnstile passed: start the session with its token.
  const verify = useCallback(
    async (token: string) => {
      try {
        setSid(await startSession(pendingName.current, token));
        setTurnstileKey(null);
        setReady(true);
      } catch (e) {
        sysLine((e as Error).message || "Could not start the chat.", true);
      }
    },
    [sysLine, setSid],
  );

  const newSession = useCallback(async (recruiterName?: string) => {
    try {
      setSid(await startSession(recruiterName));
      setLines([]);
    } catch (e) {
      setLines((l) => [...l, { kind: "sys", text: "could not start session: " + (e as Error).message, err: true }]);
    }
  }, [setSid]);

  const send = useCallback(
    async (text: string) => {
      const t = text.trim();
      if (!t || busy || cooldown > 0 || !sessionId.current) return;
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
        if (e instanceof ApiError) {
          // Limits, pause, too long: the server's message is written for visitors.
          setLines((l) => [...l.slice(0, -1), { kind: "sys", text: e.message }]);
          if (e.retryAfter) setCooldown(e.retryAfter);
        } else {
          setLines((l) => {
            const c = l.slice();
            c[c.length - 1] = { kind: "me", text: "[connection error: " + (e as Error).message + "]" };
            return c;
          });
        }
      } finally {
        setBusy(false);
        setOrbState("idle");
      }
    },
    [busy, cooldown],
  );

  const loadSession = useCallback(async (sid: string) => {
    const msgs = await getSessionMessages(sid);
    setSid(sid);
    setLines(
      msgs.map((m) =>
        m.role === "user"
          ? ({ kind: "recruiter", text: m.content } as Line)
          : ({ kind: "me", text: m.content } as Line),
      ),
    );
  }, [setSid]);

  return {
    sessionId: sid,
    conn,
    model,
    ready,
    lines,
    busy,
    orbState,
    pulseRef,
    config,
    turnstileKey,
    cooldown,
    connect,
    verify,
    newSession,
    send,
    loadSession,
    setLines,
    sysLine,
  };
}

// small helper to scroll a ref to bottom on deps change
export function useAutoScroll(ref: React.RefObject<HTMLElement>, deps: unknown[]) {
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
