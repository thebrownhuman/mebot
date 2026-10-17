import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { formatMoney, type BillingView } from "./lib/api";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));
vi.mock("./components/Turnstile", () => ({
  default: ({ onToken }: { onToken: (t: string) => void }) => (
    <button type="button" onClick={() => onToken("tok")}>
      bot check
    </button>
  ),
}));

const VIEW: BillingView = {
  status: "trialing",
  serving: true,
  plan_code: "trial",
  plan_name: "Free trial",
  provider: null,
  currency: null,
  current_period_end: null,
  cancel_at_period_end: false,
  grace_until: null,
  comp_until: null,
  trial: { ends_at: "2026-10-30T00:00:00Z", days_left: 13, messages_used: 40, messages_total: 200 },
  usage: { since: "2026-10-16T00:00:00Z", messages: 40, tokens: 12000 },
  offers: [
    { code: "monthly", name: "Monthly", prices: { INR: { amount_minor: 49900 }, USD: { amount_minor: 900 } } },
  ],
  providers: ["razorpay", "stripe"],
  can_checkout: true,
  can_manage: false,
  can_cancel: false,
  platform_gstin: null,
  owner_gstin: null,
};

const CFG = {
  signup_mode: "open",
  turnstile_site_key: "site",
  hosted_domain: null,
  billing_enabled: true,
  terms_version: "2026-10",
  trial_days: 14,
  trial_messages: 200,
};

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false, mode: "hosted" }),
    "GET /api/auth/me": () => jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/admin/llm": () => jsonResponse({ configured: true, last_test_ok: true }),
    "GET /api/admin/open-questions": () => jsonResponse({ items: [], open_count: 0 }),
    "GET /api/hosted/config": () => jsonResponse(CFG),
    "GET /api/hosted/account": () =>
      jsonResponse({ live: true, setup_done: true, email_verified: true, billing_enabled: true, serving: true }),
    "GET /api/hosted/billing": () => jsonResponse(VIEW),
    "GET /api/hosted/billing/invoices": () => jsonResponse({ items: [] }),
    ...extra,
  });
}

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );

afterEach(() => vi.restoreAllMocks());

