import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import ContactModal from "../components/ContactModal";
import ContactPanel from "../components/ContactPanel";
import Thinking from "../components/Thinking";
import Turnstile from "../components/Turnstile";
import { useAutoScroll, useChat, type Line } from "../hooks/useChat";
import { useOwnerReplies } from "../hooks/useOwnerReplies";
import { ApiError, getWidgetConfig, widgetOpened, type WidgetConfig } from "../lib/api";
import { linkify } from "../lib/linkify";
import { framed, onParentMessage, postToParent } from "./bridge";

// The 3D orb (three.js) is a separate chunk, fetched only when the owner turned it on.
const Orb = lazy(() => import("../components/Orb"));

export type Mode = "floating" | "inline" | "page";

export function parseLocation(loc: { pathname: string; search: string }): { slug: string; mode: Mode } {
  const slug = decodeURIComponent(loc.pathname.replace(/^\/embed\//, "").split("/")[0] || "");
  const m = new URLSearchParams(loc.search).get("mode");
  return { slug, mode: m === "floating" || m === "inline" ? m : "page" };
}

const HEX = /^#[0-9a-f]{6}$/i;

// Black or white text on the owner's colour, whichever reads better.
export function onColor(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.4 ? "#111111" : "#ffffff";
}

function prefersDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

function applyTheme(cfg: WidgetConfig) {
  const root = document.documentElement;
  const color = HEX.test(cfg.primary_color) ? cfg.primary_color : "#0f766e";
  root.style.setProperty("--mb-primary", color);
  root.style.setProperty("--mb-on-primary", onColor(color));
  const dark = cfg.theme === "dark" || (cfg.theme === "auto" && prefersDark());
  root.classList.toggle("mb-dark", dark);
  document.title = cfg.title;
}

const ROLE: Partial<Record<Line["kind"], string>> = { recruiter: "user", me: "assistant", owner: "owner" };

export default function EmbedApp({ slug, mode }: { slug: string; mode: Mode }) {
  const [cfg, setCfg] = useState<WidgetConfig | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const load = useCallback(() => {
    setFailed(null);
    getWidgetConfig(slug)
      .then((c) => {
        applyTheme(c);
        setCfg(c);
      })
      .catch((e) =>
        setFailed(e instanceof ApiError && e.status === 404 ? "This chat is unavailable." : "Could not load the chat."),
      );
  }, [slug]);

  useEffect(load, [load]);

  if (failed) {
    return (
      <div role="alert" className="h-full grid place-items-center p-6 text-center text-sm text-[var(--mb-dim)]">
        <div>
          <p>{failed}</p>
          {failed.startsWith("Could not") && (
            <button
              type="button"
              onClick={load}
              className="mt-3 px-3 py-2 min-h-[44px] rounded-lg border border-[var(--mb-line)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--mb-primary)]"
            >
              Try again
            </button>
          )}
        </div>
      </div>
    );
  }
  if (!cfg) {
    return (
      <div aria-busy="true" aria-label="Loading chat" className="h-full flex flex-col gap-3 p-4">
        <div className="h-10 rounded-lg bg-[var(--mb-panel)] animate-pulse" />
        <div className="h-16 w-3/4 rounded-2xl bg-[var(--mb-bot)] animate-pulse" />
        <div className="mt-auto h-11 rounded-xl bg-[var(--mb-panel)] animate-pulse" />
      </div>
    );
  }
  return <Chat slug={slug} mode={mode} cfg={cfg} />;
}

function Chat({ slug, mode, cfg }: { slug: string; mode: Mode; cfg: WidgetConfig }) {
  const chat = useChat();
  const [open, setOpen] = useState(mode !== "floating");
  const [panelOpen, setPanelOpen] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const hostOrigin = useRef<string | null>(null);
  const reported = useRef(false);
  const unread = useRef(0);
  const posted = useRef(0);
  const ownerName = chat.config.owner_name || cfg.owner_first_name;
  const { pollNow } = useOwnerReplies(chat.sessionId, chat.applyUpdates, chat.ready);
  useAutoScroll(listRef, [chat.lines]);

  useEffect(() => {
    void chat.connect(undefined, { remember: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !chat.busy) pollNow();
    wasBusy.current = chat.busy;
  }, [chat.busy, pollNow]);

  // WIDGET_OPENED: once per chat, with the host origin the loader told us about.
  const report = useCallback(() => {
    if (reported.current || !hostOrigin.current || !chat.sessionId) return;
    reported.current = true;
    widgetOpened(slug, chat.sessionId, hostOrigin.current).catch(() => {});
  }, [slug, chat.sessionId]);

  useEffect(() => {
    if (open) report();
  }, [open, report]);

  useEffect(
    () =>
      onParentMessage((m) => {
        if (m.type === "open") {
          setOpen(true);
          unread.current = 0;
          postToParent("unread", { count: 0 });
          setTimeout(() => inputRef.current?.focus(), 0);
        } else if (m.type === "close") {
          setOpen(false);
        } else if (m.type === "host-info" && typeof m.payload?.origin === "string") {
          hostOrigin.current = m.payload.origin.slice(0, 300);
          if (mode === "inline") report();
        }
      }),
    [mode, report],
  );

  useEffect(() => {
    postToParent("ready");
  }, []);

  // Role-only "message" events for the host's JS API, and the unread badge.
  useEffect(() => {
    const lines = chat.lines;
    for (; posted.current < lines.length; posted.current++) {
      const l = lines[posted.current];
      if (l.kind === "me" && (l.streaming || l.thinking)) break; // count it once done
      const role = ROLE[l.kind];
      if (!role) continue;
      postToParent("message", { role });
      if (l.kind === "owner" && !open) {
        unread.current += 1;
        postToParent("unread", { count: unread.current });
      }
    }
  }, [chat.lines, open]);

  // Inline mode grows with the conversation (the loader clamps it).
  useEffect(() => {
    if (mode !== "inline" || typeof ResizeObserver === "undefined" || !rootRef.current) return;
    const ro = new ResizeObserver(() => {
      postToParent("resize", { height: Math.ceil(rootRef.current?.scrollHeight ?? 0) });
    });
    ro.observe(rootRef.current);
    return () => ro.disconnect();
  }, [mode]);

  function close() {
    setOpen(false);
    postToParent("close");
  }

  function submit(text = input) {
    if (!text.trim() || chat.busy || chat.cooldown > 0 || !chat.ready) return;
    void chat.send(text);
    if (text === input) setInput("");
  }

  // Links open in a new tab on the host page (http(s)/mailto only, checked there too).
  function onClickCapture(e: React.MouseEvent) {
    const a = (e.target as HTMLElement).closest?.("a[href]") as HTMLAnchorElement | null;
    if (!a || !framed() || !listRef.current?.contains(a)) return;
    e.preventDefault();
    postToParent("open-link", { href: a.href });
  }

  const asked = chat.lines.some((l) => l.kind === "recruiter");
  const chips = !asked && chat.ready ? cfg.suggested_questions : [];
  const maxChars = chat.config.max_message_chars || cfg.max_message_chars;

  return (
    <div
      ref={rootRef}
      onClickCapture={onClickCapture}
      onKeyDown={(e) => {
        if (e.key === "Escape" && mode === "floating" && !panelOpen && !contactOpen) close();
      }}
      className={
        "relative flex flex-col bg-[var(--mb-bg)] text-[var(--mb-fg)] " +
        (mode === "inline" ? "min-h-[420px] border border-[var(--mb-line)] rounded-xl overflow-hidden" : "h-[100dvh]")
      }
    >
      {cfg.show_orb && (
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 opacity-30 overflow-hidden">
          <Suspense fallback={null}>
            <Orb state={chat.orbState} pulseRef={chat.pulseRef} />
          </Suspense>
        </div>
      )}
      <header className="relative z-10 flex items-center gap-3 px-4 py-3 bg-[var(--mb-primary)] text-[var(--mb-on-primary)]">
        {cfg.avatar_url ? (
          <img src={cfg.avatar_url} alt="" className="w-9 h-9 rounded-full object-cover shrink-0" />
        ) : (
          <span
            aria-hidden="true"
            className="w-9 h-9 rounded-full grid place-items-center font-semibold bg-black/15 shrink-0"
          >
            {cfg.owner_first_name.slice(0, 1).toUpperCase()}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h1 className="text-[15px] font-semibold leading-tight truncate">{cfg.title}</h1>
          <p className="text-xs opacity-80 truncate">{chat.conn.ok ? "Online" : chat.conn.text}</p>
        </div>
        {chat.ready && (
          <button
            type="button"
            aria-haspopup="dialog"
            onClick={() => setPanelOpen(true)}
            className="shrink-0 text-xs font-medium px-3 min-h-[36px] rounded-full bg-black/15 hover:bg-black/25 focus-visible:outline focus-visible:outline-2 focus-visible:outline-current"
          >
            Contact
          </button>
        )}
        {mode === "floating" && (
          <button
            type="button"
            aria-label="Close chat"
            onClick={close}
            className="shrink-0 w-11 h-11 -mr-2 grid place-items-center rounded-full hover:bg-black/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-current"
          >
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        )}
      </header>

      <div
        ref={listRef}
        aria-live="polite"
        className={
          "relative z-10 flex-1 overflow-y-auto px-4 py-4 space-y-3 " +
          (mode === "inline" ? "max-h-[520px]" : "min-h-0")
        }
      >
        {chat.lines.map((l, i) => (
          <Bubble key={i} line={l} ownerName={ownerName} onContact={() => setContactOpen(true)} />
        ))}
        {chat.turnstileKey && (
          <div className="text-xs text-[var(--mb-dim)]">
            Quick check that you're human…
            <Turnstile
              siteKey={chat.turnstileKey}
              onToken={(t) => void chat.verify(t)}
              onError={(m) => chat.sysLine(m, true)}
            />
          </div>
        )}
        {chips.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1" aria-label="Suggested questions">
            {chips.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => submit(q)}
                className="text-left text-[13px] px-3 py-2 min-h-[36px] rounded-full border border-[var(--mb-primary)] text-[var(--mb-fg)] hover:bg-[var(--mb-panel)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--mb-primary)]"
              >
                {q}
              </button>
            ))}
          </div>
        )}
      </div>

      <form
        className="relative z-10 flex items-center gap-2 px-3 py-3 border-t border-[var(--mb-line)] bg-[var(--mb-bg)]"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <input
          ref={inputRef}
          aria-label="Your question"
          value={input}
          maxLength={maxChars}
          disabled={!chat.ready}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`Ask about ${cfg.owner_first_name}…`}
          className="flex-1 min-w-0 h-11 px-3.5 rounded-xl bg-[var(--mb-panel)] border border-[var(--mb-line)] text-[15px] outline-none focus:border-[var(--mb-primary)] disabled:opacity-60 placeholder:text-[var(--mb-dim)]"
        />
        {input.length > maxChars * 0.8 && (
          <span aria-live="polite" className="text-[11px] text-[var(--mb-dim)] shrink-0">
            {input.length}/{maxChars}
          </span>
        )}
        <button
          type="submit"
          disabled={chat.busy || !chat.ready || chat.cooldown > 0 || !input.trim()}
          className="shrink-0 h-11 px-4 rounded-xl font-medium text-sm bg-[var(--mb-primary)] text-[var(--mb-on-primary)] disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--mb-primary)]"
        >
          {chat.cooldown > 0 ? `Wait ${chat.cooldown}s` : "Send"}
        </button>
      </form>

      {panelOpen && (
        <ContactPanel
          ownerName={ownerName}
          onClose={() => setPanelOpen(false)}
          onLeave={() => {
            setPanelOpen(false);
            setContactOpen(true);
          }}
        />
      )}
      {contactOpen && (
        <ContactModal ownerName={ownerName} sessionId={chat.sessionId} onClose={() => setContactOpen(false)} />
      )}
    </div>
  );
}

