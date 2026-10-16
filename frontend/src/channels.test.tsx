import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const LLM = {
  configured: true,
  status: "ok",
  provider: "openai",
  model: "gpt-4o-mini",
  base_url: null,
  has_key: true,
  api_key_last4: "9876",
  temperature: 0.4,
  max_tokens: 600,
  last_tested_at: null,
  last_test_ok: true,
};

const WA_NUMBER_MSG =
  "This looks like a phone number — add it as a Phone channel instead (not shared by default).";

const link = (id: string, kind: string, label: string, value: string, share: boolean, n = 0) => ({
  id,
  kind,
  label,
  value,
  share,
  sort_order: n,
});

function routes(links: unknown[], extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () =>
      jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/health": () => jsonResponse({ ready: true, model: "gpt-4o-mini" }),
    "GET /api/admin/llm": () => jsonResponse(LLM),
    "GET /api/admin/profile/identity": () =>
      jsonResponse({ full_name: "Jane", headline: "", location: "", open_to: "", summary: "" }),
    "GET /api/admin/profile/links": () => jsonResponse({ items: links }),
    ...extra,
  });
}

async function openEditor() {
  render(
    <MemoryRouter initialEntries={["/admin/profile/identity"]}>
      <App />
    </MemoryRouter>,
  );
  return screen.findByRole("heading", { name: /contact channels/i });
}

const body = (calls: { key: string; init?: RequestInit }[], key: string) => {
  const matching = calls.filter((c) => c.key === key);
  return JSON.parse(matching[matching.length - 1].init!.body as string);
};

afterEach(() => vi.restoreAllMocks());

