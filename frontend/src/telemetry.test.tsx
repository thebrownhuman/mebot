import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { TelemetryView } from "./lib/api";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const PAYLOAD = {
  install_id: "9f2c41aa00000000000000000000beef",
  public_key: "a2V5",
  version: "0.9.0",
  mode: "single",
};

function view(over: Partial<TelemetryView> = {}): TelemetryView {
  return {
    telemetry: "on",
    registry_url: "https://registry.shivanshmishra.in",
    consent: false,
    status: "not_registered",
    registered_at: null,
    last_register_error: null,
    install_id_prefix: "9f2c41aa",
    update_contact_email: null,
    effective_email: "o@example.com",
    public_url: "https://bot.example.dev",
    last_heartbeat: null,
    payload_preview: PAYLOAD,
    last_check_at: null,
    update: {
      current: "0.9.0",
      latest: null,
      available: false,
      dismissed: false,
      unsupported: false,
      advisory: null,
    },
    ...over,
  };
}

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () =>
      jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/admin/llm": () => jsonResponse({ configured: true, last_test_ok: true }),
    "GET /api/admin/open-questions": () => jsonResponse({ items: [], open_count: 0 }),
    "GET /api/admin/account": () =>
      jsonResponse({ timezone: "UTC", retention_days: 180, retention_choices: [30, 90, 180, 365] }),
    "GET /api/admin/telemetry": () => jsonResponse(view()),
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

// The section renders "loading…" first; wait for the form unless the test wants that state.
const section = async (loaded = true) => {
  const s = (await screen.findByRole("heading", { name: "mebot project" })).closest("section")!;
  if (loaded) await within(s).findByLabelText(/contact e-mail/i);
  return s;
};

