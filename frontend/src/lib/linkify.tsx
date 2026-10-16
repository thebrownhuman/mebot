import type { ReactNode } from "react";

// Makes http(s) URLs and e-mail addresses in a bot reply clickable. Only http(s) and
// mailto: ever become links: everything else (javascript:, data:, tel:) stays plain text.

const TOKEN = /(https?:\/\/[^\s<>"']+|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)/g;
const TRAILING = /[.,;:!?)\]}]+$/;

export function safeHref(token: string): string | null {
  if (/^https?:\/\//i.test(token)) {
    try {
      const u = new URL(token);
      return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
    } catch {
      return null;
    }
  }
  return /^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$/.test(token) ? `mailto:${token}` : null;
}

const linkCls =
  "underline text-term-bright break-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright";

export function linkify(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let n = 0;
  for (const m of text.matchAll(TOKEN)) {
    const start = m.index ?? 0;
    const trail = m[0].match(TRAILING)?.[0] ?? "";
    const token = trail ? m[0].slice(0, -trail.length) : m[0];
    const href = safeHref(token);
    if (!href) continue;
    if (start > last) out.push(text.slice(last, start));
    out.push(
      <a key={n++} href={href} target="_blank" rel="noopener noreferrer" className={linkCls}>
        {token}
      </a>,
    );
    last = start + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
