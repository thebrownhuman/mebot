import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EmbedApp, { onColor, parseLocation } from "./embed/EmbedApp";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

const orbFactory = vi.hoisted(() => vi.fn());
vi.mock("./components/Orb", () => {
  orbFactory();
  return { default: () => <div data-testid="orb" /> };
});

const WIDGET = {
  title: "Ask Shiv",
  primary_color: "#1d4ed8",
  theme: "dark",
  position: "right",
  avatar_url: null,
  launcher_label: null,
  greeting: "Hi! I am the assistant.",
  suggested_questions: ["What does he work on?", "Tech stack?"],
  show_orb: false,
  auto_open_seconds: null,
  max_message_chars: 1000,
  turnstile_site_key: null,
  owner_first_name: "Shivansh",
  paused: false,
};

function routes(extra: Record<string, Handler> = {}, widget: Partial<typeof WIDGET> = {}) {
  return mockApi({
    "GET /api/public/widget/shivansh": () => jsonResponse({ ...WIDGET, ...widget }),
    "GET /api/health": () => jsonResponse({ ready: true, model: "m" }),
    "GET /api/public/config": () =>
      jsonResponse({
        turnstile_site_key: null,
        max_message_chars: 1000,
        paused: false,
        owner_name: "Shivansh Mishra",
        assistant_greeting: WIDGET.greeting,
      }),
    "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    "GET /api/session/s1/updates": () => jsonResponse({ messages: [], unanswered: false }),
    "POST /api/chat": () => new Response("He builds bots."),
    "POST /api/public/widget/shivansh/opened": () => new Response(null, { status: 204 }),
    ...extra,
  });
}

async function readyInput() {
  const input = await screen.findByLabelText(/your question/i);
  await waitFor(() => expect(input).not.toBeDisabled());
  return input;
}

function ask(input: HTMLElement, text: string) {
  fireEvent.change(input, { target: { value: text } });
  fireEvent.submit(input.closest("form")!);
}

describe("parseLocation", () => {
  it("reads slug and mode", () => {
    expect(parseLocation({ pathname: "/embed/shivansh", search: "?mode=floating" })).toEqual({
      slug: "shivansh",
      mode: "floating",
    });
    expect(parseLocation({ pathname: "/embed/a", search: "?mode=evil" }).mode).toBe("page");
  });
  it("picks readable text on the brand colour", () => {
    expect(onColor("#0f766e")).toBe("#ffffff");
    expect(onColor("#fde68a")).toBe("#111111");
  });
});

describe("embed app", () => {
  it("applies settings: colour var, dark theme, title, greeting; no orb", async () => {
    routes();
    render(<EmbedApp slug="shivansh" mode="inline" />);
    expect(await screen.findByRole("heading", { name: "Ask Shiv" })).toBeInTheDocument();
    expect(document.documentElement.style.getPropertyValue("--mb-primary")).toBe("#1d4ed8");
    expect(document.documentElement.classList.contains("mb-dark")).toBe(true);
    expect(await screen.findByText("Hi! I am the assistant.")).toBeInTheDocument();
    expect(orbFactory).not.toHaveBeenCalled();
  });

  it("light theme: contact panel tokens follow the widget, brand colour as accent", async () => {
    routes({}, { theme: "light" });
    render(<EmbedApp slug="shivansh" mode="inline" />);
    await screen.findByRole("heading", { name: "Ask Shiv" });
    const root = document.documentElement;
    expect(root.classList.contains("mb-dark")).toBe(false);
    expect(root.style.getPropertyValue("--term-bright")).toBe("29 78 216");
  });

  it("light theme with a pale brand colour keeps accents readable", async () => {
    routes({}, { theme: "light", primary_color: "#fde047" });
    render(<EmbedApp slug="shivansh" mode="inline" />);
    await screen.findByRole("heading", { name: "Ask Shiv" });
    expect(document.documentElement.style.getPropertyValue("--term-bright")).toBe("31 41 51");
  });

  it("dark theme leaves the terminal accent to the stylesheet", async () => {
    routes();
    render(<EmbedApp slug="shivansh" mode="inline" />);
    await screen.findByRole("heading", { name: "Ask Shiv" });
    expect(document.documentElement.style.getPropertyValue("--term-bright")).toBe("");
  });

  it("shows a loading state, then unavailable for a disabled widget", async () => {
    routes({ "GET /api/public/widget/shivansh": () => errorResponse(404, "WIDGET_UNAVAILABLE", "x") });
    render(<EmbedApp slug="shivansh" mode="inline" />);
    expect(screen.getByLabelText(/loading chat/i)).toBeInTheDocument();
    expect(await screen.findByText(/this chat is unavailable/i)).toBeInTheDocument();
  });

  it("offers retry on a network error", async () => {
    let fail = true;
    routes({
      "GET /api/public/widget/shivansh": () => (fail ? errorResponse(500, "X", "boom") : jsonResponse(WIDGET)),
    });
    render(<EmbedApp slug="shivansh" mode="inline" />);
    const retry = await screen.findByRole("button", { name: /try again/i });
    fail = false;
    fireEvent.click(retry);
    expect(await screen.findByRole("heading", { name: "Ask Shiv" })).toBeInTheDocument();
  });

  it("suggested chips send the question and disappear", async () => {
    const api = routes();
    render(<EmbedApp slug="shivansh" mode="inline" />);
    await readyInput();
    fireEvent.click(await screen.findByRole("button", { name: "Tech stack?" }));
    expect(await screen.findByText("He builds bots.")).toBeInTheDocument();
    const call = api.calls.find((c) => c.key === "POST /api/chat")!;
    expect(JSON.parse(String(call.init!.body)).message).toBe("Tech stack?");
    expect(screen.queryByRole("button", { name: "Tech stack?" })).toBeNull();
  });

  it("replaces the bubble on a replace frame", async () => {
    routes({
      "POST /api/chat": () => new Response('leaky\x1e{"type":"replace","content":"Safe answer."}'),
    });
    render(<EmbedApp slug="shivansh" mode="inline" />);
    ask(await readyInput(), "hi");
    expect(await screen.findByText("Safe answer.")).toBeInTheDocument();
    expect(screen.queryByText(/leaky/)).toBeNull();
  });

  it("lazy-loads the orb only when enabled", async () => {
    routes({}, { show_orb: true });
    render(<EmbedApp slug="shivansh" mode="inline" />);
    expect(await screen.findByTestId("orb")).toBeInTheDocument();
    expect(orbFactory).toHaveBeenCalled();
  });
});