describe("contact channels editor", () => {
  it("replaces the old Links list and the public email/phone fields", async () => {
    routes([]);
    await openEditor();
    expect(screen.queryByRole("heading", { name: /^links$/i })).toBeNull();
    expect(screen.queryByLabelText(/public email/i)).toBeNull();
    expect(screen.queryByLabelText(/public phone/i)).toBeNull();
    expect(await screen.findByText(/add how recruiters can reach you/i)).toBeInTheDocument();
  });

  it("shows channels with their share state", async () => {
    routes([
      link("a", "email", "Email", "jane@example.com", true),
      link("b", "phone", "Phone", "+91 98765 43210", false, 1),
    ]);
    await openEditor();
    expect(await screen.findByText("jane@example.com")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /share email with recruiters/i })).toBeChecked();
    expect(screen.getByRole("switch", { name: /share phone with recruiters/i })).not.toBeChecked();
    expect(screen.getByText(/only you can see this number/i)).toBeInTheDocument();
  });

  it("shows a load error", async () => {
    routes([], {
      "GET /api/admin/profile/links": () => errorResponse(500, "INTERNAL", "Boom"),
    });
    await openEditor();
    expect(await screen.findByText(/boom/i)).toBeInTheDocument();
  });

  it("adds a channel using the kind's placeholder", async () => {
    const { calls } = routes([], {
      "POST /api/admin/profile/links": (init) =>
        jsonResponse({ id: "n1", sort_order: 0, ...JSON.parse(init!.body as string) }, 201),
    });
    await openEditor();
    fireEvent.click(screen.getByRole("button", { name: /add channel/i }));
    const dialog = await screen.findByRole("dialog", { name: /add channel/i });
    fireEvent.change(within(dialog).getByLabelText(/^type/i), { target: { value: "email" } });
    const value = within(dialog).getByLabelText(/^value/i);
    expect(value).toHaveAttribute("placeholder", "you@example.com");
    fireEvent.change(value, { target: { value: "jane@example.com" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(body(calls, "POST /api/admin/profile/links")).toMatchObject({
      kind: "email",
      value: "jane@example.com",
      share: true,
    });
    expect(await screen.findByText("jane@example.com")).toBeInTheDocument();
  });

  it("shows the WhatsApp hint and the server's number rejection", async () => {
    routes([], {
      "POST /api/admin/profile/links": () =>
        errorResponse(422, "VALIDATION_ERROR", "Invalid request", [
          { field: "value", message: WA_NUMBER_MSG },
        ]),
    });
    await openEditor();
    fireEvent.click(screen.getByRole("button", { name: /add channel/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^type/i), { target: { value: "whatsapp" } });
    expect(
      within(dialog).getByText("Use your WhatsApp username, not your number"),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^value/i), {
      target: { value: "+91 98765 43210" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /^save$/i }));
    expect(await within(dialog).findByText(/looks like a phone number/i)).toBeInTheDocument();
  });

  it("a new phone channel is not shared by default and shows the warning", async () => {
    const { calls } = routes([], {
      "POST /api/admin/profile/links": (init) =>
        jsonResponse({ id: "p1", sort_order: 0, ...JSON.parse(init!.body as string) }, 201),
    });
    const confirm = vi.spyOn(window, "confirm");
    await openEditor();
    fireEvent.click(screen.getByRole("button", { name: /add channel/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^type/i), { target: { value: "phone" } });
    expect(
      within(dialog).getByRole("checkbox", { name: /share with recruiters/i }),
    ).not.toBeChecked();
    expect(within(dialog).getByRole("note")).toHaveTextContent(/see and call it/i);
    fireEvent.change(within(dialog).getByLabelText(/^value/i), {
      target: { value: "+91 98765 43210" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(confirm).not.toHaveBeenCalled();
    const sent = body(calls, "POST /api/admin/profile/links");
    expect(sent.share).toBe(false);
    expect(sent.confirm_share_phone).toBeUndefined();
  });

  it("turning phone sharing on asks first and sends the confirmation flag", async () => {
    const { calls } = routes([link("p", "phone", "Phone", "+91 98765 43210", false)], {
      "PUT /api/admin/profile/links/p": () =>
        jsonResponse(link("p", "phone", "Phone", "+91 98765 43210", true)),
    });
    const confirm = vi.spyOn(window, "confirm");
    confirm.mockReturnValueOnce(false).mockReturnValueOnce(true);
    await openEditor();
    const sw = await screen.findByRole("switch", { name: /share phone with recruiters/i });
    fireEvent.click(sw); // declined
    expect(calls.some((c) => c.key === "PUT /api/admin/profile/links/p")).toBe(false);
    expect(sw).not.toBeChecked();
    fireEvent.click(sw); // accepted
    await waitFor(() => expect(sw).toBeChecked());
    expect(body(calls, "PUT /api/admin/profile/links/p")).toEqual({
      share: true,
      confirm_share_phone: true,
    });
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it("turning sharing off needs no confirmation", async () => {
    const { calls } = routes([link("a", "email", "Email", "jane@example.com", true)], {
      "PUT /api/admin/profile/links/a": () =>
        jsonResponse(link("a", "email", "Email", "jane@example.com", false)),
    });
    const confirm = vi.spyOn(window, "confirm");
    await openEditor();
    fireEvent.click(await screen.findByRole("switch", { name: /share email with recruiters/i }));
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: /share email/i })).not.toBeChecked(),
    );
    expect(confirm).not.toHaveBeenCalled();
    expect(body(calls, "PUT /api/admin/profile/links/a")).toEqual({ share: false });
  });

  it("reorders and deletes", async () => {
    const { calls } = routes(
      [
        link("a", "email", "Email", "jane@example.com", true),
        link("b", "x", "X", "https://x.com/jane", true, 1),
      ],
      {
        "PUT /api/admin/profile/links/order": () => new Response(null, { status: 204 }),
        "DELETE /api/admin/profile/links/a": () => new Response(null, { status: 204 }),
      },
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await openEditor();
    fireEvent.click(await screen.findByRole("button", { name: /move x up/i }));
    await waitFor(() =>
      expect(calls.some((c) => c.key === "PUT /api/admin/profile/links/order")).toBe(true),
    );
    expect(body(calls, "PUT /api/admin/profile/links/order")).toEqual({ ids: ["b", "a"] });
    fireEvent.click(screen.getByRole("button", { name: /delete email/i }));
    await waitFor(() => expect(screen.queryByText("jane@example.com")).toBeNull());
  });

  it("preview page shows the phone-in-notes warning", async () => {
    routes([], {
      "GET /api/admin/profile/preview": () =>
        jsonResponse({
          text: "x",
          chars: 1,
          approx_tokens: 1,
          warnings: ["A phone number appears in your notes. The bot will never show it."],
        }),
    });
    render(
      <MemoryRouter initialEntries={["/admin/profile/preview"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/phone number appears in your notes/i)).toBeInTheDocument();
  });
});
