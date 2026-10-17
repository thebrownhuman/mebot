// mebot SDK core: draws a launcher in a shadow root and hosts the chat in the existing,
// isolated /embed iframe. Chat never renders in the host DOM; the host page only ever
// learns ready/open/close and message roles, never content.

import { envelope, parseChild, safeLink } from "./protocol";
import { cleanTheme, iframeParams, type Theme } from "./theme";

export type MebotEvent = "ready" | "open" | "close" | "message";
type Handler = (detail?: unknown) => void;

export interface MebotOptions extends Theme {
  botKey: string; // public bot key, pk_...
  host?: string; // mebot server origin; defaults to where the SDK script came from
  position?: "right" | "left";
  open?: boolean;
}

export interface MebotInstance {
  open(): void;
  close(): void;
  toggle(): void;
  on(event: MebotEvent, fn: Handler): () => void;
  destroy(): void;
}

// Public keys only. Anything else (and any option we don't know) is refused, so an LLM
// key can never be passed in, let alone forwarded.
const KEY = /^pk_[a-z0-9]{8,64}$/i;
const OPTIONS = [
  "botKey", "host", "position", "open", "theme", "accent", "radius", "font",
  "launcherSize", "offsetX", "offsetY",
];
const Z = "2147483000";

export function validate(opts: MebotOptions, fallbackHost?: string): Required<Pick<MebotOptions, "botKey" | "host">> {
  for (const k of Object.keys(opts || {})) {
    if (!OPTIONS.includes(k)) throw new TypeError(`mebot: unknown option "${k}"`);
  }
  if (!opts || typeof opts.botKey !== "string" || !KEY.test(opts.botKey)) {
    throw new TypeError("mebot: botKey must be your public bot key (pk_...), never an API key");
  }
  let host: string;
  try {
    host = new URL(opts.host || fallbackHost || "").origin;
  } catch {
    throw new TypeError("mebot: host must be your mebot server URL, e.g. https://mebot.example.com");
  }
  if (!/^https?:$/.test(new URL(host).protocol)) throw new TypeError("mebot: host must be http(s)");
  return { botKey: opts.botKey, host };
}

const ICON =
  '<svg aria-hidden="true" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>';

const FONT_CSS: Record<string, string> = {
  system: 'system-ui,-apple-system,"Segoe UI",sans-serif',
  serif: "Georgia,serif",
  mono: "ui-monospace,monospace",
  rounded: 'ui-rounded,"SF Pro Rounded",system-ui,sans-serif',
};

function styles(side: string, t: Theme): string {
  const s = t.launcherSize ?? 56;
  const x = t.offsetX ?? 20;
  const y = t.offsetY ?? 20;
  const r = t.radius ?? 16;
  return `:host{all:initial}
.l{position:fixed;bottom:${y}px;${side}:${x}px;z-index:${Z};display:grid;place-items:center;width:${s}px;height:${s}px;border:0;border-radius:${s / 2}px;background:var(--c);color:var(--t);font:600 15px/1 ${FONT_CSS[t.font ?? "system"]};box-shadow:0 6px 24px rgba(0,0,0,.22);cursor:pointer}
.l:focus-visible{outline:3px solid var(--c);outline-offset:3px}
.p{position:fixed;bottom:${y + s + 12}px;${side}:${x}px;z-index:${Z};width:380px;height:600px;max-height:calc(100vh - ${y + s + 32}px);border-radius:${r}px;overflow:hidden;box-shadow:0 12px 48px rgba(0,0,0,.28);background:#fff}
.p[hidden]{display:none}
.p iframe{width:100%;height:100%;border:0;display:block}
@media (max-width:479px){.p{inset:0;width:100%;height:100dvh;max-height:none;border-radius:0}}`;
}

function textOn(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  return 0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255) > 160 ? "#111" : "#fff";
}

