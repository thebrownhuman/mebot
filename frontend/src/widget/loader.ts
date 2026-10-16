// The embed loader: <script src=".../widget/v1.js" data-bot="slug" async></script>.
// Vanilla TS, no dependencies, built to a small ES2017 IIFE. Draws a launcher in a
// shadow root (host CSS can't reach it) and creates the chat iframe on first open.

import { envelope, parseChild, safeLink, type ChildType, type ParentType } from "./protocol";

export const READY_TIMEOUT_MS = 8000;
const Z = "2147483000";
const MIN_INLINE = 420;
const MAX_INLINE = 900;
const HEX = /^#[0-9a-f]{6}$/i;

type Event = "open" | "close" | "message";
type Handler = (payload?: unknown) => void;

export interface MebotApi {
  open(): void;
  close(): void;
  toggle(): void;
  on(event: Event, fn: Handler): void;
  readonly __mebot: true;
}

interface Launcher {
  title: string;
  primary_color: string;
  position: "right" | "left";
  launcher_label: string | null;
  auto_open_seconds: number | null;
}

interface Options {
  slug: string;
  base: string; // backend origin
  mode: "floating" | "inline";
  target: string | null;
  color: string | null;
  position: "right" | "left" | null;
  open: boolean;
}

export function readOptions(script: HTMLScriptElement): Options | null {
  const d = script.dataset;
  const slug = (d.bot || "").trim();
  if (!slug) {
    warn("data-bot is required on the widget script tag");
    return null;
  }
  let base: string;
  try {
    base = new URL(script.src, location.href).origin;
  } catch {
    return null;
  }
  return {
    slug,
    base,
    mode: d.mode === "inline" ? "inline" : "floating",
    target: d.target || null,
    color: d.color && HEX.test(d.color) ? d.color : null,
    position: d.position === "left" || d.position === "right" ? d.position : null,
    open: d.open === "true",
  };
}

