import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { tenantPrefix, withTenant } from "./lib/api";
import { slugProblem } from "./pages/hosted/SignupPage";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));
vi.mock("./components/Turnstile", () => ({
  default: ({ onToken }: { onToken: (t: string) => void }) => (
    <button type="button" onClick={() => onToken("tok")}>
      bot check
    </button>
  ),
}));

const CFG = { signup_mode: "open", turnstile_site_key: "site", hosted_domain: null };

function hosted(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false, mode: "hosted" }),
    "GET /api/hosted/config": () => jsonResponse(CFG),
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

const type = (label: RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("tenant prefix", () => {
  it("prefixes public calls under /b/{ref} and embeds by public key", () => {
    expect(tenantPrefix("/b/alice")).toBe("/b/alice");
    expect(tenantPrefix("/b/alice/anything")).toBe("/b/alice");
    expect(tenantPrefix("/embed/pk_abc123")).toBe("/b/pk_abc123");
    expect(tenantPrefix("/embed/shivansh")).toBe(""); // single mode slug
    expect(tenantPrefix("/admin")).toBe("");
    expect(withTenant("/api/chat", "/b/alice")).toBe("/b/alice/api/chat");
    expect(withTenant("/api/public/config", "/b/alice")).toBe("/b/alice/api/public/config");
    expect(withTenant("/api/session/x/updates", "/b/alice")).toBe("/b/alice/api/session/x/updates");
  });

  it("never prefixes owner APIs", () => {
    expect(withTenant("/api/admin/profile/identity", "/b/alice")).toBe("/api/admin/profile/identity");
    expect(withTenant("/api/auth/me", "/b/alice")).toBe("/api/auth/me");
    expect(withTenant("/api/hosted/account", "/b/alice")).toBe("/api/hosted/account");
  });
});

describe("slug rules (mirror the server)", () => {
  it("accepts and rejects like the backend", () => {
    expect(slugProblem("alice-dev")).toBeNull();
    for (const bad of ["ab", "-x-y", "a--b", "Has_Upper", "x".repeat(33)]) {
      expect(slugProblem(bad)).not.toBeNull();
    }
  });
});

describe("signup", () => {
  it("signs up and shows check-your-email", async () => {
    const { calls } = hosted({ "POST /api/hosted/signup": () => jsonResponse({ status: "ok" }, 202) });
    renderAt("/signup");
    await screen.findByRole("heading", { name: /create your assistant/i });
    type(/your name/i, "Alice Dev");
    expect((screen.getByLabelText(/address/i) as HTMLInputElement).value).toBe("alice-dev");
    type(/e-mail/i, "alice@example.com");
    type(/^password/i, "longenough1");
    fireEvent.click(screen.getByRole("button", { name: /bot check/i }));
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    await screen.findByRole("heading", { name: /check your e-mail/i });
    const body = JSON.parse(String(calls.find((c) => c.key === "POST /api/hosted/signup")?.init?.body));
    expect(body).toMatchObject({ slug: "alice-dev", turnstile_token: "tok", bot_name: "Alice Dev" });
  });

  it("shows a taken slug next to the field", async () => {
    hosted({ "POST /api/hosted/signup": () => errorResponse(409, "SLUG_TAKEN", "That address is taken.") });
    renderAt("/signup");
    await screen.findByRole("heading", { name: /create your assistant/i });
    type(/your name/i, "Alice");
    type(/e-mail/i, "a@example.com");
    type(/^password/i, "longenough1");
    fireEvent.click(screen.getByRole("button", { name: /bot check/i }));
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByText(/that address is taken/i)).toBeTruthy();
  });

  it("asks for an invite code in invite mode and is closed in closed mode", async () => {
    hosted({ "GET /api/hosted/config": () => jsonResponse({ ...CFG, signup_mode: "invite" }) });
    renderAt("/signup");
    expect(await screen.findByLabelText(/invite code/i)).toBeTruthy();
  });

  it("closed mode", async () => {
    hosted({ "GET /api/hosted/config": () => jsonResponse({ ...CFG, signup_mode: "closed" }) });
    renderAt("/signup");
    expect(await screen.findByRole("heading", { name: /sign-up is closed/i })).toBeTruthy();
  });

  it("load error", async () => {
    hosted({ "GET /api/hosted/config": () => errorResponse(500, "X", "Server trouble") });
    renderAt("/signup");
    expect((await screen.findByRole("alert")).textContent).toMatch(/server trouble/i);
  });
});

describe("verify and reset", () => {
  it("verifies once", async () => {
    const { calls } = hosted({ "POST /api/hosted/verify": () => new Response(null, { status: 204 }) });
    renderAt("/verify?token=abc");
    expect(await screen.findByText(/your e-mail is confirmed/i)).toBeTruthy();
    expect(calls.filter((c) => c.key === "POST /api/hosted/verify")).toHaveLength(1);
  });

  it("bad verify link", async () => {
    hosted({ "POST /api/hosted/verify": () => errorResponse(400, "TOKEN_INVALID", "This link is invalid or has expired.") });
    renderAt("/verify?token=abc");
    expect((await screen.findByRole("alert")).textContent).toMatch(/expired/i);
  });

  it("requests a reset link", async () => {
    hosted({ "POST /api/hosted/password-reset": () => jsonResponse({}, 202) });
    renderAt("/reset-password");
    await screen.findByLabelText(/e-mail/i);
    type(/e-mail/i, "a@example.com");
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));
    expect(await screen.findByText(/reset link is on its way/i)).toBeTruthy();
  });

  it("sets a new password with a token, checking match first", async () => {
    const { calls } = hosted({
      "POST /api/hosted/password-reset/confirm": () => new Response(null, { status: 204 }),
    });
    renderAt("/reset-password?token=t1");
    await screen.findByLabelText(/^new password/i);
    type(/^new password/i, "longenough1");
    type(/confirm new password/i, "different11");
    fireEvent.click(screen.getByRole("button", { name: /set password/i }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/don't match/i);
    type(/confirm new password/i, "longenough1");
    fireEvent.click(screen.getByRole("button", { name: /set password/i }));
    expect(await screen.findByText(/password changed/i)).toBeTruthy();
    const body = JSON.parse(String(calls[calls.length - 1]?.init?.body));
    expect(body).toEqual({ token: "t1", new_password: "longenough1" });
  });
});

describe("tenant page", () => {
  it("shows a neutral unavailable page for an unknown bot", async () => {
    hosted({
      "GET /api/public/config": () => errorResponse(404, "BOT_UNAVAILABLE", "This assistant is unavailable."),
    });
    renderAt("/b/nobody");
    expect(await screen.findByRole("heading", { name: /this assistant is unavailable/i })).toBeTruthy();
  });

  it("server error state", async () => {
    hosted({ "GET /api/public/config": () => errorResponse(500, "X", "boom") });
    renderAt("/b/alice");
    expect((await screen.findByRole("alert")).textContent).toMatch(/can't reach/i);
  });
});

describe("login links", () => {
  it("hosted login offers sign-up and reset", async () => {
    hosted();
    renderAt("/admin/login");
    expect(await screen.findByRole("link", { name: /create an account/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /forgot password/i })).toBeTruthy();
  });

  it("single-mode login has no sign-up link", async () => {
    mockApi({ "GET /api/setup/status": () => jsonResponse({ setup_required: false }) });
    renderAt("/admin/login");
    await screen.findByRole("button", { name: /log in/i });
    await waitFor(() => expect(screen.queryByRole("link", { name: /create an account/i })).toBeNull());
  });
});