describe("account: mebot project", () => {
  it.each([
    [{ status: "not_registered" }, /^Not registered\.$/],
    [{ status: "waiting_for_public_url", consent: true, public_url: null }, /Set PUBLIC_URL to register/],
    [{ status: "off", telemetry: "off" }, /off by server setting \(TELEMETRY=off\)/],
    [
      { status: "registered", consent: true, registered_at: "2026-10-17T10:00:00Z" },
      /Registered on .* as o@example.com for https:\/\/bot.example.dev/,
    ],
    [
      { status: "pending", consent: true, last_register_error: "network: ConnectError" },
      /last attempt failed \(network: ConnectError\)/,
    ],
    [{ status: "unregister_pending" }, /Removing your registration/],
    [{ status: "unavailable" }, /install key .* could not be read/],
  ] as [Partial<TelemetryView>, RegExp][])("shows the state %j", async (over, text) => {
    routes({ "GET /api/admin/telemetry": () => jsonResponse(view(over)) });
    renderAt("/admin/account");
    const s = await section();
    expect(within(s).getByRole("status")).toHaveTextContent(text);
  });

  it("shows the server setting, registry host and only the first 8 characters of the id in the summary", async () => {
    routes();
    renderAt("/admin/account");
    const s = await section();
    expect(within(s).getByText("https://registry.shivanshmishra.in")).toBeInTheDocument();
    expect(within(s).getByText("9f2c41aa…")).toBeInTheDocument();
    // Outside "What's sent" (which prints the heartbeat literally) only the prefix appears.
    expect(s.querySelector("dl")!.textContent).not.toContain("00000000");
  });

  it("asks for confirmation, spelling out what is sent, before registering", async () => {
    const { calls } = routes({
      "PUT /api/admin/telemetry": () =>
        jsonResponse(view({ consent: true, status: "pending", registered_at: null })),
    });
    renderAt("/admin/account");
    const s = await section();
    const box = within(s).getByRole("checkbox", { name: /register this install/i });
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    const confirm = within(s).getByRole("group", { name: /confirm/i });
    expect(confirm).toHaveTextContent("o@example.com");
    expect(confirm).toHaveTextContent("https://bot.example.dev");
    expect(confirm).toHaveTextContent("version 0.9.0");
    expect(calls.some((c) => c.key === "PUT /api/admin/telemetry")).toBe(false);
    fireEvent.click(within(confirm).getByRole("button", { name: /yes, register/i }));
    expect(await screen.findByText(/registration requested/i)).toBeInTheDocument();
    expect(
      JSON.parse(calls.find((c) => c.key === "PUT /api/admin/telemetry")!.init!.body as string),
    ).toEqual({ consent: true });
    expect(within(s).queryByRole("group", { name: /confirm/i })).not.toBeInTheDocument();
    expect(within(s).getByRole("checkbox", { name: /register this install/i })).toBeChecked();
  });

  it("cancelling the confirmation changes nothing", async () => {
    const { calls } = routes();
    renderAt("/admin/account");
    const s = await section();
    fireEvent.click(within(s).getByRole("checkbox", { name: /register this install/i }));
    fireEvent.click(within(s).getByRole("button", { name: /cancel/i }));
    expect(within(s).queryByRole("group", { name: /confirm/i })).not.toBeInTheDocument();
    expect(within(s).getByRole("checkbox", { name: /register this install/i })).not.toBeChecked();
    expect(calls.some((c) => c.key.startsWith("PUT /api/admin/telemetry"))).toBe(false);
  });

  it("unticking explains the deletion and sends consent false", async () => {
    const { calls } = routes({
      "GET /api/admin/telemetry": () => jsonResponse(view({ consent: true, status: "registered" })),
      "PUT /api/admin/telemetry": () => jsonResponse(view({ status: "unregister_pending" })),
    });
    renderAt("/admin/account");
    const s = await section();
    fireEvent.click(within(s).getByRole("checkbox", { name: /register this install/i }));
    const confirm = within(s).getByRole("group", { name: /confirm/i });
    expect(confirm).toHaveTextContent(/deletes your registration/i);
    fireEvent.click(within(confirm).getByRole("button", { name: /yes, remove/i }));
    await screen.findByText(/removal requested/i);
    expect(
      JSON.parse(calls.find((c) => c.key === "PUT /api/admin/telemetry")!.init!.body as string),
    ).toEqual({ consent: false });
    expect(within(s).getByRole("status")).toHaveTextContent(/removing your registration/i);
  });

  it("disables consent and e-mail when the server turned telemetry off", async () => {
    routes({ "GET /api/admin/telemetry": () => jsonResponse(view({ telemetry: "off", status: "off" })) });
    renderAt("/admin/account");
    const s = await section();
    expect(within(s).getByRole("checkbox", { name: /register this install/i })).toBeDisabled();
    expect(within(s).getByLabelText(/contact e-mail/i)).toBeDisabled();
  });

  it("saves a contact e-mail, or clears it with null", async () => {
    const { calls } = routes({
      "PUT /api/admin/telemetry": (init) =>
        jsonResponse(view({ update_contact_email: JSON.parse(init!.body as string).update_contact_email })),
    });
    renderAt("/admin/account");
    const s = await section();
    const input = within(s).getByLabelText(/contact e-mail/i);
    const save = within(s).getByRole("button", { name: /save e-mail/i });
    expect(save).toBeDisabled();
    fireEvent.change(input, { target: { value: "  me@x.dev " } });
    fireEvent.click(save);
    expect(await screen.findByText(/contact e-mail saved/i)).toBeInTheDocument();
    expect(JSON.parse(calls.find((c) => c.key === "PUT /api/admin/telemetry")!.init!.body as string)).toEqual({
      update_contact_email: "me@x.dev",
    });
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(within(s).getByRole("button", { name: /save e-mail/i }));
    await waitFor(() =>
      expect(calls.filter((c) => c.key === "PUT /api/admin/telemetry")).toHaveLength(2),
    );
    expect(JSON.parse(calls.filter((c) => c.key === "PUT /api/admin/telemetry")[1].init!.body as string)).toEqual({
      update_contact_email: null,
    });
  });

  it("shows the backend error when saving fails", async () => {
    routes({
      "PUT /api/admin/telemetry": () => errorResponse(422, "VALIDATION_ERROR", "not a valid e-mail address"),
    });
    renderAt("/admin/account");
    const s = await section();
    fireEvent.change(within(s).getByLabelText(/contact e-mail/i), { target: { value: "nope" } });
    fireEvent.click(within(s).getByRole("button", { name: /save e-mail/i }));
    expect(await within(s).findByRole("alert")).toHaveTextContent("not a valid e-mail address");
  });

  it("What's sent shows the literal JSON of the next heartbeat, then of the last one", async () => {
    routes();
    renderAt("/admin/account");
    const s = await section();
    const details = within(s).getByText("What's sent").closest("details")!;
    expect(details.textContent).toContain("Nothing sent yet");
    expect(JSON.parse(details.querySelector("pre")!.textContent!)).toEqual(PAYLOAD);
    expect(details.textContent).toMatch(/no IP address, hostname, URL, e-mail or usage data/);
  });

  it("shows the last heartbeat and its time", async () => {
    const sent = { ...PAYLOAD, version: "0.9.0" };
    routes({
      "GET /api/admin/telemetry": () =>
        jsonResponse(
          view({
            last_heartbeat: { sent_at: "2026-10-16T09:00:00Z", payload: sent },
            last_check_at: "2026-10-16T09:00:01Z",
          }),
        ),
    });
    renderAt("/admin/account");
    const s = await section();
    const details = within(s).getByText("What's sent").closest("details")!;
    expect(details.textContent).toContain("The last heartbeat, exactly as sent");
    expect(within(s).queryByText("never")).not.toBeInTheDocument();
  });

  it("hides the JSON when telemetry is off", async () => {
    routes({
      "GET /api/admin/telemetry": () => jsonResponse(view({ telemetry: "off", status: "off" })),
    });
    renderAt("/admin/account");
    const s = await section();
    expect(s.querySelector("pre")).toBeNull();
  });

  it("links to the registry's privacy notice", async () => {
    routes();
    renderAt("/admin/account");
    const s = await section();
    expect(within(s).getByRole("link", { name: /privacy notice/i })).toHaveAttribute(
      "href",
      "https://registry.shivanshmishra.in/privacy",
    );
  });

  it("has a loading state and an error state with retry", async () => {
    let fail = true;
    routes({
      "GET /api/admin/telemetry": () =>
        fail ? errorResponse(500, "BOOM", "Database is locked") : jsonResponse(view()),
    });
    renderAt("/admin/account");
    const s = await section(false);
    expect(await within(s).findByRole("alert")).toHaveTextContent("Database is locked");
    fail = false;
    fireEvent.click(within(s).getByRole("button", { name: /try again/i }));
    expect(await screen.findByLabelText(/contact e-mail/i)).toBeInTheDocument();
  });
});

