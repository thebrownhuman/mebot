import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { boot, readOptions, READY_TIMEOUT_MS, type MebotApi } from "./widget/loader";

const BASE = "https://bot.example.com";
const LAUNCHER = {
  title: "Ask Shiv",
  primary_color: "#1d4ed8",
  position: "right",
  theme: "auto",
  launcher_label: "Ask about me",
  auto_open_seconds: null as number | null,
};

type W = { Mebot?: MebotApi; MebotQueue?: unknown };

function script(attrs: Record<string, string>) {
  const s = document.createElement("script");
  s.src = `${BASE}/widget/v1.js`;
  for (const [k, v] of Object.entries(attrs)) s.setAttribute(k, v);
  return s;
}

function mockLauncher(body: unknown = LAUNCHER, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
    status === 200
      ? new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
      : new Response("{}", { status }),
  );
}

const shadow = () => document.querySelector("[data-mebot]")?.shadowRoot ?? null;
const launcherBtn = () => shadow()?.querySelector<HTMLButtonElement>("button.l") ?? null;
const iframe = () =>
  (shadow()?.querySelector("iframe") ?? document.querySelector("iframe")) as HTMLIFrameElement | null;

async function mounted() {
  await vi.waitFor(() => expect(launcherBtn()).not.toBeNull());
  return launcherBtn()!;
}

function fromFrame(data: unknown, opts: { origin?: string; source?: unknown } = {}) {
  window.dispatchEvent(
    new MessageEvent("message", {
      data,
      origin: opts.origin ?? BASE,
      source: (opts.source === undefined ? iframe()?.contentWindow : opts.source) as Window,
    }),
  );
}

// jsdom gives iframes inside a shadow root no contentWindow; stand one in.
function fakeChild(frame = iframe()!) {
  const child = { postMessage: vi.fn() };
  Object.defineProperty(frame, "contentWindow", { configurable: true, get: () => child });
  return child;
}

const msg = (type: string, payload?: unknown) => ({ source: "mebot", v: 1, type, ...(payload ? { payload } : {}) });

