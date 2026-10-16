import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const CONFIG = {
  turnstile_site_key: null,
  max_message_chars: 1000,
  paused: false,
  owner_name: "Jane Doe",
};
const STORE_KEY = "mebot.session";

type Upd = { messages: { role: string; from_owner: boolean; content: string; created_at: string }[]; unanswered: boolean };
const owner = (content: string, created_at: string) => ({
  role: "assistant",
  from_owner: true,
  content,
  created_at,
});

let updates: Upd = { messages: [], unanswered: false };
let visibility: DocumentVisibilityState = "visible";

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/health": () => jsonResponse({ ready: true, model: "m" }),
    "GET /api/public/config": () => jsonResponse(CONFIG),
    "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    "GET /api/session/s1/updates": () => jsonResponse(updates),
    ...extra,
  });
}

const pollCount = (calls: { key: string }[], sid = "s1") =>
  calls.filter((c) => c.key === `GET /api/session/${sid}/updates`).length;

async function enter() {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
  fireEvent.change(await screen.findByLabelText(/your name/i), { target: { value: "Jo" } });
  fireEvent.keyDown(screen.getByLabelText(/your name/i), { key: "Enter" });
  const input = await screen.findByLabelText(/your question/i);
  await waitFor(() => expect(input).not.toBeDisabled());
  return input;
}

async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function setVisibility(v: DocumentVisibilityState) {
  visibility = v;
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  updates = { messages: [], unanswered: false };
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibility,
  });
  localStorage.clear();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("owner replies", () => {
  it("polls every 5s and shows owner replies as distinct bubbles, using after=", async () => {
    const api = routes();
    await enter();
    await waitFor(() => expect(pollCount(api.calls)).toBe(1));
    updates = { messages: [owner("Around 30 LPA.", "2026-10-16T10:00:00.000000Z")], unanswered: false };
    await tick(5000);
    expect(await screen.findByText("Jane replied:")).toBeInTheDocument();
    expect(screen.getByText("Around 30 LPA.")).toBeInTheDocument();
    updates = { messages: [], unanswered: false };
    await tick(5000);
    const urls = (api.spy.mock.calls as [RequestInfo][]).map((c) => String(c[0]));
    expect(urls.filter((u) => u.includes("/updates")).slice(-1)[0]).toContain(
      "after=2026-10-16T10%3A00%3A00.000000Z",
    );
    expect(screen.getAllByText("Jane replied:")).toHaveLength(1);
  });

  it("stops while the tab is hidden and resumes when visible", async () => {
    const api = routes();
    await enter();
    await tick(5000);
    const before = pollCount(api.calls);
    setVisibility("hidden");
    await tick(20000);
    expect(pollCount(api.calls)).toBe(before);
    setVisibility("visible");
    await waitFor(() => expect(pollCount(api.calls)).toBe(before + 1));
    await tick(5000);
    expect(pollCount(api.calls)).toBe(before + 2);
  });

  it("stops after 30 minutes idle and resumes on activity", async () => {
    const api = routes();
    await enter();
    await tick(31 * 60 * 1000);
    const idle = pollCount(api.calls);
    await tick(60_000);
    expect(pollCount(api.calls)).toBe(idle);
    fireEvent.keyDown(window, { key: "a" });
    await waitFor(() => expect(pollCount(api.calls)).toBe(idle + 1));
  });

  it("remembers the session and shows earlier replies when the recruiter returns", async () => {
    localStorage.setItem(STORE_KEY, "old1");
    const api = routes({
      "GET /api/session/old1/updates": () =>
        jsonResponse({ messages: [owner("Yes, open to relocation.", "2026-10-15T08:00:00Z")], unanswered: false }),
    });
    await enter();
    expect(await screen.findByText("Yes, open to relocation.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.key === "POST /api/session")).toBe(false);
    expect(localStorage.getItem(STORE_KEY)).toBe("old1");
  });

  it("starts a new session when the remembered one is gone", async () => {
    localStorage.setItem(STORE_KEY, "gone");
    const api = routes({
      "GET /api/session/gone/updates": () => errorResponse(404, "NOT_FOUND", "Unknown session"),
    });
    await enter();
    await waitFor(() => expect(api.calls.some((c) => c.key === "POST /api/session")).toBe(true));
    expect(localStorage.getItem(STORE_KEY)).toBe("s1");
  });

  it("suggests leaving contact details after an unanswered reply", async () => {
    routes({ "POST /api/chat": () => new Response("I don't know that one.") });
    const input = await enter();
    updates = { messages: [], unanswered: true };
    fireEvent.change(input, { target: { value: "Expected CTC?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    const btn = await screen.findByRole("button", { name: /leave your contact/i });
    fireEvent.click(btn);
    expect(screen.getByRole("dialog", { name: /leave your contact/i })).toBeInTheDocument();
  });

  it("works when localStorage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const api = routes();
    await enter();
    await waitFor(() => expect(api.calls.some((c) => c.key === "POST /api/session")).toBe(true));
  });
});
