import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const BASE = {
  configured: false,
  linked: false,
  bot_username: null,
  bot_token_last4: null,
  mode: "polling",
  webhook_available: false,
  error: null,
  digest_hour: 21,
  timezone: "UTC",
  outbox: { pending: 0, failed: 0, dead: 0, last_sent_at: null },
  notify_new_session: true,
  notify_every_question: false,
  notify_unanswered: true,
  notify_contact: true,
  notify_limits: true,
  daily_digest: true,
};
const CONFIGURED = { ...BASE, configured: true, bot_username: "jane_mebot", bot_token_last4: "wxyz" };
const LINKED = { ...CONFIGURED, linked: true };

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () =>
      jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/health": () => jsonResponse({ ready: true, model: "m" }),
    "GET /api/public/config": () =>
      jsonResponse({ turnstile_site_key: null, max_message_chars: 1000, paused: false, owner_name: "Jane" }),
    "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    "GET /api/admin/llm": () =>
      jsonResponse({ configured: true, status: "ok", last_test_ok: true, model: "m" }),
    "GET /api/admin/limits": () => jsonResponse({ paused: false }),
    "GET /api/admin/unanswered": () => jsonResponse({ items: [] }),
    "GET /api/admin/log": () => jsonResponse([]),
    "GET /api/admin/sessions": () => jsonResponse([]),
    "GET /api/admin/telegram": () => jsonResponse(BASE),
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

afterEach(() => {
  vi.useRealTimers();
});

describe("notifications page", () => {
  it("is in the sidebar and shows the BotFather guide when nothing is set up", async () => {
    routes();
    renderAt("/admin/notifications");
    expect(await screen.findByRole("heading", { name: /^notifications$/i })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: /admin/i });
    expect(within(nav).getByRole("link", { name: /^notifications$/i })).toBeInTheDocument();
    expect(await screen.findByText(/how to create a bot with @botfather/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/bot token/i)).toHaveValue("");
    expect(screen.queryByRole("button", { name: /connect telegram/i })).toBeNull();
  });

  it("saves a token and then shows it masked", async () => {
    const api = routes({ "PUT /api/admin/telegram": () => jsonResponse(CONFIGURED) });
    renderAt("/admin/notifications");
    fireEvent.change(await screen.findByLabelText(/bot token/i), {
      target: { value: "123456:abcdefghijklmnopqrstuvwxyz" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save token/i }));
    expect(await screen.findByText(/••••wxyz/)).toBeInTheDocument();
    expect(screen.getByText(/@jane_mebot/)).toBeInTheDocument();
    expect(lastBody(api.calls, "PUT /api/admin/telegram")).toEqual({
      bot_token: "123456:abcdefghijklmnopqrstuvwxyz",
    });
    expect(screen.getByLabelText(/bot token/i)).toHaveValue("");
  });

  it("shows the backend error for a rejected token", async () => {
    routes({
      "PUT /api/admin/telegram": () =>
        errorResponse(422, "TELEGRAM_TOKEN_INVALID", "Telegram rejected this token.", [
          { field: "bot_token", message: "rejected by Telegram" },
        ]),
    });
    renderAt("/admin/notifications");
    fireEvent.change(await screen.findByLabelText(/bot token/i), { target: { value: "1:x" } });
    fireEvent.click(screen.getByRole("button", { name: /save token/i }));
    expect(await screen.findByText(/telegram rejected this token/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/bot token/i)).toHaveAttribute("aria-invalid", "true");
  });

  it("connects: shows the deep link and a QR code, polls until linked", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let linked = false;
    routes({
      "GET /api/admin/telegram": () => jsonResponse(linked ? LINKED : CONFIGURED),
      "POST /api/admin/telegram/link": () =>
        jsonResponse({
          deep_link: "https://t.me/jane_mebot?start=code123",
          expires_at: "2026-10-16T10:10:00Z",
        }),
    });
    renderAt("/admin/notifications");
    fireEvent.click(await screen.findByRole("button", { name: /connect telegram/i }));
    const link = await screen.findByRole("link", { name: /t\.me\/jane_mebot/i });
    expect(link).toHaveAttribute("href", "https://t.me/jane_mebot?start=code123");
    expect(await screen.findByRole("img", { name: /qr code/i })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: /waiting/i })).toBeInTheDocument();
    linked = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });
    expect(await screen.findByText(/linked ✓/i)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /qr code/i })).toBeNull();
  });

  it("saves toggles, digest hour, timezone; webhook disabled without PUBLIC_URL", async () => {
    const api = routes({
      "GET /api/admin/telegram": () => jsonResponse(LINKED),
      "PATCH /api/admin/telegram": (init) =>
        jsonResponse({ ...LINKED, ...JSON.parse(String(init!.body)) }),
    });
    renderAt("/admin/notifications");
    expect(await screen.findByLabelText(/webhook/i)).toBeDisabled();
    expect(screen.getByLabelText(/long polling/i)).toBeChecked();
    fireEvent.click(screen.getByLabelText(/every question/i));
    fireEvent.change(screen.getByLabelText(/digest hour/i), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText(/^timezone$/i), { target: { value: "Asia/Kolkata" } });
    fireEvent.click(screen.getByRole("button", { name: /save settings/i }));
    await waitFor(() => expect(api.calls.some((c) => c.key === "PATCH /api/admin/telegram")).toBe(true));
    expect(lastBody(api.calls, "PATCH /api/admin/telegram")).toEqual({
      notify_every_question: true,
      digest_hour: 8,
      timezone: "Asia/Kolkata",
    });
  });

  it("shows outbox health, sends a test, unlinks after confirm", async () => {
    let state: Record<string, unknown> = {
      ...LINKED,
      outbox: { pending: 2, failed: 1, dead: 3, last_sent_at: "2026-10-16T09:00:00Z" },
    };
    const api = routes({
      "GET /api/admin/telegram": () => jsonResponse(state),
      "POST /api/admin/telegram/test": () => new Response(null, { status: 204 }),
      "DELETE /api/admin/telegram": () => {
        state = BASE;
        return new Response(null, { status: 204 });
      },
    });
    renderAt("/admin/notifications");
    const health = await screen.findByRole("list", { name: /outbox/i });
    expect(within(health).getByText(/pending/i).closest("li")).toHaveTextContent("2");
    expect(within(health).getByText(/dead/i).closest("li")).toHaveTextContent("3");
    fireEvent.click(screen.getByRole("button", { name: /send test/i }));
    expect(await screen.findByText(/test message sent/i)).toBeInTheDocument();

    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole("button", { name: /unlink/i }));
    expect(api.calls.some((c) => c.key === "DELETE /api/admin/telegram")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /unlink/i }));
    await waitFor(() => expect(api.calls.some((c) => c.key === "DELETE /api/admin/telegram")).toBe(true));
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(await screen.findByLabelText(/bot token/i)).toBeInTheDocument();
  });

  it("shows a load error from the backend", async () => {
    routes({ "GET /api/admin/telegram": () => errorResponse(500, "X", "Database is sad") });
    renderAt("/admin/notifications");
    expect(await screen.findByRole("alert")).toHaveTextContent(/database is sad/i);
  });
});
