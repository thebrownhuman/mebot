import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import {
  errorResponse,
  jsonResponse,
  mockApi,
  type Handler,
} from "./test/fetchMock";

vi.mock("./components/Orb", () => ({
  default: () => <div data-testid="orb" />,
}));

const LIMITS = {
  per_ip_per_minute: 10,
  per_ip_per_day: 100,
  per_session_messages: 40,
  sessions_per_ip_per_hour: 10,
  daily_message_cap: 500,
  daily_token_cap: null,
  max_message_chars: 1000,
  history_turns: 12,
  paused: false,
  paused_message: null,
  turnstile_enabled: false,
  turnstile_available: false,
};

const day = (date: string, over: Record<string, unknown> = {}) => ({
  date,
  messages: 0,
  tokens: 0,
  tokens_estimated: false,
  rate_limited: 0,
  leak_blocked: 0,
  ...over,
});

const USAGE = {
  days: [
    day("2026-10-16", { messages: 132, tokens: 81234, rate_limited: 4 }),
    day("2026-10-15", {
      messages: 12,
      tokens: 900,
      tokens_estimated: true,
      leak_blocked: 1,
    }),
  ],
  top_visitors: [{ ip_hash: "a3f9…", messages: 38 }],
};

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () =>
      jsonResponse({
        email: "o@example.com",
        bot_name: "Jane",
        bot_slug: "jane",
      }),
    "GET /api/health": () =>
      jsonResponse({ ready: true, model: "gpt-4o-mini" }),
    "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    "GET /api/admin/llm": () =>
      jsonResponse({
        configured: true,
        status: "ok",
        last_test_ok: true,
        model: "m",
      }),
    "GET /api/admin/limits": () => jsonResponse(LIMITS),
    "GET /api/admin/usage": () => jsonResponse(USAGE),
    "GET /api/admin/unanswered": () => jsonResponse({ items: [] }),
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

const sentBody = (calls: { key: string; init?: RequestInit }[], key: string) =>
  JSON.parse(String(calls.filter((c) => c.key === key).slice(-1)[0].init!.body));

describe("limits page", () => {
  it("is in the sidebar and shows the form and usage", async () => {
    routes();
    renderAt("/admin/limits");
    expect(
      await screen.findByRole("heading", { name: /^limits$/i }),
    ).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: /admin/i });
    expect(
      within(nav).getByRole("link", { name: /^limits$/i }),
    ).toBeInTheDocument();
    expect(
      await screen.findByLabelText(/messages per minute per visitor/i),
    ).toHaveValue(10);
    expect(screen.getByLabelText(/total messages per day/i)).toHaveValue(500);
    const table = screen.getByRole("table", { name: /usage/i });
    expect(within(table).getByText("2026-10-16")).toBeInTheDocument();
    expect(within(table).getByText("132")).toBeInTheDocument();
    expect(within(table).getByText("900")).toBeInTheDocument();
    expect(within(table).getByText(/(est.)/)).toBeInTheDocument();
    expect(screen.getByText("a3f9…")).toBeInTheDocument();
  });

  it("applies a preset and saves", async () => {
    const api = routes({
      "PUT /api/admin/limits": (init) =>
        jsonResponse({ ...LIMITS, ...JSON.parse(String(init!.body)) }),
    });
    renderAt("/admin/limits");
    await screen.findByLabelText(/messages per minute per visitor/i);
    fireEvent.click(screen.getByRole("button", { name: /^strict$/i }));
    expect(
      screen.getByLabelText(/messages per minute per visitor/i),
    ).toHaveValue(5);
    fireEvent.click(screen.getByRole("button", { name: /save limits/i }));
    await waitFor(() =>
      expect(api.calls.some((c) => c.key === "PUT /api/admin/limits")).toBe(
        true,
      ),
    );
    const body = sentBody(api.calls, "PUT /api/admin/limits");
    expect(body.per_ip_per_minute).toBe(5);
    expect(body.daily_message_cap).toBe(200);
    expect(await screen.findByText(/limits saved/i)).toBeInTheDocument();
  });

  it("shows field errors from the server", async () => {
    routes({
      "PUT /api/admin/limits": () =>
        errorResponse(422, "VALIDATION_ERROR", "Invalid request", [
          {
            field: "history_turns",
            message: "Input should be less than or equal to 50",
          },
        ]),
    });
    renderAt("/admin/limits");
    await screen.findByLabelText(/messages per minute per visitor/i);
    fireEvent.click(screen.getByRole("button", { name: /save limits/i }));
    expect(
      await screen.findByText(/less than or equal to 50/i),
    ).toBeInTheDocument();
  });

  it("pauses the bot with a custom message", async () => {
    const api = routes({
      "PUT /api/admin/limits": (init) =>
        jsonResponse({ ...LIMITS, ...JSON.parse(String(init!.body)) }),
    });
    renderAt("/admin/limits");
    await screen.findByLabelText(/messages per minute per visitor/i);
    fireEvent.change(screen.getByLabelText(/message shown while paused/i), {
      target: { value: "Back Monday" },
    });
    fireEvent.click(screen.getByRole("button", { name: /pause the bot/i }));
    await waitFor(() =>
      expect(api.calls.some((c) => c.key === "PUT /api/admin/limits")).toBe(
        true,
      ),
    );
    expect(sentBody(api.calls, "PUT /api/admin/limits")).toEqual({
      paused: true,
      paused_message: "Back Monday",
    });
    expect(
      await screen.findByRole("button", { name: /resume the bot/i }),
    ).toBeInTheDocument();
  });

  it("disables the Turnstile toggle without env keys", async () => {
    routes();
    renderAt("/admin/limits");
    const box = await screen.findByLabelText(/require cloudflare turnstile/i);
    expect(box).toBeDisabled();
    expect(screen.getByText(/TURNSTILE_SITE_KEY/)).toBeInTheDocument();
  });

  it("shows an error state when limits fail to load", async () => {
    routes({ "GET /api/admin/limits": () => errorResponse(500, "X", "boom") });
    renderAt("/admin/limits");
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/i);
  });
});

describe("dashboard banners", () => {
  it("warns when paused", async () => {
    routes({
      "GET /api/admin/limits": () => jsonResponse({ ...LIMITS, paused: true }),
    });
    renderAt("/admin");
    expect(await screen.findByText(/the bot is paused/i)).toBeInTheDocument();
  });

  it("warns at 80% of the daily cap", async () => {
    routes({
      "GET /api/admin/usage": () =>
        jsonResponse({
          days: [day("2026-10-16", { messages: 400 })],
          top_visitors: [],
        }),
    });
    renderAt("/admin");
    expect(
      await screen.findByText(/80% of today's message cap/i),
    ).toBeInTheDocument();
  });

  it("no banner under 80%", async () => {
    routes();
    renderAt("/admin");
    await screen.findByRole("navigation", { name: /admin/i });
    await waitFor(() =>
      expect(screen.queryByText(/today's message cap/i)).toBeNull(),
    );
    expect(screen.queryByText(/the bot is paused/i)).toBeNull();
  });
});
