import { act, render } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMebot, validate } from "../src/core";
import { defineElement } from "../src/element";
import { Mebot } from "../src/index";
import { MebotChat, type MebotChatHandle } from "../src/react";
import { cleanTheme, iframeParams, themeFromCss } from "../src/theme";

const HOST = "https://mebot.example";
const KEY = "pk_0123456789abcdef01234567";

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
    new Response(JSON.stringify({ title: "Alice's assistant", primary_color: "#112233", position: "right" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

const flush = () => new Promise((r) => setTimeout(r, 0));
const shadow = () => document.querySelector("[data-mebot-sdk]")!.shadowRoot!;
const frame = () => shadow().querySelector("iframe")!;

function fromFrame(type: string, payload?: object, origin = HOST, source: unknown = frame().contentWindow) {
  window.dispatchEvent(
    new MessageEvent("message", { data: { source: "mebot", v: 1, type, payload }, origin, source: source as Window }),
  );
}

describe("options", () => {
  it("accepts only a public key and known options; never an LLM key", () => {
    expect(validate({ botKey: KEY, host: HOST }).host).toBe(HOST);
    expect(() => validate({ botKey: "sk-live-abc123", host: HOST })).toThrow(/public bot key/);
    expect(() => validate({ botKey: KEY, host: HOST, apiKey: "sk-123" } as never)).toThrow(/unknown option "apiKey"/);
    expect(() => validate({ botKey: KEY, host: HOST, llmKey: "x" } as never)).toThrow(/unknown option/);
    expect(() => validate({ botKey: KEY })).toThrow(/host/);
    expect(() => validate({ botKey: KEY, host: "javascript:alert(1)" })).toThrow();
  });

  it("never puts anything but the public key and theme params in the iframe URL", async () => {
    createMebot({ botKey: KEY, host: HOST, accent: "#AA0000", theme: "dark", font: "serif" });
    await flush();
    const src = new URL(frame().src);
    expect(src.origin).toBe(HOST);
    expect(src.pathname).toBe(`/embed/${KEY}`);
    expect(Object.fromEntries(src.searchParams)).toEqual({ mode: "floating", theme: "dark", accent: "aa0000", font: "serif" });
  });
});

describe("theme allow-list", () => {
  it("drops anything that isn't a plain, bounded value", () => {
    expect(
      cleanTheme({
        theme: "neon", accent: "red;background:url(x)", radius: "12px", font: "Comic Sans",
        launcherSize: 999, offsetX: "8", offsetY: "-3",
      }),
    ).toEqual({ radius: 12, offsetX: 8 });
    expect(iframeParams(cleanTheme({ accent: "#00ff00", font: "mono" }))).toBe("&accent=00ff00&font=mono");
  });

  it("reads CSS variables", () => {
    const el = document.createElement("div");
    el.style.setProperty("--mebot-accent", "#123456");
    el.style.setProperty("--mebot-radius", "8px");
    el.style.setProperty("--mebot-font", "expression(alert(1))");
    expect(themeFromCss(el.style)).toEqual({ accent: "#123456", radius: 8 });
  });
});

describe("postMessage", () => {
  it("only trusts its own iframe from the mebot origin", async () => {
    const m = createMebot({ botKey: KEY, host: HOST });
    const ready = vi.fn();
    const msg = vi.fn();
    m.on("ready", ready);
    m.on("message", msg);
    await flush();
    fromFrame("ready", undefined, "https://evil.example");
    fromFrame("ready", undefined, HOST, window);
    expect(ready).not.toHaveBeenCalled();
    fromFrame("ready");
    expect(ready).toHaveBeenCalledTimes(1);
    fromFrame("message", { role: "assistant", content: "secret" });
    expect(msg).toHaveBeenCalledWith({ role: "assistant" });
    fromFrame("bogus");
  });

  it("open/close/toggle and Escape; events fire", async () => {
    const m = createMebot({ botKey: KEY, host: HOST });
    const seen: string[] = [];
    for (const e of ["open", "close"] as const) m.on(e, () => seen.push(e));
    m.open(); // before mount: queued
    await flush();
    const panel = shadow().querySelector(".p") as HTMLElement;
    expect(panel.hidden).toBe(false);
    m.toggle();
    expect(panel.hidden).toBe(true);
    m.open();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(seen).toEqual(["open", "close", "open", "close"]);
    m.destroy();
    expect(document.querySelector("[data-mebot-sdk]")).toBeNull();
  });

  it("removes itself when the site isn't allowed", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 403 }));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    createMebot({ botKey: KEY, host: HOST });
    await flush();
    await flush();
    expect(document.querySelector("[data-mebot-sdk]")).toBeNull();
    expect(warn).toHaveBeenCalled();
  });
});

describe("<mebot-chat>", () => {
  it("mounts from attributes and CSS variables and re-dispatches events", async () => {
    defineElement(window);
    const el = document.createElement("mebot-chat") as HTMLElement & { open(): void };
    el.setAttribute("bot-key", KEY);
    el.setAttribute("host", HOST);
    el.setAttribute("theme", "auto");
    el.style.setProperty("--mebot-accent", "#00aa55");
    const opened = vi.fn();
    el.addEventListener("open", opened);
    document.body.appendChild(el);
    await flush();
    expect(new URL(frame().src).searchParams.get("accent")).toBe("00aa55");
    expect(new URL(frame().src).searchParams.get("theme")).toBe("auto");
    el.open();
    expect(opened).toHaveBeenCalled();
    el.remove();
    expect(document.querySelector("[data-mebot-sdk]")).toBeNull();
  });

  it("ignores an element with an API key instead of a bot key", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const el = document.createElement("mebot-chat");
    el.setAttribute("bot-key", "sk-proj-123");
    el.setAttribute("host", HOST);
    document.body.appendChild(el);
    await flush();
    expect(document.querySelector("[data-mebot-sdk]")).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
  });
});

describe("Mebot.init and React", () => {
  it("Mebot.init returns a controllable instance", async () => {
    const m = Mebot.init({ botKey: KEY, host: HOST });
    await flush();
    m.open();
    expect((shadow().querySelector(".p") as HTMLElement).hidden).toBe(false);
  });

  it("MebotChat mounts, exposes a ref and cleans up", async () => {
    const ref = createRef<MebotChatHandle>();
    const onOpen = vi.fn();
    const { unmount } = render(<MebotChat ref={ref} botKey={KEY} host={HOST} onOpen={onOpen} />);
    await act(flush);
    act(() => ref.current!.open());
    expect(onOpen).toHaveBeenCalled();
    unmount();
    expect(document.querySelector("[data-mebot-sdk]")).toBeNull();
  });
});