export function createMebot(opts: MebotOptions, fallbackHost?: string, win: Window = window): MebotInstance {
  const { botKey, host } = validate(opts, fallbackHost);
  const theme = cleanTheme(opts as unknown as Record<string, unknown>);
  const handlers: Partial<Record<MebotEvent, Handler[]>> = {};
  const doc = win.document;
  let frame: HTMLIFrameElement | null = null;
  let hostEl: HTMLElement | null = null;
  let launcher: HTMLButtonElement | null = null;
  let panel: HTMLElement | null = null;
  let ready = false;
  let isOpen = false;
  let dead = false;
  let wantOpen = !!opts.open;

  const emit = (e: MebotEvent, d?: unknown) => (handlers[e] || []).slice().forEach((fn) => fn(d));
  const post = (type: "open" | "close" | "host-info", payload?: Record<string, unknown>) => {
    if (frame && ready) frame.contentWindow?.postMessage(envelope(type, payload), host);
  };

  function onMessage(e: MessageEvent) {
    // Only our own iframe, from the mebot server's origin.
    if (!frame || e.origin !== host || e.source !== frame.contentWindow) return;
    const m = parseChild(e.data);
    if (!m) return;
    const p = m.payload || {};
    if (m.type === "ready") {
      ready = true;
      post("host-info", { origin: win.location.origin });
      if (isOpen) post("open");
      emit("ready");
    } else if (m.type === "close") {
      close();
    } else if (m.type === "message") {
      if (p.role === "user" || p.role === "assistant" || p.role === "owner") emit("message", { role: p.role });
    } else if (m.type === "open-link") {
      const href = safeLink(p.href);
      if (href) win.open(href, "_blank", "noopener,noreferrer");
    }
  }

  function open() {
    if (dead) return;
    if (!panel || !launcher) {
      wantOpen = true;
      return;
    }
    if (isOpen) return;
    isOpen = true;
    panel.hidden = false;
    launcher.setAttribute("aria-expanded", "true");
    post("open");
    frame?.focus();
    emit("open");
  }

  function close() {
    if (!isOpen || !panel || !launcher) return;
    isOpen = false;
    panel.hidden = true;
    launcher.setAttribute("aria-expanded", "false");
    post("close");
    launcher.focus();
    emit("close");
  }

  const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();

  function mount(cfg: { title?: string; primary_color?: string; position?: string }) {
    if (dead) return;
    const color = theme.accent || (/^#[0-9a-f]{6}$/i.test(cfg.primary_color || "") ? cfg.primary_color! : "#0f766e");
    const side = opts.position || (cfg.position === "left" ? "left" : "right");
    const title = String(cfg.title || "Chat").slice(0, 120);
    hostEl = doc.createElement("div");
    hostEl.setAttribute("data-mebot-sdk", "");
    const root = hostEl.attachShadow({ mode: "open" });
    const style = doc.createElement("style");
    style.textContent = styles(side === "left" ? "left" : "right", theme);
    launcher = doc.createElement("button");
    launcher.type = "button";
    launcher.className = "l";
    launcher.setAttribute("aria-label", `Chat with ${title}`);
    launcher.setAttribute("aria-expanded", "false");
    launcher.setAttribute("aria-haspopup", "dialog");
    launcher.style.cssText = `--c:${color};--t:${textOn(color)}`;
    launcher.innerHTML = ICON;
    launcher.addEventListener("click", () => (isOpen ? close() : open()));
    panel = doc.createElement("div");
    panel.className = "p";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", title);
    panel.hidden = true;
    frame = doc.createElement("iframe");
    frame.src = `${host}/embed/${encodeURIComponent(botKey)}?mode=floating${iframeParams(theme)}`;
    frame.title = "Chat";
    frame.setAttribute("allow", "clipboard-write");
    frame.setAttribute("referrerpolicy", "origin");
    panel.appendChild(frame);
    root.append(style, launcher, panel);
    doc.body.appendChild(hostEl);
    doc.addEventListener("keydown", onKey);
    if (wantOpen) open();
  }

  win.addEventListener("message", onMessage);
  fetch(`${host}/api/public/widget/${encodeURIComponent(botKey)}/launcher`, { credentials: "omit" })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(mount)
    .catch(() => {
      if (!dead) console.warn(`[mebot] chat unavailable here: is ${win.location.origin} on the allowed sites list?`);
      destroy();
    });

  function destroy() {
    dead = true;
    win.removeEventListener("message", onMessage);
    doc.removeEventListener("keydown", onKey);
    hostEl?.remove();
    hostEl = launcher = panel = frame = null;
  }

  return {
    open,
    close,
    toggle: () => (isOpen ? close() : open()),
    on(event, fn) {
      (handlers[event] = handlers[event] || []).push(fn);
      return () => {
        handlers[event] = (handlers[event] || []).filter((h) => h !== fn);
      };
    },
    destroy,
  };
}
