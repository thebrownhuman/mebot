import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { conversationExportUrl, conversationQuery } from "./lib/api";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

function Where() {
  const l = useLocation();
  return <div data-testid="where">{l.pathname + l.search}</div>;
}
const where = () => screen.getByTestId("where").textContent ?? "";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <Where />
    </MemoryRouter>,
  );
}

const item = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  recruiter_name: `Rec ${id}`,
  started_at: "2026-10-16T10:00:00Z",
  last_message_at: "2026-10-16T10:05:00Z",
  messages: 4,
  origin: "direct",
  flags: [],
  preview: `Question from ${id}`,
  ...over,
});

const DETAIL = {
  id: "a",
  recruiter_name: "Ann",
  started_at: "2026-10-16T10:00:00Z",
  origin: "https://shivansh.dev",
  messages: [
    { role: "user", content: "What is his stack?", created_at: "2026-10-16T10:00:30Z", unanswered: false, from_owner: false },
    { role: "assistant", content: "I don't know that.", created_at: "2026-10-16T10:00:40Z", unanswered: true, from_owner: false },
    { role: "assistant", content: "It is Python.", created_at: "2026-10-16T10:05:00Z", unanswered: false, from_owner: true },
  ],
  events: [
    { event: "UNANSWERED", created_at: "2026-10-16T10:00:40Z" },
    { event: "LEAK_BLOCKED", created_at: "2026-10-16T10:01:00Z" },
  ],
  contact: { id: "c1", name: "Ann", email: "ann@example.com", company: "Acme", role: "Recruiter", note: null, created_at: "2026-10-16T10:02:00Z" },
};

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () =>
      jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/admin/llm": () => jsonResponse({ configured: true, last_test_ok: true }),
    "GET /api/admin/open-questions": () => jsonResponse({ items: [], open_count: 0 }),
    "GET /api/admin/conversations": () =>
      jsonResponse({
        items: [item("a", { flags: ["unanswered", "contact"], origin: "https://shivansh.dev" }), item("b")],
        next_cursor: null,
      }),
    "GET /api/admin/conversations/a": () => jsonResponse(DETAIL),
    ...extra,
  });
}

const listCalls = (calls: { key: string; init?: RequestInit }[]) =>
  calls.filter((c) => c.key === "GET /api/admin/conversations");

afterEach(() => vi.useRealTimers());

describe("api query builder", () => {
  it("builds filters; custom dates win over a range", () => {
    expect(conversationQuery({})).toBe("");
    expect(conversationQuery({ range: "7d", q: " kube ", has: ["contact", "unanswered"], origin: "direct" })).toBe(
      "range=7d&q=kube&has=contact%2Cunanswered&origin=direct",
    );
    expect(conversationQuery({ range: "7d", from: "2026-10-01", to: "2026-10-05" })).toBe(
      "from=2026-10-01&to=2026-10-05",
    );
    expect(conversationExportUrl({ range: "30d" }, "csv")).toBe(
      "/api/admin/conversations/export?format=csv&range=30d",
    );
  });
});