function Bubble({ line, ownerName, onContact }: { line: Line; ownerName: string; onContact: () => void }) {
  const first = ownerName.split(/\s+/)[0];
  if (line.kind === "suggest") {
    return (
      <p className="text-[13px] text-[var(--mb-dim)]">
        {first} can answer this personally.{" "}
        <button type="button" onClick={onContact} className="underline font-medium text-[var(--mb-fg)]">
          Leave your contact
        </button>
      </p>
    );
  }
  if (line.kind === "sys") {
    return (
      <p role={line.err ? "alert" : undefined} className={"text-[13px] " + (line.err ? "text-[var(--mb-err)]" : "text-[var(--mb-dim)]")}>
        {line.text}
      </p>
    );
  }
  if (line.kind === "recruiter") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md px-3.5 py-2 text-[15px] bg-[var(--mb-primary)] text-[var(--mb-on-primary)]">
          {line.text}
        </p>
      </div>
    );
  }
  const owner = line.kind === "owner";
  return (
    <div className="flex">
      <div
        className={
          "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-bl-md px-3.5 py-2 text-[15px] bg-[var(--mb-bot)] [&_a]:underline [&_a]:break-all [&_a]:!text-inherit" +
          (owner ? "border-l-4 border-[var(--mb-primary)]" : "")
        }
      >
        {owner && <span className="block text-[11px] font-semibold text-[var(--mb-dim)] mb-0.5">{first} replied</span>}
        {line.kind === "me" && line.thinking && !line.text ? <Thinking /> : linkify(line.text)}
      </div>
    </div>
  );
}
