import { useCallback, useEffect, useRef, useState } from "react";
import type { OrbState } from "../components/Orb";
import {
  ApiError,
  getHealth,
  getPublicConfig,
  getSessionMessages,
  getSessionUpdates,
  startSession,
  streamChat,
  type PublicConfig,
  type SessionUpdates,
} from "../lib/api";
import { splitStream } from "../lib/stream";

export type Line =
  | { kind: "recruiter"; text: string }
  | { kind: "me"; text: string; streaming?: boolean; thinking?: boolean }
  | { kind: "sys"; text: string; err?: boolean }
  // A reply the owner sent from Telegram.
  | { kind: "owner"; text: string; at: string }
  // "Leave your contact" suggestion after a question the bot couldn't answer.
  | { kind: "suggest" };

// The recruiter's session id survives reloads so owner replies still reach them.
export const SESSION_STORE_KEY = "mebot.session";

function readStoredSession(): string | null {
  try {
    return localStorage.getItem(SESSION_STORE_KEY);
  } catch {
    return null;
  }
}

function storeSession(id: string | null) {
  try {
    if (id) localStorage.setItem(SESSION_STORE_KEY, id);
    else localStorage.removeItem(SESSION_STORE_KEY);
  } catch {
    // private mode / blocked storage: replies only show while the tab stays open
  }
}

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
    suggested.current = false;
    if (remember.current) storeSession(id);
  }, []);
  const pendingName = useRef<string | undefined>(undefined);
  const pulseRef = useRef(0);
  const remember = useRef(false);
  const suggested = useRef(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => Math.max(0, c - 1)), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const sysLine = useCallback((text: string, err = false) => {
    setLines((l) => [...l, { kind: "sys", text, err }]);
  }, []);

  // remember: keep the session id in localStorage and resume it next time (recruiters).
  const connect = useCallback(
    async (recruiterName?: string, opts: { remember?: boolean } = {}) => {
      remember.current = Boolean(opts.remember);
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
      // The assistant introduces itself first (a server-rendered line, not an AI call).
      if (remember.current && cfg?.assistant_greeting) {
        setLines([{ kind: "me", text: cfg.assistant_greeting }]);
      }
      const stored = remember.current ? readStoredSession() : null;
      if (stored) {
        try {
          await getSessionUpdates(stored); // still exists?
          setSid(stored);
          setReady(true);
          return true;
        } catch (e) {
          if (e instanceof ApiError && e.status === 404) storeSession(null);
          // otherwise fall through to a fresh session
        }
      }
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

  // Owner replies + the "unanswered" flag from GET /api/session/{sid}/updates.
  const applyUpdates = useCallback((u: SessionUpdates) => {
    setLines((l) => {
      const seen = new Set(l.flatMap((x) => (x.kind === "owner" ? [x.at + x.text] : [])));
      const add: Line[] = u.messages
        .filter((m) => !seen.has(m.created_at + m.content))
        .map((m) => ({ kind: "owner", text: m.content, at: m.created_at }));
      if (u.unanswered && !suggested.current) {
        suggested.current = true;
        add.push({ kind: "suggest" });
      }
      return add.length ? [...l, ...add] : l;
    });
  }, []);

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
          const shown = splitStream(acc).text;
          setLines((l) => {
            const c = l.slice();
            c[c.length - 1] = { kind: "me", text: shown, streaming: true };
            return c;
          });
        });
        // A replace frame (leak-block / redaction) swaps the whole bubble.
        const { text: streamed, replace } = splitStream(acc);
        setLines((l) => {
          const c = l.slice();
          c[c.length - 1] = { kind: "me", text: (replace ?? streamed).trim() };
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
    applyUpdates,
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