describe("conversations page", () => {
  it("lists conversations with badges, source and preview", async () => {
    routes();
    renderAt("/admin/conversations");
    const list = await screen.findByRole("list", { name: "Conversations" });
    const first = within(list).getAllByRole("listitem")[0];
    expect(first).toHaveTextContent("Rec a");
    expect(first).toHaveTextContent("shivansh.dev");
    expect(first).toHaveTextContent("Unanswered");
    expect(first).toHaveTextContent("Contact");
    expect(first).toHaveTextContent("Question from a");
    expect(within(list).getAllByRole("listitem")[1]).toHaveTextContent("Direct page");
  });

  it("shows empty states", async () => {
    routes({ "GET /api/admin/conversations": () => jsonResponse({ items: [], next_cursor: null }) });
    renderAt("/admin/conversations");
    expect(await screen.findByText(/no conversations yet/i)).toBeInTheDocument();
    cleanup();
    renderAt("/admin/conversations?has=contact");
    expect(await screen.findByText(/no conversations match/i)).toBeInTheDocument();
  });

  it("shows a load error with retry", async () => {
    let fail = true;
    routes({
      "GET /api/admin/conversations": () =>
        fail ? errorResponse(500, "BOOM", "Database is locked") : jsonResponse({ items: [item("a")], next_cursor: null }),
    });
    renderAt("/admin/conversations");
    expect(await screen.findByRole("alert")).toHaveTextContent("Database is locked");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("Rec a")).toBeInTheDocument();
  });

  it("applies filters from the URL, and changes send them to the API", async () => {
    const { calls } = routes();
    renderAt("/admin/conversations?range=30d&has=contact&q=kube");
    await screen.findByRole("list", { name: "Conversations" });
    const first = listCalls(calls)[0];
    expect(first).toBeDefined();
    expect(screen.getByLabelText(/search messages/i)).toHaveValue("kube");
    expect(screen.getByRole("button", { name: /left contact/i })).toHaveAttribute("aria-pressed", "true");
    const chips = screen.getByRole("group", { name: /only conversations/i });
    fireEvent.click(within(chips).getByRole("button", { name: /^unanswered$/i }));
    await waitFor(() => expect(where()).toContain("has=contact%2Cunanswered"));
    fireEvent.change(screen.getByLabelText(/^period/i), { target: { value: "7d" } });
    await waitFor(() => expect(where()).toContain("range=7d"));
    await waitFor(() => expect(listCalls(calls).length).toBeGreaterThanOrEqual(3));
  });

  it("debounces search and ignores one-character queries", async () => {
    const { calls } = routes();
    renderAt("/admin/conversations");
    await screen.findByRole("list", { name: "Conversations" });
    const before = listCalls(calls).length;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const box = screen.getByLabelText(/search messages/i);
    fireEvent.change(box, { target: { value: "k" } });
    fireEvent.change(box, { target: { value: "ku" } });
    fireEvent.change(box, { target: { value: "kub" } });
    expect(listCalls(calls).length).toBe(before); // nothing yet
    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });
    vi.useRealTimers();
    await waitFor(() => expect(where()).toContain("q=kub"));
    await waitFor(() => expect(listCalls(calls).length).toBe(before + 1));
    fireEvent.change(box, { target: { value: "x" } });
    expect(screen.getByText(/at least 2 characters/i)).toBeInTheDocument();
  });

  it("paginates with Load more", async () => {
    let page = 0;
    const { calls } = routes({
      "GET /api/admin/conversations": () => {
        page += 1;
        return jsonResponse(
          page === 1
            ? { items: [item("a"), item("b")], next_cursor: "CUR1" }
            : { items: [item("c")], next_cursor: null },
        );
      },
    });
    renderAt("/admin/conversations");
    await screen.findByText("Rec b");
    fireEvent.click(screen.getByRole("button", { name: /load more/i }));
    expect(await screen.findByText("Rec c")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Conversations" })).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
    expect(listCalls(calls)).toHaveLength(2);
  });

  it("opens a transcript with inline badges, events and the contact card", async () => {
    routes();
    renderAt("/admin/conversations");
    fireEvent.click(await screen.findByRole("button", { name: /rec a/i }));
    const panel = await screen.findByRole("region", { name: "Conversation" });
    expect(await within(panel).findByText("What is his stack?")).toBeInTheDocument();
    expect(where()).toContain("c=a");
    const transcript = within(panel).getByRole("list", { name: "Transcript" });
    const items = within(transcript).getAllByRole("listitem");
    expect(items[1]).toHaveTextContent("Unanswered");
    expect(items[2]).toHaveTextContent("Owner reply");
    expect(items[2]).toHaveTextContent("You");
    expect(within(panel).getByText(/looked like a prompt leak/i)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "ann@example.com" })).toHaveAttribute("href", "mailto:ann@example.com");
    fireEvent.click(within(panel).getByRole("button", { name: /back to list/i }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Conversation" })).not.toBeInTheDocument());
  });

  it("deletes after confirmation and removes it from the list", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { calls } = routes({ "DELETE /api/admin/conversations/a": () => new Response(null, { status: 204 }) });
    renderAt("/admin/conversations?c=a");
    fireEvent.click(await screen.findByRole("button", { name: /delete conversation/i }));
    await waitFor(() => expect(calls.some((c) => c.key === "DELETE /api/admin/conversations/a")).toBe(true));
    expect(await screen.findByText(/conversation deleted/i)).toBeInTheDocument();
    expect(screen.queryByText("Rec a")).not.toBeInTheDocument();
    expect(screen.getByText("Rec b")).toBeInTheDocument();
  });

  it("does not delete when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const { calls } = routes();
    renderAt("/admin/conversations?c=a");
    fireEvent.click(await screen.findByRole("button", { name: /delete conversation/i }));
    expect(calls.some((c) => c.key.startsWith("DELETE"))).toBe(false);
  });

  it("explains a conversation that was deleted elsewhere (404)", async () => {
    routes({ "GET /api/admin/conversations/a": () => errorResponse(404, "NOT_FOUND", "This conversation no longer exists.") });
    renderAt("/admin/conversations?c=a");
    expect(await screen.findByText(/no longer exists/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete conversation/i })).not.toBeInTheDocument();
  });

  it("export links carry the current filters", async () => {
    routes();
    renderAt("/admin/conversations?range=30d&has=contact");
    await screen.findByRole("list", { name: "Conversations" });
    expect(screen.getByRole("link", { name: /export csv/i })).toHaveAttribute(
      "href",
      "/api/admin/conversations/export?format=csv&range=30d&has=contact",
    );
    expect(screen.getByRole("link", { name: /export json/i })).toHaveAttribute(
      "href",
      "/api/admin/conversations/export?format=json&range=30d&has=contact",
    );
  });

  it("has a sidebar entry", async () => {
    routes();
    renderAt("/admin/conversations");
    const nav = await screen.findByRole("navigation", { name: /admin/i });
    expect(within(nav).getByRole("link", { name: /^conversations$/i })).toBeInTheDocument();
  });
});
