import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

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
const health = () => jsonResponse({ ready: true, model: "gpt-4o-mini" });
const me = () => jsonResponse({ email: "o@example.com", bot_name: "Bot", bot_slug: "bot" });
const PROVIDERS = [
  {
    id: "openai",
    name: "OpenAI",
    key_required: true,
    default_base_url: "https://api.openai.com/v1",
    key_url: "https://platform.openai.com/api-keys",
    suggested_models: ["gpt-4o-mini"],
    base_url_required: false,
  },
  {
    id: "ollama",
    name: "Ollama",
    key_required: false,
    default_base_url: "http://127.0.0.1:11434",
    key_url: null,
    suggested_models: ["gemma3"],
    base_url_required: false,
  },
];
const LLM_CONFIG = {
  configured: true,
  status: "ok",
  provider: "openai",
  model: "gpt-4o-mini",
  base_url: null,
  has_key: true,
  api_key_last4: "9876",
  temperature: 0.4,
  max_tokens: 600,
  last_tested_at: "2026-10-15T10:00:00Z",
  last_test_ok: true,
};

function setupRoutes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: true }),
    "GET /api/setup/llm-providers": () => jsonResponse({ providers: PROVIDERS }),
    "POST /api/setup/llm-models": () => jsonResponse({ models: ["gpt-4o-mini", "gpt-4o"] }),
    "POST /api/setup/llm-test": () => jsonResponse({ ok: true, latency_ms: 42 }),
    ...extra,
  });
}

