import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const CONFIG = {
  turnstile_site_key: null,
  max_message_chars: 1000,
  paused: false,
  owner_name: "Jane Doe",
};

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/health": () => jsonResponse({ ready: true, model: "m" }),
    "GET /api/public/config": () => jsonResponse(CONFIG),
    "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    "GET /api/session/s1/updates": () => jsonResponse({ messages: [], unanswered: false }),
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
}

async function openModal() {
  fireEvent.click(await screen.findByRole("button", { name: /leave my contact/i }));
  return screen.getByRole("dialog", { name: /leave your contact/i });
}

describe("recruiter contact modal", () => {
  it("shows the consent line with the owner's name and a hidden honeypot", async () => {
    routes();
    await enter();
    const dialog = await openModal();
    expect(within(dialog).getByText("Your details are shared only with Jane Doe.")).toBeInTheDocument();
    const trap = dialog.querySelector('input[name="website"]') as HTMLInputElement;
    expect(trap).not.toBeNull();
    expect(trap.tabIndex).toBe(-1);
    expect(trap.closest("[aria-hidden='true']")).not.toBeNull();
    expect(within(dialog).getByLabelText(/^name/i)).toHaveFocus();
  });

  it("requires name and a valid email before sending", async () => {
    const api = routes();
    await enter();
    const dialog = await openModal();
    fireEvent.change(within(dialog).getByLabelText(/^email/i), { target: { value: "nope" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /send/i }));
    expect(within(dialog).getByText(/enter your name/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/valid email/i)).toBeInTheDocument();
    expect(api.calls.some((c) => c.key === "POST /api/contact")).toBe(false);
  });

  it("sends the details with the session id and thanks the recruiter", async () => {
    const api = routes({ "POST /api/contact": () => jsonResponse({ id: "c1" }, 201) });
    await enter();
    const dialog = await openModal();
    fireEvent.change(within(dialog).getByLabelText(/^name/i), { target: { value: "Priya" } });
    fireEvent.change(within(dialog).getByLabelText(/^email/i), { target: { value: "p@acme.com" } });
    fireEvent.change(within(dialog).getByLabelText(/company/i), { target: { value: "Acme" } });
    fireEvent.change(within(dialog).getByLabelText(/role/i), { target: { value: "Recruiter" } });
    fireEvent.change(within(dialog).getByLabelText(/note/i), { target: { value: "Call me" } });
    expect(within(dialog).getByLabelText(/note/i)).toHaveAttribute("maxLength", "1000");
    fireEvent.click(within(dialog).getByRole("button", { name: /send/i }));
    expect(await within(dialog).findByText(/thanks/i)).toBeInTheDocument();
    const call = api.calls.find((c) => c.key === "POST /api/contact")!;
    expect(JSON.parse(String(call.init!.body))).toEqual({
      session_id: "s1",
      name: "Priya",
      email: "p@acme.com",
      company: "Acme",
      role: "Recruiter",
      note: "Call me",
    });
  });

  it("shows the backend error (rate limit)", async () => {
    routes({
      "POST /api/contact": () =>
        errorResponse(429, "RATE_LIMITED", "You've already left your details. Please try again later."),
    });
    await enter();
    const dialog = await openModal();
    fireEvent.change(within(dialog).getByLabelText(/^name/i), { target: { value: "Priya" } });
    fireEvent.change(within(dialog).getByLabelText(/^email/i), { target: { value: "p@acme.com" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /send/i }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/already left your details/i);
  });

  it("closes with Escape and the close button", async () => {
    routes();
    await enter();
    await openModal();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    await openModal();
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
