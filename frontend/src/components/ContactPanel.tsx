import { useCallback, useEffect, useRef, useState } from "react";
import { kindMeta, type PublicChannel } from "../lib/channels";
import { getContactChannels } from "../lib/api";
import { safeHref } from "../lib/linkify";

// "Contact" in the chat header: the channels the owner chose to share, plus the
// "Leave my contact" form. Only http(s), mailto:, tel: hrefs from the server are used.

const linkCls =
  "flex items-center gap-2.5 border border-term-line2 rounded px-3 py-2.5 min-h-[44px] text-sm text-term-fg hover:border-term-bright focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright";

function hrefOk(href: string | null): string | null {
  if (!href) return null;
  if (/^(mailto|tel):/i.test(href)) return href;
  return safeHref(href);
}

export default function ContactPanel({
  ownerName,
  onLeave,
  onClose,
}: {
  ownerName: string;
  onLeave: () => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<PublicChannel[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);

  const load = useCallback(() => {
    setItems(null);
    setError(null);
    getContactChannels()
      .then(setItems)
      .catch((e: Error) => {
        setItems([]);
        setError(e.message || "Could not load the contact options.");
      });
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    opener.current = document.activeElement;
    closeRef.current?.focus();
    return () => {
      (opener.current as HTMLElement | null)?.focus?.();
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 p-0 sm:p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="contact-panel-title"
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
        className="w-full sm:max-w-md max-h-[100dvh] overflow-y-auto border border-term-line bg-term-panel rounded-t-lg sm:rounded-lg px-4 py-4 font-mono"
      >
        <div className="flex items-start gap-3 mb-3">
          <h2 id="contact-panel-title" className="flex-1 text-term-bright text-sm">
            Get in touch with {ownerName}
          </h2>
          <button
            ref={closeRef}
            type="button"
            aria-label="close"
            onClick={onClose}
            className="text-term-dim hover:text-term-fg text-xs px-2 py-1 rounded border border-term-line2"
          >
            ✕
          </button>
        </div>

        {items === null && (
          <div role="status" className="space-y-2" aria-label="loading contact options">
            {[0, 1, 2].map((k) => (
              <div
                key={k}
                className="h-11 rounded border border-term-line bg-term-bg/60 animate-pulse"
              />
            ))}
          </div>
        )}
        {error && (
          <div role="alert" className="text-term-err text-xs mb-3">
            {error}{" "}
            <button type="button" onClick={load} className="underline text-term-bright">
              try again
            </button>
          </div>
        )}
        {items && items.length === 0 && !error && (
          <p className="text-term-dim text-xs mb-3">
            {ownerName} hasn’t shared direct contact options. Leave your details and they’ll get
            back to you.
          </p>
        )}
        {items && items.length > 0 && (
          <ul className="space-y-2 mb-4">
            {items.map((c) => {
              const meta = kindMeta(c.kind);
              const href = hrefOk(c.href);
              const body = (
                <>
                  <span aria-hidden="true" className="w-5 text-center">
                    {meta.icon}
                  </span>
                  <span className="text-term-dim text-xs shrink-0">{c.label}</span>
                  <span className="min-w-0 break-all">{c.display}</span>
                </>
              );
              return (
                <li key={`${c.kind}-${c.display}`}>
                  {href ? (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`${c.label}: ${c.display}`}
                      className={linkCls}
                    >
                      {body}
                    </a>
                  ) : (
                    <div className={linkCls}>{body}</div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <button
          type="button"
          onClick={onLeave}
          className="w-full font-mono text-xs px-3 py-2.5 min-h-[44px] rounded border border-term-bright text-term-bright bg-term-bright/10 hover:bg-term-bright/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright"
        >
          Leave my contact
        </button>
        <p className="text-term-dim text-[11px] mt-2">
          Leave your details and {ownerName} will get back to you.
        </p>
      </div>
    </div>
  );
}