beforeEach(() => {
  delete (window as W).Mebot;
  delete (window as W).MebotQueue;
  try {
    sessionStorage.clear();
  } catch {
    /* ignore */
  }
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("readOptions", () => {
  it("parses data attributes and rejects bad overrides", () => {
    const o = readOptions(script({ "data-bot": "shiv", "data-color": "#ABCDEF", "data-position": "left", "data-open": "true" }))!;
    expect(o).toMatchObject({ slug: "shiv", base: BASE, mode: "floating", color: "#ABCDEF", position: "left", open: true });
    const bad = readOptions(script({ "data-bot": "shiv", "data-color": "red;x", "data-position": "top", "data-mode": "inline", "data-target": "#c" }))!;
    expect(bad).toMatchObject({ color: null, position: null, mode: "inline", target: "#c", open: false });
  });

  it("requires data-bot", () => {
    const w = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(readOptions(script({}))).toBeNull();
    expect(w).toHaveBeenCalled();
  });
});

describe("floating loader", () => {
  it("draws a shadow-DOM launcher with settings, and no iframe before first open", async () => {
    const f = mockLauncher();
    boot(script({ "data-bot": "shiv" }));
    const btn = await mounted();
    expect(f.mock.calls[0][0]).toBe(`${BASE}/api/public/widget/shiv/launcher`);
    expect((f.mock.calls[0][1] as RequestInit).credentials).toBe("omit");
    expect(btn.getAttribute("aria-label")).toBe("Chat with Ask Shiv");
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(btn.getAttribute("style")).toContain("--c:#1d4ed8");
    expect(btn.textContent).toContain("Ask about me");
    expect(iframe()).toBeNull();
    // host page CSS can't reach the launcher
    expect(document.body.querySelector("button")).toBeNull();
  });

  it("data-color / data-position override the server settings", async () => {
    mockLauncher();
    boot(script({ "data-bot": "shiv", "data-color": "#112233", "data-position": "left" }));
    const btn = await mounted();
    expect(btn.getAttribute("style")).toContain("--c:#112233");
    expect(shadow()!.querySelector("style")!.textContent).toContain("left:20px");
  });

  it("is a single instance however many times it loads", async () => {
    mockLauncher();
    const a = boot(script({ "data-bot": "shiv" }));
    const b = boot(script({ "data-bot": "other" }));
    expect(a).toBe(b);
    await mounted();
    expect(document.querySelectorAll("[data-mebot]")).toHaveLength(1);
  });

  it("open/close/toggle create the iframe lazily, move focus, and emit events", async () => {
    mockLauncher();
    const api = boot(script({ "data-bot": "shiv" }))!;
    const btn = await mounted();
    const events: string[] = [];
    api.on("open", () => events.push("open"));
    api.on("close", () => events.push("close"));
    api.open();
    const f = iframe()!;
    expect(f.src).toBe(`${BASE}/embed/shiv?mode=floating`);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(shadow()!.activeElement).toBe(f);
    api.toggle();
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(shadow()!.activeElement).toBe(btn);
    api.toggle();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(events).toEqual(["open", "close", "open", "close"]);
    expect(document.querySelectorAll("iframe, [data-mebot]")).toHaveLength(1);
    expect(shadow()!.querySelectorAll("iframe")).toHaveLength(1);
  });

  it("runs calls queued in window.MebotQueue before load, and later pushes", async () => {
    mockLauncher();
    const seen: unknown[] = [];
    (window as W).MebotQueue = [["on", "open", () => seen.push("opened")], ["open"]];
    boot(script({ "data-bot": "shiv" }));
    const btn = await mounted();
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(seen).toEqual(["opened"]);
    ((window as W).MebotQueue as { push(c: unknown[]): void }).push(["close"]);
    expect(btn.getAttribute("aria-expanded")).toBe("false");
  });

  it("talks to the iframe only after ready, and ignores spoofed messages", async () => {
    mockLauncher();
    const api = boot(script({ "data-bot": "shiv" }))!;
    await mounted();
    api.open();
    const post = fakeChild().postMessage;
    const onMsg = vi.fn();
    api.on("message", onMsg);
    // wrong origin, wrong source, bad schema: all ignored
    fromFrame(msg("ready"), { origin: "https://evil.dev" });
    fromFrame(msg("ready"), { source: window });
    fromFrame({ source: "mebot", v: 9, type: "ready" });
    expect(post).not.toHaveBeenCalled();
    fromFrame(msg("ready"));
    expect(post).toHaveBeenCalledWith(msg("host-info", { origin: location.origin }), BASE);
    expect(post).toHaveBeenCalledWith(msg("open"), BASE);
    fromFrame(msg("message", { role: "assistant", content: "secret" }));
    expect(onMsg).toHaveBeenCalledWith({ role: "assistant" });
    fromFrame(msg("close"));
    expect(launcherBtn()!.getAttribute("aria-expanded")).toBe("false");
    expect(post).toHaveBeenLastCalledWith(msg("close"), BASE);
  });

  it("opens only safe links in a new tab", async () => {
    mockLauncher();
    const api = boot(script({ "data-bot": "shiv" }))!;
    await mounted();
    api.open();
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    fakeChild();
    fromFrame(msg("ready"));
    fromFrame(msg("open-link", { href: "javascript:alert(1)" }));
    expect(open).not.toHaveBeenCalled();
    fromFrame(msg("open-link", { href: "https://jane.dev" }));
    expect(open).toHaveBeenCalledWith("https://jane.dev/", "_blank", "noopener,noreferrer");
  });

  it("shows an unread badge while closed and clears it on open", async () => {
    mockLauncher();
    const api = boot(script({ "data-bot": "shiv" }))!;
    const btn = await mounted();
    api.open();
    fakeChild();
    fromFrame(msg("ready"));
    api.close();
    fromFrame(msg("unread", { count: 2 }));
    const badge = shadow()!.querySelector<HTMLElement>(".b")!;
    expect(badge.hidden).toBe(false);
    expect(badge.textContent).toBe("2");
    expect(btn.getAttribute("aria-label")).toContain("2 new");
    api.open();
    expect(badge.hidden).toBe(true);
  });

  it("removes the launcher and warns when the iframe never says ready", async () => {
    mockLauncher();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const api = boot(script({ "data-bot": "shiv" }))!;
    await mounted();
    vi.useFakeTimers();
    api.open();
    vi.advanceTimersByTime(READY_TIMEOUT_MS + 10);
    expect(document.querySelector("[data-mebot]")).toBeNull();
    expect(warn.mock.calls[0][0]).toContain(location.origin);
  });

  it("draws nothing when this site is not allowed", async () => {
    mockLauncher({}, 403);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    boot(script({ "data-bot": "shiv" }));
    await vi.waitFor(() => expect(warn).toHaveBeenCalled());
    expect(document.querySelector("[data-mebot]")).toBeNull();
    expect(warn.mock.calls[0][0]).toContain("allowed sites");
  });

  it("data-open opens at once; auto_open_seconds opens once per session", async () => {
    mockLauncher({ ...LAUNCHER, auto_open_seconds: 5 });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    boot(script({ "data-bot": "shiv" }));
    const btn = await mounted();
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    vi.advanceTimersByTime(5000);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(sessionStorage.getItem("mebot.autoopen.shiv")).toBe("1");
  });
});

describe("inline loader", () => {
  it("inserts the iframe into the target and resizes from postMessage within bounds", () => {
    document.body.innerHTML = '<div id="chat"></div>';
    const f = vi.spyOn(globalThis, "fetch");
    boot(script({ "data-bot": "shiv", "data-mode": "inline", "data-target": "#chat" }));
    const frame = document.querySelector<HTMLIFrameElement>("#chat iframe")!;
    expect(frame.src).toBe(`${BASE}/embed/shiv?mode=inline`);
    expect(frame.style.height).toBe("420px");
    expect(f).not.toHaveBeenCalled();
    const post = fakeChild(frame).postMessage;
    fromFrame(msg("ready"));
    expect(post).toHaveBeenCalledWith(msg("open"), BASE);
    fromFrame(msg("resize", { height: 640 }));
    expect(frame.style.height).toBe("640px");
    fromFrame(msg("resize", { height: 100 }));
    expect(frame.style.height).toBe("420px");
    fromFrame(msg("resize", { height: 99999 }));
    expect(frame.style.height).toBe("900px");
    fromFrame(msg("resize", { height: 500 }), { origin: "https://evil.dev" });
    expect(frame.style.height).toBe("900px");
  });

  it("warns when the target is missing", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    boot(script({ "data-bot": "shiv", "data-mode": "inline", "data-target": "#nope" }));
    expect(document.querySelector("iframe")).toBeNull();
    expect(warn.mock.calls[0][0]).toContain("#nope");
  });
});