describe("embed postMessage", () => {
  function fromParent(data: unknown, source: unknown) {
    act(() => {
      window.dispatchEvent(new MessageEvent("message", { data, source: source as Window }));
    });
  }

  function fakeParent() {
    const parent = { postMessage: vi.fn() };
    // jsdom: window.parent === window, so pretend we are framed.
    vi.spyOn(window, "parent", "get").mockReturnValue(parent as unknown as Window);
    return parent;
  }

  it("posts ready, reports WIDGET_OPENED on open with host origin, ignores spoofs", async () => {
    const parent = fakeParent();
    const api = routes();
    render(<EmbedApp slug="shivansh" mode="floating" />);
    await readyInput();
    expect(parent.postMessage).toHaveBeenCalledWith({ source: "mebot", v: 1, type: "ready" }, "*");
    const opened = () => api.calls.filter((c) => c.key === "POST /api/public/widget/shivansh/opened");
    // spoofed: wrong source window, wrong schema
    fromParent({ source: "mebot", v: 1, type: "host-info", payload: { origin: "https://evil.dev" } }, window);
    fromParent({ source: "other", v: 1, type: "open" }, parent);
    fromParent({ source: "mebot", v: 2, type: "open" }, parent);
    expect(opened()).toHaveLength(0);
    fromParent({ source: "mebot", v: 1, type: "host-info", payload: { origin: "https://shivansh.dev" } }, parent);
    fromParent({ source: "mebot", v: 1, type: "open" }, parent);
    await waitFor(() => expect(opened()).toHaveLength(1));
    expect(JSON.parse(String(opened()[0].init!.body))).toEqual({
      session_id: "s1",
      origin: "https://shivansh.dev",
    });
    fireEvent.click(screen.getByRole("button", { name: /close chat/i }));
    expect(parent.postMessage).toHaveBeenCalledWith({ source: "mebot", v: 1, type: "close" }, "*");
    for (const [msg] of parent.postMessage.mock.calls) {
      expect(JSON.stringify(msg)).not.toMatch(/assistant\.|builds|Shivansh/);
    }
  });

  it("posts message roles without content, and counts unread owner replies while closed", async () => {
    const parent = fakeParent();
    const updates = {
      messages: [{ content: "Hi, Shivansh here", created_at: "2026-10-17T10:00:00Z" }],
      unanswered: false,
    };
    routes({ "GET /api/session/s1/updates": () => jsonResponse(updates) });
    render(<EmbedApp slug="shivansh" mode="floating" />);
    ask(await readyInput(), "hi");
    await screen.findByText("He builds bots.");
    await waitFor(() =>
      expect(parent.postMessage).toHaveBeenCalledWith(
        { source: "mebot", v: 1, type: "message", payload: { role: "assistant" } },
        "*",
      ),
    );
    await waitFor(() =>
      expect(parent.postMessage).toHaveBeenCalledWith(
        { source: "mebot", v: 1, type: "unread", payload: { count: 1 } },
        "*",
      ),
    );
  });

  it("links open via the parent", async () => {
    const parent = fakeParent();
    routes({ "POST /api/chat": () => new Response("See https://jane.dev") });
    render(<EmbedApp slug="shivansh" mode="inline" />);
    ask(await readyInput(), "site?");
    fireEvent.click(await screen.findByRole("link", { name: "https://jane.dev" }));
    expect(parent.postMessage).toHaveBeenCalledWith(
      { source: "mebot", v: 1, type: "open-link", payload: { href: "https://jane.dev/" } },
      "*",
    );
  });
});