describe("billing page", () => {
  it("shows trial, usage, offers and an empty invoice list; nav has Billing", async () => {
    routes();
    renderAt("/admin/billing");
    await screen.findByRole("heading", { name: /your plan/i });
    expect(screen.getByText("Free trial")).toBeTruthy();
    expect(screen.getByText(/40 of 200 used/)).toBeTruthy();
    expect(screen.getByText(/13 days left/)).toBeTruthy();
    expect(await screen.findByText(/no invoices yet/i)).toBeTruthy();
    expect(screen.getByText(formatMoney(49900, "INR") + " / month")).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "admin" });
    await waitFor(() => expect(within(nav).getByRole("link", { name: "Billing" })).toBeTruthy());
  });

  it("starts checkout in the chosen currency and goes to the provider page", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, search: "" });
    const { calls } = routes({
      "POST /api/hosted/billing/checkout": () => jsonResponse({ url: "https://checkout.stripe.com/x" }),
    });
    renderAt("/admin/billing");
    fireEvent.click(await screen.findByLabelText("USD"));
    fireEvent.click(screen.getByRole("button", { name: /subscribe to monthly/i }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://checkout.stripe.com/x"));
    const sent = JSON.parse(String(calls.find((c) => c.key === "POST /api/hosted/billing/checkout")?.init?.body));
    expect(sent).toEqual({ plan_code: "monthly", currency: "USD" });
    vi.unstubAllGlobals();
  });

  it("shows a checkout error", async () => {
    routes({
      "POST /api/hosted/billing/checkout": () =>
        errorResponse(502, "BILLING_PROVIDER_ERROR", "The payment provider didn't respond. Try again."),
    });
    renderAt("/admin/billing");
    fireEvent.click(await screen.findByRole("button", { name: /subscribe to monthly/i }));
    expect(await screen.findByText(/didn't respond/)).toBeTruthy();
  });

  it("past due: grace banner; cancel needs confirmation", async () => {
    const active: BillingView = {
      ...VIEW,
      status: "past_due",
      plan_code: "monthly",
      plan_name: "Monthly",
      provider: "razorpay",
      currency: "INR",
      grace_until: "2026-10-20T00:00:00Z",
      current_period_end: "2026-11-01T00:00:00Z",
      trial: null,
      can_checkout: false,
      can_manage: true,
      can_cancel: true,
    };
    const { calls } = routes({
      "GET /api/hosted/billing": () => jsonResponse(active),
      "POST /api/hosted/billing/cancel": () =>
        jsonResponse({ ...active, status: "cancelled", cancel_at_period_end: true, can_cancel: false }),
    });
    renderAt("/admin/billing");
    expect(await screen.findByText(/last payment failed/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /update payment method/i })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /cancel subscription/i }));
    expect(calls.some((c) => c.key === "POST /api/hosted/billing/cancel")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /yes, cancel/i }));
    expect(await screen.findByText(/stays online until/i)).toBeTruthy();
    expect(JSON.parse(String(calls.find((c) => c.key === "POST /api/hosted/billing/cancel")?.init?.body))).toEqual({
      confirm: true,
    });
  });

  it("lists invoices with links", async () => {
    routes({
      "GET /api/hosted/billing/invoices": () =>
        jsonResponse({
          items: [
            {
              id: "i1", amount_minor: 900, currency: "USD", status: "paid",
              period_start: "2026-10-01T00:00:00Z", period_end: null, created_at: null,
              hosted_url: "https://inv/1", pdf_url: "https://pdf/1",
            },
          ],
        }),
    });
    renderAt("/admin/billing");
    expect((await screen.findByRole("link", { name: "PDF" })).getAttribute("href")).toBe("https://pdf/1");
    expect(screen.getByText(formatMoney(900, "USD"))).toBeTruthy();
  });

  it("load error offers a retry; billing off says so", async () => {
    routes({ "GET /api/hosted/billing": () => errorResponse(500, "INTERNAL", "boom") });
    renderAt("/admin/billing");
    expect(await screen.findByRole("button", { name: /try again/i })).toBeTruthy();
    vi.restoreAllMocks();
    routes({ "GET /api/hosted/billing": () => errorResponse(404, "NOT_FOUND", "Not Found") });
    renderAt("/admin/billing");
    expect(await screen.findByText(/aren't enabled on this server/i)).toBeTruthy();
  });

  it("no Billing nav item when paid plans are off", async () => {
    routes({ "GET /api/hosted/config": () => jsonResponse({ ...CFG, billing_enabled: false }) });
    renderAt("/admin/account");
    const nav = await screen.findByRole("navigation", { name: "admin" });
    await waitFor(() => expect(within(nav).getByRole("link", { name: "Account" })).toBeTruthy());
    expect(within(nav).queryByRole("link", { name: "Billing" })).toBeNull();
  });
});

describe("signup terms", () => {
  it("requires accepting the terms when paid plans are on", async () => {
    const { calls } = routes({
      "POST /api/hosted/signup": () => jsonResponse({ status: "check_your_email" }, 202),
    });
    renderAt("/signup");
    await screen.findByRole("heading", { name: /create your assistant/i });
    fireEvent.change(screen.getByLabelText(/your name/i), { target: { value: "Alice Dev" } });
    fireEvent.change(screen.getByLabelText(/e-mail/i), { target: { value: "a@example.com" } });
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "longenough1" } });
    fireEvent.click(screen.getByRole("button", { name: /bot check/i }));
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByText(/please accept the terms/i)).toBeTruthy();
    expect(calls.some((c) => c.key === "POST /api/hosted/signup")).toBe(false);
    expect(screen.getByText(/free 14-day trial/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    await screen.findByRole("heading", { name: /check your e-mail/i });
    const body = JSON.parse(String(calls.find((c) => c.key === "POST /api/hosted/signup")?.init?.body));
    expect(body.accept_terms).toBe(true);
  });
});
