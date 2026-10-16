import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { linkify, safeHref } from "./lib/linkify";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const CONFIG = {
  turnstile_site_key: null,
  max_message_chars: 1000,
  paused: false,
  owner_name: "Jane Doe",
};

const ITEMS = [
  { kind: "email", label: "Email", display: "jane@example.com", href: "mailto:jane@example.com" },
  { kind: "whatsapp", label: "WhatsApp", display: "@jane_wa", href: "https://wa.me/jane_wa" },
  { kind: "portfolio", label: "Portfolio", display: "jane.dev", href: "https://jane.dev" },
  { kind: "other", label: "Evil", display: "x", href: "javascript:alert(1)" },
];

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

const openPanel = async () => {
  fireEvent.click(await screen.findByRole("button", { name: /^contact$/i }));
  return screen.findByRole("dialog", { name: /get in touch with jane doe/i });
};

describe("recruiter Contact panel", () => {
  it("lists shared channels as safe new-tab links", async () => {
    routes({ "GET /api/public/contact-channels": () => jsonResponse({ items: ITEMS }) });
    await enter();
    const panel = await openPanel();
    const mail = await within(panel).findByRole("link", { name: /email: jane@example.com/i });
    expect(mail).toHaveAttribute("href", "mailto:jane@example.com");
    const wa = within(panel).getByRole("link", { name: /whatsapp: @jane_wa/i });
    expect(wa).toHaveAttribute("href", "https://wa.me/jane_wa");
    for (const a of [mail, wa, within(panel).getByRole("link", { name: /portfolio/i })]) {
      expect(a).toHaveAttribute("target", "_blank");
      expect(a).toHaveAttribute("rel", "noopener noreferrer");
    }
    // A non-http(s) href from the server is never made a link.
    expect(within(panel).queryByRole("link", { name: /evil/i })).toBeNull();
    expect(within(panel).getByText("x")).toBeInTheDocument();
  });

  it("shows a loading state, then an empty state with only the form", async () => {
    let release: (r: Response) => void = () => {};
    routes({
      "GET /api/public/contact-channels": () => new Promise<Response>((r) => (release = r)),
    });
    await enter();
    const panel = await openPanel();
    expect(within(panel).getByRole("status")).toBeInTheDocument();
    release(jsonResponse({ items: [] }));
    expect(await within(panel).findByText(/hasn’t shared direct contact options/i)).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /leave my contact/i })).toBeInTheDocument();
  });

  it("shows an error with retry", async () => {
    let n = 0;
    routes({
      "GET /api/public/contact-channels": () =>
        ++n === 1
          ? errorResponse(429, "RATE_LIMITED", "Too many requests. Please wait a moment.")
          : jsonResponse({ items: ITEMS.slice(0, 1) }),
    });
    await enter();
    const panel = await openPanel();
    expect(await within(panel).findByRole("alert")).toHaveTextContent(/too many requests/i);
    fireEvent.click(within(panel).getByRole("button", { name: /try again/i }));
    expect(await within(panel).findByRole("link", { name: /email/i })).toBeInTheDocument();
  });

  it("Leave my contact opens the form; Escape closes the panel", async () => {
    routes({ "GET /api/public/contact-channels": () => jsonResponse({ items: [] }) });
    await enter();
    const panel = await openPanel();
    fireEvent.keyDown(panel, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    const again = await openPanel();
    fireEvent.click(within(again).getByRole("button", { name: /leave my contact/i }));
    expect(screen.getByRole("dialog", { name: /leave your contact/i })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /get in touch/i })).toBeNull();
  });
});

describe("safe linkify", () => {
  it("links http(s) and e-mail only", () => {
    expect(safeHref("https://jane.dev/x?y=1")).toBe("https://jane.dev/x?y=1");
    expect(safeHref("jane@example.com")).toBe("mailto:jane@example.com");
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,x")).toBeNull();
    expect(safeHref("ftp://x.com")).toBeNull();
  });

  it("renders anchors with noopener, trims trailing punctuation, leaves other text alone", () => {
    render(
      <p data-testid="out">
        {linkify("Mail jane@example.com, or see https://jane.dev/work. javascript:alert(1) done")}
      </p>,
    );
    const links = within(screen.getByTestId("out")).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "mailto:jane@example.com",
      "https://jane.dev/work",
    ]);
    for (const a of links) {
      expect(a).toHaveAttribute("target", "_blank");
      expect(a).toHaveAttribute("rel", "noopener noreferrer");
    }
    expect(screen.getByTestId("out").textContent).toBe(
      "Mail jane@example.com, or see https://jane.dev/work. javascript:alert(1) done",
    );
  });

  it("makes URLs in a bot reply clickable in the chat", async () => {
    routes({
      "POST /api/chat": () =>
        new Response("Reach him at https://jane.dev and <script>x</script>", { status: 200 }),
    });
    await enter();
    const input = screen.getByLabelText(/your question/i);
    fireEvent.change(input, { target: { value: "contact?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    const a = await screen.findByRole("link", { name: "https://jane.dev" });
    expect(a).toHaveAttribute("rel", "noopener noreferrer");
    expect(document.querySelector("script")).toBeNull();
  });
});
