import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const CONFIG = { turnstile_site_key: null, max_message_chars: 50, paused: false };

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/health": () => jsonResponse({ ready: true, model: "gpt-4o-mini" }),
    "GET /api/public/config": () => jsonResponse(CONFIG),
    "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    ...extra,
  });
}

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

function ask(input: HTMLElement, text: string) {
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
}

afterEach(() => {
  delete (window as { turnstile?: unknown }).turnstile;
});

describe("recruiter chat limits", () => {
  it("limits input length and shows a counter", async () => {
    routes();
    const input = await enter();
    expect(input).toHaveAttribute("maxLength", "50");
    fireEvent.change(input, { target: { value: "hello" } });
    expect(screen.getByText("5/50")).toBeInTheDocument();
  });

  it("shows the friendly 429 message and disables send for Retry-After", async () => {
    routes({
      "POST /api/chat": () => {
        const r = errorResponse(429, "RATE_LIMITED", "You're sending messages quickly — please wait a minute.", [
          { field: "scope", message: "ip_minute" },
        ]);
        r.headers.set("Retry-After", "42");
        return r;
      },
    });
    const input = await enter();
    ask(input, "hi");
    expect(await screen.findByText(/please wait a minute/i)).toBeInTheDocument();
    expect(screen.queryByText(/connection error/i)).toBeNull();
    const btn = screen.getByRole("button", { name: /wait 4[12]s/i });
    expect(btn).toBeDisabled();
  });

  it("shows the paused message from the server", async () => {
    routes({
      "POST /api/chat": () => errorResponse(503, "BOT_PAUSED", "Back on Monday!"),
    });
    const input = await enter();
    ask(input, "hi");
    expect(await screen.findByText(/back on monday/i)).toBeInTheDocument();
  });

  it("tells visitors up front when the bot is paused", async () => {
    routes({ "GET /api/public/config": () => jsonResponse({ ...CONFIG, paused: true }) });
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    fireEvent.change(await screen.findByLabelText(/your name/i), { target: { value: "Jo" } });
    fireEvent.keyDown(screen.getByLabelText(/your name/i), { key: "Enter" });
    expect(await screen.findByText(/paused right now/i)).toBeInTheDocument();
  });

  it("renders Turnstile when configured and sends its token", async () => {
    const renderWidget = vi.fn((_el: HTMLElement, opts: { sitekey: string; callback: (t: string) => void }) => {
      setTimeout(() => opts.callback("tok-1"), 0);
      return "w1";
    });
    (window as { turnstile?: unknown }).turnstile = { render: renderWidget, remove: vi.fn() };
    const api = routes({
      "GET /api/public/config": () => jsonResponse({ ...CONFIG, turnstile_site_key: "site-1" }),
    });
    await enter();
    expect(renderWidget).toHaveBeenCalled();
    expect(renderWidget.mock.calls[0][1].sitekey).toBe("site-1");
    const call = api.calls.find((c) => c.key === "POST /api/session")!;
    expect(JSON.parse(String(call.init!.body)).turnstile_token).toBe("tok-1");
  });
});