function warn(msg: string) {
  console.warn("[mebot] " + msg);
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {}) {
  const e = document.createElement(tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

const ICON =
  '<svg aria-hidden="true" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>';

function css(side: string) {
  return `:host{all:initial}
.l{position:fixed;bottom:20px;${side}:20px;z-index:${Z};display:flex;align-items:center;gap:8px;height:56px;min-width:56px;padding:0 15px;border:0;border-radius:28px;background:var(--c);color:var(--t);font:600 15px/1 system-ui,-apple-system,"Segoe UI",sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.22);cursor:pointer}
.l:focus-visible{outline:3px solid var(--c);outline-offset:3px}
.b{position:absolute;top:-4px;${side === "right" ? "left" : "right"}:-4px;min-width:20px;height:20px;padding:0 5px;box-sizing:border-box;border-radius:10px;background:#d92d20;color:#fff;font:700 12px/20px system-ui,sans-serif;text-align:center}
.p{position:fixed;bottom:88px;${side}:20px;z-index:${Z};width:380px;height:600px;max-height:calc(100vh - 108px);border-radius:16px;overflow:hidden;box-shadow:0 12px 48px rgba(0,0,0,.28);background:#fff}
.p[hidden],.b[hidden]{display:none}
.p iframe{width:100%;height:100%;border:0;display:block}
@media (max-width:479px){.p{inset:0;width:100%;height:100dvh;max-height:none;border-radius:0}}
@media (prefers-reduced-motion:no-preference){.l{transition:transform .15s}.l:hover{transform:scale(1.04)}}`;
}

function textOn(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  const y = 0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255);
  return y > 160 ? "#111" : "#fff";
}

export function createWidget(opts: Options, win: Window = window): MebotApi {
  const handlers: Record<string, Handler[]> = {};
  let frame: HTMLIFrameElement | null = null;
  let ready = false;
  let isOpen = false;
  let dead = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let host: HTMLElement | null = null;
  let launcher: HTMLButtonElement | null = null;
  let badge: HTMLElement | null = null;
  let panel: HTMLElement | null = null;
  let pendingOpen = false;
  let wantOpen = false; // open() called before the launcher was drawn

  const emit = (e: Event, p?: unknown) => (handlers[e] || []).forEach((fn) => fn(p));

  function post(type: ParentType, payload?: Record<string, unknown>) {
    if (frame && ready) frame.contentWindow?.postMessage(envelope(type, payload), opts.base);
  }

  function destroy(reason: string) {
    dead = true;
    clearTimeout(timer);
    host?.remove();
    frame?.remove();
    win.removeEventListener("message", onMessage);
    warn(reason);
  }

  function makeFrame(mode: "floating" | "inline"): HTMLIFrameElement {
    const f = el("iframe", {
      src: `${opts.base}/embed/${encodeURIComponent(opts.slug)}?mode=${mode}`,
      title: "Chat",
      allow: "clipboard-write",
      referrerpolicy: "origin",
    });
    timer = setTimeout(
      () =>
        destroy(
          `chat did not load in ${READY_TIMEOUT_MS / 1000}s; is ${location.origin} on the allowed sites list (Admin -> Widget)? ` +
            "A strict Content-Security-Policy on this page also needs frame-src " + opts.base,
        ),
      READY_TIMEOUT_MS,
    );
    return f;
  }

  function onMessage(e: MessageEvent) {
    if (!frame || !e.source || e.origin !== opts.base || e.source !== frame.contentWindow) return;
    const m = parseChild(e.data);
    if (!m) return;
    const p = m.payload || {};
    const t: ChildType = m.type;
    if (t === "ready") {
      ready = true;
      clearTimeout(timer);
      post("host-info", { origin: location.origin });
      if (opts.mode === "inline" || isOpen || pendingOpen) post("open");
    } else if (t === "resize" && opts.mode === "inline") {
      const h = Number(p.height);
      if (Number.isFinite(h)) frame.style.height = Math.min(MAX_INLINE, Math.max(MIN_INLINE, h)) + "px";
    } else if (t === "close") {
      close();
    } else if (t === "unread" && badge) {
      const n = Math.max(0, Math.floor(Number(p.count) || 0));
      badge.textContent = n > 9 ? "9+" : String(n);
      badge.hidden = n === 0 || isOpen;
      launcher?.setAttribute("aria-label", label() + (n && !isOpen ? ` (${n} new)` : ""));
    } else if (t === "message") {
      if (p.role === "user" || p.role === "assistant" || p.role === "owner") emit("message", { role: p.role });
    } else if (t === "open-link") {
      const href = safeLink(p.href);
      if (href) win.open(href, "_blank", "noopener,noreferrer");
    }
  }

  let labelText = "Open chat";
  const label = () => labelText;

  function open() {
    if (dead || opts.mode === "inline") return;
    if (!panel || !launcher) {
      wantOpen = true;
      return;
    }
    if (!frame) {
      frame = makeFrame("floating");
      panel.appendChild(frame);
    }
    if (isOpen) return;
    isOpen = true;
    pendingOpen = !ready;
    panel.hidden = false;
    if (badge) badge.hidden = true;
    launcher.setAttribute("aria-expanded", "true");
    post("open");
    frame.focus();
    emit("open");
  }

  function close() {
    if (!isOpen || !panel || !launcher) return;
    isOpen = false;
    pendingOpen = false;
    panel.hidden = true;
    launcher.setAttribute("aria-expanded", "false");
    post("close");
    launcher.focus();
    emit("close");
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape" && isOpen) close();
  }

  function mountFloating(cfg: Launcher) {
    const color = opts.color || (HEX.test(cfg.primary_color) ? cfg.primary_color : "#0f766e");
    const side = opts.position || cfg.position || "right";
    labelText = `Chat with ${cfg.title}`.slice(0, 120);
    host = el("div", { "data-mebot": "" });
    const root = host.attachShadow({ mode: "open" });
    const style = el("style");
    style.textContent = css(side === "left" ? "left" : "right");
    root.appendChild(style);
    launcher = el("button", {
      type: "button",
      class: "l",
      "aria-label": labelText,
      "aria-expanded": "false",
      "aria-haspopup": "dialog",
      style: `--c:${color};--t:${textOn(color)}`,
    });
    launcher.innerHTML = ICON;
    if (cfg.launcher_label) {
      const s = el("span");
      s.textContent = cfg.launcher_label.slice(0, 40);
      launcher.appendChild(s);
    }
    badge = el("span", { class: "b", "aria-hidden": "true" });
    badge.hidden = true;
    launcher.appendChild(badge);
    launcher.addEventListener("click", () => (isOpen ? close() : open()));
    panel = el("div", { class: "p", role: "dialog", "aria-label": cfg.title.slice(0, 120) });
    panel.hidden = true;
    root.append(launcher, panel);
    document.body.appendChild(host);
    win.document.addEventListener("keydown", onKey);
    if (opts.open || wantOpen) open();
    else if (cfg.auto_open_seconds) autoOpen(cfg.auto_open_seconds);
  }

  // Once per browser session on this site, not on every page view.
  function autoOpen(seconds: number) {
    const key = "mebot.autoopen." + opts.slug;
    try {
      if (sessionStorage.getItem(key)) return;
    } catch {
      // storage blocked: still auto-open, just not remembered
    }
    setTimeout(() => {
      try {
        sessionStorage.setItem(key, "1");
      } catch {
        // ignore
      }
      if (!isOpen) open();
    }, seconds * 1000);
  }

  function mountInline() {
    const target = opts.target ? document.querySelector(opts.target) : null;
    if (!target) {
      dead = true;
      warn(`data-target "${opts.target ?? ""}" not found for inline mode`);
      return;
    }
    frame = makeFrame("inline");
    frame.style.cssText = `width:100%;height:${MIN_INLINE}px;border:0;display:block`;
    target.appendChild(frame);
  }

  win.addEventListener("message", onMessage);
  if (opts.mode === "inline") {
    mountInline();
  } else {
    fetch(`${opts.base}/api/public/widget/${encodeURIComponent(opts.slug)}/launcher`, {
      credentials: "omit",
    })
      .then((r) => (r.ok ? (r.json() as Promise<Launcher>) : Promise.reject(r.status)))
      .then((cfg) => !dead && mountFloating(cfg))
      .catch(() =>
        destroy(`this site (${location.origin}) is not on the allowed sites list, or the widget is off`),
      );
  }

  return {
    open,
    close,
    toggle: () => (isOpen ? close() : open()),
    on(event, fn) {
      if (typeof fn === "function") (handlers[event] = handlers[event] || []).push(fn);
    },
    __mebot: true,
  };
}

type Call = [string, ...unknown[]];

// Entry point: one instance per page, however many times the script is included.
export function boot(script: HTMLScriptElement | null, win: Window = window) {
  const w = win as unknown as { Mebot?: MebotApi; MebotQueue?: Call[] | { push(c: Call): void } };
  if (w.Mebot && w.Mebot.__mebot) return w.Mebot;
  if (!script) return undefined;
  const opts = readOptions(script);
  if (!opts) return undefined;
  const api = createWidget(opts, win);
  w.Mebot = api;
  const run = (c: Call) => {
    if (!Array.isArray(c)) return;
    const [method, ...args] = c;
    const fn = (api as unknown as Record<string, unknown>)[method];
    if (method !== "__mebot" && typeof fn === "function") (fn as (...a: unknown[]) => void)(...args);
  };
  const queued = Array.isArray(w.MebotQueue) ? w.MebotQueue : [];
  w.MebotQueue = { push: run };
  queued.forEach(run);
  return api;
}
