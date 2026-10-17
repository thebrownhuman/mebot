import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const ACCOUNT = {
  timezone: "UTC",
  retention_days: 180,
  retention_choices: [30, 90, 180, 365],
};

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () =>
      jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/admin/llm": () => jsonResponse({ configured: true, last_test_ok: true }),
    "GET /api/admin/open-questions": () => jsonResponse({ items: [], open_count: 0 }),
    "GET /api/admin/account": () => jsonResponse(ACCOUNT),
    ...extra,
  });
}

function renderAccount() {
  return render(
    <MemoryRouter initialEntries={["/admin/account"]}>
      <App />
    </MemoryRouter>,
  );
}

const body = (calls: { key: string; init?: RequestInit }[], key: string) =>
  JSON.parse(calls.find((c) => c.key === key)!.init!.body as string);

describe("account: timezone", () => {
  it("saves a new timezone", async () => {
    const { calls } = routes({
      "PUT /api/admin/account": (init) =>
        jsonResponse({ ...ACCOUNT, timezone: JSON.parse(init!.body as string).timezone }),
    });
    renderAccount();
    const select = await screen.findByLabelText(/^your timezone$/i);
    expect(select).toHaveValue("UTC");
    const save = screen.getByRole("button", { name: /save timezone/i });
    expect(save).toBeDisabled();
    fireEvent.change(select, { target: { value: "Asia/Kolkata" } });
    fireEvent.click(save);
    expect(await screen.findByText(/timezone saved/i)).toBeInTheDocument();
    expect(body(calls, "PUT /api/admin/account")).toEqual({ timezone: "Asia/Kolkata" });
    expect(screen.getByRole("button", { name: /save timezone/i })).toBeDisabled();
  });

  it("suggests the browser's timezone", async () => {
    routes();
    vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({
      timeZone: "Europe/Berlin",
    } as Intl.ResolvedDateTimeFormatOptions);
    renderAccount();
    fireEvent.click(await screen.findByRole("button", { name: /use this browser's timezone \(europe\/berlin\)/i }));
    expect(screen.getByLabelText(/^your timezone$/i)).toHaveValue("Europe/Berlin");
  });
});

describe("account: retention", () => {
  it("previews how many conversations a shorter window would delete, then saves", async () => {
    const { calls } = routes({
      "GET /api/admin/account": () => jsonResponse({ ...ACCOUNT, will_delete: 7 }),
      "PUT /api/admin/account": () => jsonResponse({ ...ACCOUNT, retention_days: 30 }),
    });
    renderAccount();
    const select = await screen.findByLabelText(/delete conversations older than/i);
    expect(select).toHaveValue("180");
    expect(screen.getByRole("button", { name: /save retention/i })).toBeDisabled();
    fireEvent.change(select, { target: { value: "30" } });
    expect(await screen.findByText(/will delete 7 existing conversations/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /save retention/i }));
    expect(await screen.findByText(/retention saved/i)).toBeInTheDocument();
    expect(body(calls, "PUT /api/admin/account")).toEqual({ retention_days: 30 });
    expect(screen.queryByText(/will delete/i)).not.toBeInTheDocument();
  });

  it("says when nothing would be deleted", async () => {
    routes({ "GET /api/admin/account": () => jsonResponse({ ...ACCOUNT, will_delete: 0 }) });
    renderAccount();
    fireEvent.change(await screen.findByLabelText(/delete conversations older than/i), {
      target: { value: "365" },
    });
    expect(await screen.findByText(/nothing existing is older/i)).toBeInTheDocument();
  });

  it("can keep conversations forever (sends null)", async () => {
    const { calls } = routes({
      "PUT /api/admin/account": () => jsonResponse({ ...ACCOUNT, retention_days: null }),
    });
    renderAccount();
    fireEvent.change(await screen.findByLabelText(/delete conversations older than/i), {
      target: { value: "forever" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save retention/i }));
    await screen.findByText(/retention saved/i);
    expect(body(calls, "PUT /api/admin/account")).toEqual({ retention_days: null });
    expect(screen.queryByText(/will delete/i)).not.toBeInTheDocument();
  });

  it("shows the backend error when saving fails", async () => {
    routes({
      "PUT /api/admin/account": () => errorResponse(422, "VALIDATION_ERROR", "choose 30, 90, 180, 365"),
    });
    renderAccount();
    fireEvent.change(await screen.findByLabelText(/delete conversations older than/i), {
      target: { value: "90" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save retention/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("choose 30, 90, 180, 365");
  });

  it("shows a load error instead of the form", async () => {
    routes({ "GET /api/admin/account": () => errorResponse(500, "BOOM", "Database is locked") });
    renderAccount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Database is locked");
    expect(screen.queryByLabelText(/^your timezone$/i)).not.toBeInTheDocument();
  });
});

describe("account: delete all conversations", () => {
  it("needs the exact word DELETE", async () => {
    const { calls } = routes({
      "POST /api/admin/account/delete-conversations": () => jsonResponse({ deleted_sessions: 52 }),
    });
    renderAccount();
    const input = await screen.findByLabelText(/type delete to confirm/i);
    const button = screen.getByRole("button", { name: /delete all conversations/i });
    expect(button).toBeDisabled();
    for (const wrong of ["delete", "DELET", "DELETE "]) {
      fireEvent.change(input, { target: { value: wrong } });
      expect(button).toBeDisabled();
    }
    fireEvent.change(input, { target: { value: "DELETE" } });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(await screen.findByText(/deleted 52 conversations/i)).toBeInTheDocument();
    expect(body(calls, "POST /api/admin/account/delete-conversations")).toEqual({ confirm: "DELETE" });
    await waitFor(() => expect(input).toHaveValue(""));
  });

  it("links to exports of everything", async () => {
    routes();
    renderAccount();
    expect(await screen.findByRole("link", { name: /all conversations \(csv\)/i })).toHaveAttribute(
      "href",
      "/api/admin/conversations/export?format=csv",
    );
    expect(screen.getByRole("link", { name: "JSON" })).toHaveAttribute(
      "href",
      "/api/admin/conversations/export?format=json",
    );
  });

  it("shows the backend error", async () => {
    routes({
      "POST /api/admin/account/delete-conversations": () =>
        errorResponse(500, "BOOM", "Database is locked"),
    });
    renderAccount();
    fireEvent.change(await screen.findByLabelText(/type delete to confirm/i), {
      target: { value: "DELETE" },
    });
    fireEvent.click(screen.getByRole("button", { name: /delete all conversations/i }));
    expect(await screen.findByText("Database is locked")).toBeInTheDocument();
  });
});