describe("admin banners", () => {
  const withUpdate = (update: Partial<TelemetryView["update"]>) =>
    routes({
      "GET /api/admin/telemetry": () =>
        jsonResponse(view({ update: { ...view().update, ...update } })),
    });

  it("shows a dismissible banner for a new release", async () => {
    const { calls } = withUpdate({ latest: "0.10.1", available: true });
    mockDismiss(calls);
    renderAt("/admin");
    const banner = await screen.findByText(/update available: mebot 0\.10\.1 \(you have 0\.9\.0\)/i);
    fireEvent.click(within(banner.parentElement!).getByRole("button", { name: /dismiss/i }));
    await waitFor(() => expect(screen.queryByText(/update available/i)).not.toBeInTheDocument());
    await waitFor(() =>
      expect(calls.some((c) => c.key === "POST /api/admin/telemetry/dismiss-update")).toBe(true),
    );
    expect(
      JSON.parse(calls.find((c) => c.key === "POST /api/admin/telemetry/dismiss-update")!.init!.body as string),
    ).toEqual({ version: "0.10.1" });
  });

  it("stays hidden once dismissed", async () => {
    withUpdate({ latest: "0.10.1", available: true, dismissed: true });
    renderAt("/admin");
    await screen.findByRole("navigation", { name: /admin/i });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(/update available/i)).not.toBeInTheDocument();
  });

  it("shows no banner when up to date or when the check failed", async () => {
    routes({ "GET /api/admin/telemetry": () => errorResponse(500, "X", "boom") });
    renderAt("/admin");
    await screen.findByRole("navigation", { name: /admin/i });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(/update available/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/security advisory/i)).not.toBeInTheDocument();
  });

  it("shows a red advisory that cannot be dismissed, even after a dismissal", async () => {
    withUpdate({
      latest: "0.10.1",
      available: true,
      dismissed: true,
      advisory: { id: "A-1", severity: "high", title: "Session fixation", url: "https://ex.test/a" },
    });
    renderAt("/admin");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/security advisory affects your version \(0\.9\.0\)/i);
    expect(alert).toHaveTextContent("Session fixation");
    expect(alert).toHaveTextContent("Update to mebot 0.10.1");
    expect(within(alert).queryByRole("button")).not.toBeInTheDocument();
    expect(within(alert).getByRole("link", { name: /details/i })).toHaveAttribute("href", "https://ex.test/a");
  });

  it("never renders a non-http advisory link", async () => {
    withUpdate({
      advisory: { id: "A", severity: "low", title: "t", url: "javascript:alert(1)" },
    });
    renderAt("/admin");
    const alert = await screen.findByRole("alert");
    expect(within(alert).queryByRole("link")).not.toBeInTheDocument();
  });
});

function mockDismiss(calls: { key: string; init?: RequestInit }[]) {
  // The default fetch mock answers unknown routes with 404, which the banner ignores; the
  // call is still recorded, which is all these tests need.
  return calls;
}
