import { useRef, useState } from "react";
import Orb from "./Orb";
import Thinking from "./Thinking";
import Turnstile from "./Turnstile";
import { linkify } from "../lib/linkify";
import { useAutoScroll, type Line } from "../hooks/useChat";
import type { OrbState } from "./Orb";

interface Props {
  title: string;
  conn: { ok: boolean; text: string };
  lines: Line[];
  busy: boolean;
  ready: boolean;
  orbState: OrbState;
  pulseRef: React.MutableRefObject<number>;
  onSend: (text: string) => void;
  toolbar?: React.ReactNode;
  // Extra control in the title bar (e.g. "Leave my contact").
  headerAction?: React.ReactNode;
  drawers?: React.ReactNode;
  // Owner's max_message_chars (from /api/public/config).
  maxChars?: number;
  // Seconds until sending is allowed again after a rate limit.
  cooldown?: number;
  // When set, a Turnstile check must pass before the chat starts.
  turnstileKey?: string | null;
  onTurnstile?: (token: string) => void;
  onTurnstileError?: (message: string) => void;
  // Shown on owner-reply bubbles ("{first name} replied:").
  ownerName?: string;
  // Opens the contact form from the "unanswered" suggestion.
  onContact?: () => void;
}

export default function ChatScreen({
  title,
  conn,
  lines,
  busy,
  ready,
  orbState,
  pulseRef,
  onSend,
  toolbar,
  headerAction,
  drawers,
  maxChars = 1000,
  cooldown = 0,
  turnstileKey = null,
  onTurnstile,
  onTurnstileError,
  ownerName = "The owner",
  onContact,
}: Props) {
  const [input, setInput] = useState("");
  const screenRef = useRef<HTMLDivElement>(null);
  useAutoScroll(screenRef, [lines]);

  function submit() {
    if (!input.trim() || busy || cooldown > 0) return;
    onSend(input);
    setInput("");
  }

  return (
    <>
      <Orb state={orbState} pulseRef={pulseRef} />
      <div className="scanlines" />

      <div className="relative z-10 h-full flex flex-col max-w-[920px] mx-auto px-4 py-[18px]">
        <div className="flex items-center gap-3 border border-term-line bg-term-panel/70 backdrop-blur-sm rounded-t-lg px-3.5 py-2.5">
          <div className="flex gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-[#ff5f57]" />
            <span className="w-2.5 h-2.5 rounded-full bg-[#febc2e]" />
            <span className="w-2.5 h-2.5 rounded-full bg-[#28c840]" />
          </div>
          <span className="text-term-dim text-xs tracking-wide min-w-0 truncate">{title}</span>
          <span className="ml-auto flex items-center gap-2 text-xs text-term-dim shrink-0">
            <span
              className={
                "w-2 h-2 rounded-full " +
                (conn.ok ? "bg-term-bright shadow-[0_0_8px_#7dffb0]" : "bg-term-err shadow-[0_0_8px_#ff6b6b]")
              }
            />
            <span className="hidden sm:inline">{conn.text}</span>
          </span>
          {headerAction}
        </div>

        <div
          ref={screenRef}
          className="flex-1 min-h-0 border border-term-line border-t-0 bg-term-bg/75 backdrop-blur-sm overflow-y-auto px-4 pt-4 pb-3"
        >
          {toolbar}
          {drawers}
          {lines.map((l, i) => (
            <LineView key={i} line={l} ownerName={ownerName} onContact={onContact} />
          ))}
          {turnstileKey && (
            <div className="mb-3 text-term-amber text-xs">
              // quick check that you're human…
              <Turnstile
                siteKey={turnstileKey}
                onToken={(t) => onTurnstile?.(t)}
                onError={(m) => onTurnstileError?.(m)}
              />
            </div>
          )}
        </div>

        <div className="flex items-center gap-2.5 border border-term-line border-t-0 rounded-b-lg bg-term-panel/70 backdrop-blur-sm px-3.5 py-2.5">
          <span className="text-term-bright shrink-0">recruiter $</span>
          <input
            aria-label="your question"
            value={input}
            maxLength={maxChars}
            disabled={!ready}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="type a question and press enter…"
            className="flex-1 min-w-0 bg-transparent border-0 text-term-fg font-mono text-sm outline-none placeholder:text-term-dim"
          />
          {input.length > 0 && (
            <span
              aria-live="polite"
              className={
                "shrink-0 text-[11px] font-mono " +
                (input.length >= maxChars ? "text-term-err" : "text-term-dim")
              }
            >
              {input.length}/{maxChars}
            </span>
          )}
          <button
            onClick={submit}
            disabled={busy || !ready || cooldown > 0}
            className="bg-transparent border border-term-line2 text-term-bright font-mono text-xs px-3 py-1.5 rounded disabled:opacity-40"
          >
            {cooldown > 0 ? `wait ${cooldown}s` : "send"}
          </button>
        </div>
      </div>
    </>
  );
}

function LineView({
  line,
  ownerName,
  onContact,
}: {
  line: Line;
  ownerName: string;
  onContact?: () => void;
}) {
  if (line.kind === "suggest") {
    if (!onContact) return null;
    return (
      <div className="mb-3 text-term-amber text-xs">
        // {ownerName.split(/\s+/)[0]} can answer this personally.{" "}
        <button
          type="button"
          onClick={onContact}
          className="underline text-term-bright focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright"
        >
          leave your contact
        </button>
      </div>
    );
  }
  if (line.kind === "owner") {
    return (
      <div className="mb-3 whitespace-pre-wrap break-words leading-relaxed border-l-2 border-term-amber pl-3">
        <span className="block text-[11px] tracking-wider text-term-amber mb-0.5">
          {ownerName.split(/\s+/)[0]} replied:
        </span>
        <span className="text-term-fg">{linkify(line.text)}</span>
      </div>
    );
  }
  if (line.kind === "sys") {
    return <div className={"mb-3 " + (line.err ? "text-term-err" : "text-term-amber")}>// {line.text}</div>;
  }
  const who = line.kind === "recruiter" ? "recruiter" : "me";
  const whoColor = line.kind === "recruiter" ? "text-term-recruiter" : "text-term-bright";
  const bodyColor = line.kind === "recruiter" ? "text-[#a9c8ef]" : "text-term-fg";
  return (
    <div className="mb-3 whitespace-pre-wrap break-words leading-relaxed">
      <span className={"block text-[11px] tracking-wider opacity-65 mb-0.5 " + whoColor}>{who}</span>
      <span className={bodyColor}>
        {line.kind === "me" && line.thinking && !line.text ? (
          <Thinking />
        ) : (
          <>
            {line.kind === "me" ? linkify(line.text) : line.text}
            {line.kind === "me" && line.streaming && <span className="text-term-bright animate-blink">▋</span>}
          </>
        )}
      </span>
    </div>
  );
}
