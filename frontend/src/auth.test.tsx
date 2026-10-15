import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <Where />
    </MemoryRouter>,
  );
}

const where = () => screen.getByTestId("where").textContent;
const health = () => jsonResponse({ ollama: true, model: "me-bot" });
const me = () => jsonResponse({ email: "o@example.com", bot_name: "Bot", bot_slug: "bot" });

describe("first-run setup", () => {
  it.each(["/", "/admin", "/admin/login"])("redirects %s to /setup when setup is required", async (p) => {
    mockApi({ "GET /api/setup/status": () => jsonResponse({ setup_required: true }) });
    renderAt(p);
    await waitFor(() => expect(where()).toBe("/setup"));
    expect(await screen.findByRole("heading", { name: /set up/i })).toBeInTheDocument();
  });

  it("sends /setup to the login page once setup is done", async () => {
    mockApi({ "GET /api/setup/status": () => jsonResponse({ setup_required: false }) });
    renderAt("/setup");
    await waitFor(() => expect(where()).toBe("/admin/login"));
  });

  it("has consent unchecked by default and derives the slug from the name", async () => {
    mockApi({ "GET /api/setup/status": () => jsonResponse({ setup_required: true }) });
    renderAt("/setup");
    const consent = await screen.findByLabelText(/register this install/i);
    expect(consent).not.toBeChecked();
    fireEvent.change(screen.getByLabelText(/bot name/i), { target: { value: "Jane Doe!" } });
    expect(screen.getByLabelText(/^slug/i)).toHaveValue("jane-doe");
  });

  it("validates password confirmation and slug format before submitting", async () => {
    const { calls } = mockApi({
      "GET /api/setup/status": () => jsonResponse({ setup_required: true }),
    });
    renderAt("/setup");
    fireEvent.change(await screen.findByLabelText(/^email/i), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "longenough1" } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: "different11" } });
    fireEvent.change(screen.getByLabelText(/bot name/i), { target: { value: "Bot" } });
    fireEvent.change(screen.getByLabelText(/^slug/i), { target: { value: "Bad Slug" } });
    fireEvent.click(screen.getByRole("button", { name: /finish setup/i }));
    expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
    expect(screen.getByText(/3–40 lowercase/i)).toBeInTheDocument();
    expect(calls.some((c) => c.key === "POST /api/setup")).toBe(false);
  });

  it("submits setup and lands in the admin panel", async () => {
    let done = false;
    const { calls } = mockApi({
      "GET /api/setup/status": () => jsonResponse({ setup_required: !done }),
      "POST /api/setup": () => {
        done = true;
        return jsonResponse({ email: "a@b.com", bot_slug: "bot" }, 201);
      },
      "GET /api/auth/me": me,
      "GET /api/health": health,
      "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    });
    document.cookie = "mebot_csrf=tok123";
    renderAt("/setup");
    fireEvent.change(await screen.findByLabelText(/^email/i), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "longenough1" } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: "longenough1" } });
    fireEvent.change(screen.getByLabelText(/bot name/i), { target: { value: "Bot" } });
    fireEvent.click(screen.getByRole("button", { name: /finish setup/i }));
    await waitFor(() => expect(where()).toBe("/admin"));
    const post = calls.find((c) => c.key === "POST /api/setup")!;
    expect(JSON.parse(post.init!.body as string)).toMatchObject({
      email: "a@b.com",
      bot_slug: "bot",
      registration_consent: false,
    });
    expect((post.init!.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok123");
    expect(post.init!.credentials).toBe("include");
  });

  it("shows the backend error message when setup fails", async () => {
    mockApi({
      "GET /api/setup/status": () => jsonResponse({ setup_required: true }),
      "POST /api/setup": () => errorResponse(403, "SETUP_TOKEN_INVALID", "Invalid setup token"),
    });
    renderAt("/setup");
    fireEvent.change(await screen.findByLabelText(/^email/i), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "longenough1" } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: "longenough1" } });
    fireEvent.change(screen.getByLabelText(/bot name/i), { target: { value: "Bot" } });
    fireEvent.click(screen.getByRole("button", { name: /finish setup/i }));
    expect(await screen.findByText("Invalid setup token")).toBeInTheDocument();
  });
});

describe("admin auth", () => {
  it("redirects /admin to the login page on 401", async () => {
    mockApi({
      "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
      "GET /api/auth/me": () => errorResponse(401, "UNAUTHENTICATED", "Login required"),
    });
    renderAt("/admin");
    await waitFor(() => expect(where()).toBe("/admin/login"));
  });

  it("shows the backend message on failed login", async () => {
    mockApi({
      "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
      "POST /api/auth/login": () =>
        errorResponse(401, "INVALID_CREDENTIALS", "Invalid email or password"),
    });
    renderAt("/admin/login");
    fireEvent.change(await screen.findByLabelText(/^email/i), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: /log in/i }));
    expect(await screen.findByText("Invalid email or password")).toBeInTheDocument();
    expect(where()).toBe("/admin/login");
  });

  it("logs in and opens the admin panel", async () => {
    let authed = false;
    mockApi({
      "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
      "POST /api/auth/login": () => {
        authed = true;
        return new Response(null, { status: 204 });
      },
      "GET /api/auth/me": () =>
        authed ? me() : errorResponse(401, "UNAUTHENTICATED", "Login required"),
      "GET /api/health": health,
      "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    });
    renderAt("/admin/login");
    fireEvent.change(await screen.findByLabelText(/^email/i), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "longenough1" } });
    fireEvent.click(screen.getByRole("button", { name: /log in/i }));
    await waitFor(() => expect(where()).toBe("/admin"));
  });

  it("logs out from the admin panel", async () => {
    const { calls } = mockApi({
      "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
      "GET /api/auth/me": me,
      "GET /api/health": health,
      "POST /api/session": () => jsonResponse({ session_id: "s1" }),
      "POST /api/auth/logout": () => new Response(null, { status: 204 }),
    });
    renderAt("/admin");
    fireEvent.click(await screen.findByRole("button", { name: /log out/i }));
    await waitFor(() => expect(where()).toBe("/admin/login"));
    expect(calls.some((c) => c.key === "POST /api/auth/logout")).toBe(true);
  });
});
