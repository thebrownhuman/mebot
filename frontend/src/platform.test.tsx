import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const TENANT = {
  id: "b1",
  slug: "alice",
  owner_email: "alice@example.com",
  email_verified: true,
  created_at: "2026-10-01T10:00:00Z",
  status: "active",
  status_reason: null,
  plan: "free",
  setup_done: true,
  messages_7d: 7,
  messages_30d: 30,
  tokens_30d: 1200,
  last_active_at: "2026-10-16T10:00:00Z",
  deletion_requested_at: null,
};

function api(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false, mode: "hosted" }),
    "GET /api/platform/auth/me": () => jsonResponse({ email: "ops@example.com" }),
    "GET /api/platform/tenants": () => jsonResponse({ items: [TENANT] }),
    "GET /api/platform/signups": () => jsonResponse({ items: [] }),
    "GET /api/platform/invites": () => jsonResponse({ items: [] }),
    "GET /api/platform/audit": () => jsonResponse({ items: [] }),
    ...extra,
  });
}

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );

describe("platform console", () => {
  it("redirects to login without an operator session", async () => {
    api({ "GET /api/platform/auth/me": () => errorResponse(401, "UNAUTHENTICATED", "Login") });
    renderAt("/platform");
    expect(await screen.findByRole("heading", { name: /log in/i })).toBeTruthy();
  });

  it("lists tenants with usage and suspends with a reason", async () => {
    const { calls } = api({
      "POST /api/platform/tenants/b1/suspend": () => jsonResponse({ status: "suspended" }),
    });
    vi.spyOn(window, "prompt").mockReturnValue("spam");
    renderAt("/platform");
    expect(await screen.findByText("/b/alice")).toBeTruthy();
    expect(screen.getByText("7 / 30")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /suspend/i }));
    await waitFor(() =>
      expect(calls.some((c) => c.key === "POST /api/platform/tenants/b1/suspend")).toBe(true),
    );
    const call = calls.find((c) => c.key === "POST /api/platform/tenants/b1/suspend");
    expect(JSON.parse(String(call?.init?.body))).toEqual({ reason: "spam" });
  });

  it("cancelling the reason prompt does nothing", async () => {
    const { calls } = api();
    vi.spyOn(window, "prompt").mockReturnValue(null);
    renderAt("/platform");
    fireEvent.click(await screen.findByRole("button", { name: /delete/i }));
    expect(calls.some((c) => c.key.includes("/delete"))).toBe(false);
  });

  it("empty sign-up queue and invite creation", async () => {
    api({ "POST /api/platform/invites": () => jsonResponse({ code: "CODE123" }, 201) });
    renderAt("/platform");
    fireEvent.click(await screen.findByRole("tab", { name: /sign-ups/i }));
    expect(await screen.findByText(/nobody is waiting/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /invites/i }));
    expect(await screen.findByText(/no invites yet/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /create invite/i }));
    expect(await screen.findByText("CODE123")).toBeTruthy();
  });

  it("shows a load error", async () => {
    api({ "GET /api/platform/tenants": () => errorResponse(500, "X", "Database down") });
    renderAt("/platform");
    expect((await screen.findByRole("alert")).textContent).toMatch(/database down/i);
  });
});