const type = (label: RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

async function fillAccount() {
  fireEvent.change(await screen.findByLabelText(/^email/i), { target: { value: "a@b.com" } });
  type(/^password/i, "longenough1");
  type(/confirm password/i, "longenough1");
  fireEvent.click(screen.getByRole("button", { name: /^next/i }));
  await screen.findByLabelText(/^provider/i);
}

async function passProviderStep() {
  fireEvent.change(screen.getByLabelText(/^provider/i), { target: { value: "openai" } });
  type(/api key/i, "sk-secret-1234");
  type(/^model/i, "gpt-4o-mini");
  fireEvent.click(screen.getByRole("button", { name: /test connection/i }));
  await screen.findByText(/connection works/i);
}

describe("first-run setup wizard", () => {
  it.each(["/", "/admin", "/admin/login"])("redirects %s to /setup when required", async (p) => {
    setupRoutes();
    renderAt(p);
    await waitFor(() => expect(where()).toBe("/setup"));
    expect(await screen.findByRole("heading", { name: /set up/i })).toBeInTheDocument();
  });

  it("sends /setup to the login page once setup is done", async () => {
    mockApi({ "GET /api/setup/status": () => jsonResponse({ setup_required: false }) });
    renderAt("/setup");
    await waitFor(() => expect(where()).toBe("/admin/login"));
  });

  it("validates the account step before moving on", async () => {
    setupRoutes();
    renderAt("/setup");
    fireEvent.change(await screen.findByLabelText(/^email/i), { target: { value: "a@b.com" } });
    type(/^password/i, "longenough1");
    type(/confirm password/i, "different11");
    fireEvent.click(screen.getByRole("button", { name: /^next/i }));
    expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^provider/i)).not.toBeInTheDocument();
  });

  it("keeps Next disabled on the provider step until a test passes", async () => {
    setupRoutes();
    renderAt("/setup");
    await fillAccount();
    const next = screen.getByRole("button", { name: /^next/i });
    expect(next).toBeDisabled();
    await passProviderStep();
    expect(next).toBeEnabled();
    // Any change invalidates the test.
    type(/api key/i, "sk-other-0000");
    expect(next).toBeDisabled();
  });

  it("shows the provider's error when the test fails", async () => {
    setupRoutes({
      "POST /api/setup/llm-test": () =>
        errorResponse(422, "LLM_TEST_FAILED", "OpenAI rejected the API key (401)"),
    });
    renderAt("/setup");
    await fillAccount();
    fireEvent.change(screen.getByLabelText(/^provider/i), { target: { value: "openai" } });
    type(/api key/i, "sk-bad");
    type(/^model/i, "gpt-4o-mini");
    fireEvent.click(screen.getByRole("button", { name: /test connection/i }));
    expect(await screen.findByText("OpenAI rejected the API key (401)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^next/i })).toBeDisabled();
  });

  it("key field is a password field with autocomplete off and a Get-a-key link", async () => {
    setupRoutes();
    renderAt("/setup");
    await fillAccount();
    fireEvent.change(screen.getByLabelText(/^provider/i), { target: { value: "openai" } });
    const key = screen.getByLabelText(/api key/i);
    expect(key).toHaveAttribute("type", "password");
    expect(key).toHaveAttribute("autocomplete", "off");
    expect(screen.getByRole("link", { name: /get a key/i })).toHaveAttribute(
      "href",
      "https://platform.openai.com/api-keys",
    );
  });

  it("going back keeps entered values", async () => {
    setupRoutes();
    renderAt("/setup");
    await fillAccount();
    await passProviderStep();
    fireEvent.click(screen.getByRole("button", { name: /^next/i }));
    await screen.findByLabelText(/bot name/i);
    type(/bot name/i, "Jane Doe!");
    fireEvent.click(screen.getByRole("button", { name: /^back/i }));
    expect(screen.getByLabelText(/^model/i)).toHaveValue("gpt-4o-mini");
    expect(screen.getByLabelText(/api key/i)).toHaveValue("sk-secret-1234");
    fireEvent.click(screen.getByRole("button", { name: /^back/i }));
    expect(screen.getByLabelText(/^email/i)).toHaveValue("a@b.com");
    fireEvent.click(screen.getByRole("button", { name: /^next/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^next/i }));
    expect(await screen.findByLabelText(/bot name/i)).toHaveValue("Jane Doe!");
    expect(screen.getByLabelText(/^slug/i)).toHaveValue("jane-doe");
  });

  it("consent is unchecked by default and the slug is validated", async () => {
    const { calls } = setupRoutes();
    renderAt("/setup");
    await fillAccount();
    await passProviderStep();
    fireEvent.click(screen.getByRole("button", { name: /^next/i }));
    expect(await screen.findByLabelText(/register this install/i)).not.toBeChecked();
    type(/bot name/i, "Bot");
    type(/^slug/i, "Bad Slug");
    fireEvent.click(screen.getByRole("button", { name: /finish setup/i }));
    expect(await screen.findByText(/3–40 lowercase/i)).toBeInTheDocument();
    expect(calls.some((c) => c.key === "POST /api/setup")).toBe(false);
  });

  it("What's sent? opens the explanation inline and links the README anchor", async () => {
    setupRoutes();
    renderAt("/setup");
    await fillAccount();
    await passProviderStep();
    fireEvent.click(screen.getByRole("button", { name: /^next/i }));
    const toggle = await screen.findByRole("button", { name: /what's sent\?/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/never sent:/i)).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/never sent:/i)).toBeInTheDocument();
    expect(screen.getByText(/random install id/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /details in the readme/i })).toHaveAttribute(
      "href",
      "README.md#telemetry",
    );
    // The consent checkbox keeps its wording and stays unchecked.
    expect(screen.getByLabelText(/register this install with the mebot project/i)).not.toBeChecked();
  });

  it("submits everything and lands in the admin panel", async () => {
    let done = false;
    const { calls } = setupRoutes({
      "GET /api/setup/status": () => jsonResponse({ setup_required: !done }),
      "POST /api/setup": () => {
        done = true;
        return jsonResponse({ email: "a@b.com", bot_slug: "bot" }, 201);
      },
      "GET /api/auth/me": me,
      "GET /api/health": health,
      "GET /api/admin/llm": () => jsonResponse(LLM_CONFIG),
      "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    });
    document.cookie = "mebot_csrf=tok123";
    renderAt("/setup");
    await fillAccount();
    await passProviderStep();
    fireEvent.click(screen.getByRole("button", { name: /^next/i }));
    type(await screen.findByLabelText(/bot name/i).then(() => /bot name/i), "Bot");
    fireEvent.click(screen.getByRole("button", { name: /finish setup/i }));
    await waitFor(() => expect(where()).toBe("/admin"));
    const post = calls.find((c) => c.key === "POST /api/setup")!;
    expect(JSON.parse(post.init!.body as string)).toMatchObject({
      email: "a@b.com",
      bot_slug: "bot",
      registration_consent: false,
      llm: { provider: "openai", model: "gpt-4o-mini", api_key: "sk-secret-1234" },
    });
    expect((post.init!.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok123");
  });

  it("returns to the provider step if the final test fails", async () => {
    setupRoutes({
      "POST /api/setup": () =>
        errorResponse(
          422,
          "LLM_TEST_FAILED",
          "OpenAI rate limited the request, try again shortly.",
        ),
    });
    renderAt("/setup");
    await fillAccount();
    await passProviderStep();
    fireEvent.click(screen.getByRole("button", { name: /^next/i }));
    type(await screen.findByLabelText(/bot name/i).then(() => /bot name/i), "Bot");
    fireEvent.click(screen.getByRole("button", { name: /finish setup/i }));
    expect(await screen.findByText(/rate limited/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^provider/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^next/i })).toBeDisabled();
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
    type(/^password/i, "nope");
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
      "GET /api/admin/llm": () => jsonResponse(LLM_CONFIG),
      "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    });
    renderAt("/admin/login");
    fireEvent.change(await screen.findByLabelText(/^email/i), { target: { value: "a@b.com" } });
    type(/^password/i, "longenough1");
    fireEvent.click(screen.getByRole("button", { name: /log in/i }));
    await waitFor(() => expect(where()).toBe("/admin"));
  });

  it("logs out from the admin panel", async () => {
    const { calls } = mockApi({
      "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
      "GET /api/auth/me": me,
      "GET /api/health": health,
      "GET /api/admin/llm": () => jsonResponse(LLM_CONFIG),
      "POST /api/session": () => jsonResponse({ session_id: "s1" }),
      "POST /api/auth/logout": () => new Response(null, { status: 204 }),
    });
    renderAt("/admin");
    fireEvent.click(await screen.findByRole("button", { name: /log out/i }));
    await waitFor(() => expect(where()).toBe("/admin/login"));
    expect(calls.some((c) => c.key === "POST /api/auth/logout")).toBe(true);
  });
});

describe("AI provider admin", () => {
  function adminRoutes(cfg: object, extra: Record<string, Handler> = {}) {
    return mockApi({
      "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
      "GET /api/auth/me": me,
      "GET /api/health": health,
      "POST /api/session": () => jsonResponse({ session_id: "s1" }),
      "GET /api/admin/llm": () => jsonResponse(cfg),
      "GET /api/admin/llm/providers": () => jsonResponse({ providers: PROVIDERS }),
      "POST /api/admin/llm/models": () => jsonResponse({ models: ["gpt-4o-mini"] }),
      ...extra,
    });
  }

  it("shows a blocking banner when no provider is configured", async () => {
    adminRoutes({ ...LLM_CONFIG, configured: false, status: "missing", provider: null });
    renderAt("/admin");
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/no ai provider/i);
    expect(screen.getByRole("link", { name: /set up ai provider/i })).toHaveAttribute(
      "href",
      "/admin/llm",
    );
  });

  it("shows a banner when the last test failed", async () => {
    adminRoutes({ ...LLM_CONFIG, last_test_ok: false });
    renderAt("/admin");
    expect(await screen.findByRole("alert")).toHaveTextContent(/last call .* failed/i);
  });

  it("no banner when configured and working", async () => {
    adminRoutes(LLM_CONFIG);
    renderAt("/admin");
    await screen.findByRole("button", { name: /log out/i });
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("AI provider page masks the key and keeps it when saving without a new one", async () => {
    const { calls } = adminRoutes(LLM_CONFIG, {
      "PUT /api/admin/llm": () => jsonResponse({ ...LLM_CONFIG, model: "gpt-4o" }),
    });
    renderAt("/admin/llm");
    expect(await screen.findByText("••••9876")).toBeInTheDocument();
    const key = screen.getByLabelText(/api key/i);
    expect(key).toHaveValue("");
    expect(key).toHaveAttribute("autocomplete", "off");
    type(/^model/i, "gpt-4o");
    fireEvent.click(screen.getByRole("button", { name: /^save/i }));
    expect(await screen.findByText(/saved/i)).toBeInTheDocument();
    const put = calls.find((c) => c.key === "PUT /api/admin/llm")!;
    const body = JSON.parse(put.init!.body as string);
    expect(body).toMatchObject({ provider: "openai", model: "gpt-4o" });
    expect(body).not.toHaveProperty("api_key");
  });

  it("AI provider page shows the backend error when save fails", async () => {
    adminRoutes(LLM_CONFIG, {
      "PUT /api/admin/llm": () =>
        errorResponse(422, "LLM_TEST_FAILED", "OpenAI could not find that model (404)"),
    });
    renderAt("/admin/llm");
    await screen.findByText("••••9876");
    type(/^model/i, "gpt-nope");
    fireEvent.click(screen.getByRole("button", { name: /^save/i }));
    expect(await screen.findByText("OpenAI could not find that model (404)")).toBeInTheDocument();
  });
});
