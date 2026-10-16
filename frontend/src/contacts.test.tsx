import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const ITEMS = [
  {
    id: "c2",
    session_id: "s9",
    name: "Priya",
    email: "priya@acme.com",
    company: "Acme",
    role: "Recruiter",
    note: "Let's talk",
    created_at: "2026-10-16T09:00:00Z",
  },
  {
    id: "c1",
    session_id: null,
    name: "Bo",
    email: "bo@x.io",
    company: null,
    role: null,
    note: null,
    created_at: "2026-10-15T09:00:00Z",
  },
];

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () =>
      jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/admin/llm": () =>
      jsonResponse({ configured: true, status: "ok", last_test_ok: true, model: "m" }),
    "GET /api/admin/contacts": () => jsonResponse({ items: ITEMS }),
    ...extra,
  });
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("contacts page", () => {
  it("is in the sidebar and lists contacts newest first", async () => {
    routes();
    renderAt("/admin/contacts");
    expect(await screen.findByRole("heading", { name: /^contacts$/i })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: /admin/i });
    expect(within(nav).getByRole("link", { name: /^contacts$/i })).toBeInTheDocument();
    const items = await screen.findAllByRole("article");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText("Priya")).toBeInTheDocument();
    expect(within(items[0]).getByRole("link", { name: "priya@acme.com" })).toHaveAttribute(
      "href",
      "mailto:priya@acme.com",
    );
    expect(within(items[0]).getByText(/Recruiter · Acme/)).toBeInTheDocument();
    expect(within(items[0]).getByText("Let's talk")).toBeInTheDocument();
    expect(within(items[1]).getByText("Bo")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    routes({ "GET /api/admin/contacts": () => jsonResponse({ items: [] }) });
    renderAt("/admin/contacts");
    expect(await screen.findByText(/no one has left their details yet/i)).toBeInTheDocument();
  });

  it("shows the backend error", async () => {
    routes({ "GET /api/admin/contacts": () => errorResponse(500, "X", "Contacts are on fire") });
    renderAt("/admin/contacts");
    expect(await screen.findByRole("alert")).toHaveTextContent(/contacts are on fire/i);
  });

  it("deletes only after confirm", async () => {
    const api = routes({
      "DELETE /api/admin/contacts/c2": () => new Response(null, { status: 204 }),
    });
    renderAt("/admin/contacts");
    await screen.findAllByRole("article");
    vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole("button", { name: /delete priya/i }));
    expect(api.calls.some((c) => c.key.startsWith("DELETE"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /delete priya/i }));
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(1));
    expect(api.calls.some((c) => c.key === "DELETE /api/admin/contacts/c2")).toBe(true);
  });
});
