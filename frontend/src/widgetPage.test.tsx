import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { checkOrigin } from "./pages/admin/WidgetPage";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const SETTINGS = {
  slug: "jane",
  enabled: true,
  allowed_origins: ["https://jane.dev"],
  allow_any_origin: false,
  primary_color: "#0f766e",
  theme: "auto",
  position: "right",
  title: null,
  avatar_url: null,
  launcher_label: null,
  suggested_questions: ["What does she work on?", "Tech stack?"],
  show_orb: false,
  auto_open_seconds: null,
  needs_origins: false,
};

const SNIPPETS = {
  script: '<script src="https://bot.example.com/widget/v1.js" data-bot="jane" async></script>',
  inline: '<div id="mebot-chat"></div>',
  iframe: '<iframe src="https://bot.example.com/embed/jane?mode=inline"></iframe>',
};

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () => jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/health": () => jsonResponse({ ready: true, model: "m" }),
    "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    "GET /api/admin/llm": () => jsonResponse({ configured: true, status: "ok", last_test_ok: true, model: "m" }),
    "GET /api/admin/widget": () => jsonResponse(SETTINGS),
    "GET /api/admin/widget/snippets": () => jsonResponse(SNIPPETS),
    "GET /api/admin/log": () => jsonResponse([]),
    "GET /api/admin/sessions": () => jsonResponse([]),
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

const lastBody = (calls: { key: string; init?: RequestInit }[], key: string) =>
  JSON.parse(String(calls.filter((c) => c.key === key).slice(-1)[0].init!.body));

describe("checkOrigin", () => {
  it("normalises and rejects like the server", () => {
    expect(checkOrigin("https://Jane.dev/")).toEqual({ origin: "https://jane.dev" });
    expect(checkOrigin("https://jane.dev:443")).toEqual({ origin: "https://jane.dev" });
    expect(checkOrigin("http://localhost:3000")).toEqual({ origin: "http://localhost:3000" });
    expect(checkOrigin("https://*.jane.dev")).toEqual({ origin: "https://*.jane.dev" });
    for (const bad of ["jane.dev", "http://jane.dev", "https://jane.dev/blog", "https://*.dev", "https://a.*.jane.dev"]) {
      expect("error" in checkOrigin(bad)).toBe(true);
    }
  });
});

describe("widget page", () => {
  it("is in the sidebar and shows settings, status, preview and snippets", async () => {
    routes();
    renderAt("/admin/widget");
    expect(await screen.findByRole("heading", { name: "Widget", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Widget" })).toBeInTheDocument();
    expect(await screen.findByText("Widget allowed on 1 site.")).toBeInTheDocument();
    expect(screen.getByText("https://jane.dev")).toBeInTheDocument();
    expect(screen.getByLabelText("Question 1")).toHaveValue("What does she work on?");
    const preview = await screen.findByTitle("Widget preview");
    expect(preview.getAttribute("src")).toContain("/widget-test?");
    expect(preview.getAttribute("src")).toContain("color=%230f766e");
    expect(await screen.findByText(SNIPPETS.script)).toBeInTheDocument();
  });

  it("shows a loading state, then an error when settings fail to load", async () => {
    routes({ "GET /api/admin/widget": () => errorResponse(500, "X", "Server down") });
    renderAt("/admin/widget");
    expect(await screen.findByRole("alert")).toHaveTextContent("Server down");
  });

  it("adds, validates and removes allowed sites, then saves", async () => {
    const api = routes({
      "PUT /api/admin/widget": (init) => jsonResponse({ ...SETTINGS, ...JSON.parse(String(init!.body)) }),
    });
    renderAt("/admin/widget");
    const input = await screen.findByLabelText("add a site");
    fireEvent.change(input, { target: { value: "http://evil.dev" } });
    fireEvent.click(screen.getByRole("button", { name: "add" }));
    expect(await screen.findByText(/https is required/i)).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "https://*.Jane.dev" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("https://*.jane.dev")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove https://jane.dev" }));
    fireEvent.click(screen.getByRole("button", { name: /save widget/i }));
    await waitFor(() => expect(api.calls.some((c) => c.key === "PUT /api/admin/widget")).toBe(true));
    expect(lastBody(api.calls, "PUT /api/admin/widget").allowed_origins).toEqual(["https://*.jane.dev"]);
  });

  it("validates colour and auto-open before saving, and shows server field errors", async () => {
    const api = routes({
      "PUT /api/admin/widget": () =>
        errorResponse(422, "VALIDATION_ERROR", "Invalid request", [{ field: "title", message: "too long" }]),
    });
    renderAt("/admin/widget");
    fireEvent.change(await screen.findByLabelText("brand colour"), { target: { value: "red" } });
    fireEvent.change(screen.getByLabelText("auto-open after (seconds)"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: /save widget/i }));
    expect(await screen.findByText(/hex colour/i)).toBeInTheDocument();
    expect(screen.getByText(/5–120 seconds/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.key === "PUT /api/admin/widget")).toBe(false);
    fireEvent.change(screen.getByLabelText("brand colour"), { target: { value: "#1d4ed8" } });
    fireEvent.change(screen.getByLabelText("auto-open after (seconds)"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /save widget/i }));
    expect(await screen.findByText("too long")).toBeInTheDocument();
    const body = lastBody(api.calls, "PUT /api/admin/widget");
    expect(body.primary_color).toBe("#1d4ed8");
    expect(body.auto_open_seconds).toBeNull();
  });

  it("reorders and edits suggested questions (max 6)", async () => {
    const api = routes({
      "PUT /api/admin/widget": (init) => jsonResponse({ ...SETTINGS, ...JSON.parse(String(init!.body)) }),
    });
    renderAt("/admin/widget");
    fireEvent.click(await screen.findByRole("button", { name: "Move question 2 up" }));
    expect(screen.getByLabelText("Question 1")).toHaveValue("Tech stack?");
    const add = screen.getByRole("button", { name: /add question/i });
    for (let i = 0; i < 4; i++) fireEvent.click(add);
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Question 3"), { target: { value: "Open to remote?" } });
    fireEvent.click(screen.getByRole("button", { name: /save widget/i }));
    await waitFor(() => expect(api.calls.some((c) => c.key === "PUT /api/admin/widget")).toBe(true));
    expect(lastBody(api.calls, "PUT /api/admin/widget").suggested_questions).toEqual([
      "Tech stack?",
      "What does she work on?",
      "Open to remote?",
    ]);
  });

  it("allow any site needs an explicit confirm", async () => {
    const api = routes({
      "PUT /api/admin/widget": (init) => jsonResponse({ ...SETTINGS, ...JSON.parse(String(init!.body)) }),
    });
    renderAt("/admin/widget");
    fireEvent.click(await screen.findByRole("button", { name: /allow any site…/i }));
    const dialog = screen.getByRole("alertdialog", { name: /confirm allow any site/i });
    expect(api.calls.some((c) => c.key === "PUT /api/admin/widget")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: /yes, allow any site/i }));
    await waitFor(() => expect(screen.getByText("Widget allowed on any site.")).toBeInTheDocument());
    expect(lastBody(api.calls, "PUT /api/admin/widget")).toEqual({ allow_any_origin: true, confirm_any_origin: true });
  });

  it("copies snippets", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    routes();
    renderAt("/admin/widget");
    fireEvent.click(await screen.findByRole("button", { name: "Copy Floating bubble (recommended)" }));
    expect(writeText).toHaveBeenCalledWith(SNIPPETS.script);
    expect(await screen.findByText("copied")).toBeInTheDocument();
  });
});
