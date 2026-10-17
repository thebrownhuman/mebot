import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { formatMoney } from "./lib/api";
import { jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const TENANT = {
  id: "b1", slug: "alice", owner_email: "alice@example.com", email_verified: true,
  created_at: "2026-10-01T10:00:00Z", status: "active", status_reason: null, plan: "free",
  billing_status: "past_due", billing_plan: "monthly", setup_done: true, messages_7d: 7,
  messages_30d: 30, tokens_30d: 1200, last_active_at: null, deletion_requested_at: null,
};

const BILLING = {
  enabled: true,
  mrr: { INR: 49900, USD: 1800 },
  counts: { active: 3, past_due: 1 },
  past_due: [{ bot_id: "b1", slug: "alice", provider: "stripe", grace_until: "2026-10-20T00:00:00Z" }],
  plans: [
    { code: "trial", name: "Free trial", active: true, is_trial: true, prices: {}, limits: { daily_message_cap: 100 } },
    {
      code: "monthly", name: "Monthly", active: true, is_trial: false,
      prices: { USD: { amount_minor: 900, provider: "stripe", provider_plan_id: "price_1" } }, limits: {},
    },
  ],
};

function api(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false, mode: "hosted" }),
    "GET /api/platform/auth/me": () => jsonResponse({ email: "ops@example.com" }),
    "GET /api/platform/tenants": () => jsonResponse({ items: [TENANT] }),
    "GET /api/platform/billing": () => jsonResponse(BILLING),
    ...extra,
  });
}

const renderPlatform = () =>
  render(
    <MemoryRouter initialEntries={["/platform"]}>
      <App />
    </MemoryRouter>,
  );

afterEach(() => vi.restoreAllMocks());

describe("operator billing", () => {
  it("shows MRR, counts, past due and plans; reconcile now reports", async () => {
    const { calls } = api({
      "POST /api/platform/billing/reconcile": () => jsonResponse({ checked: 4, fixed: 1, errors: 0 }),
    });
    renderPlatform();
    fireEvent.click(await screen.findByRole("tab", { name: "Billing" }));
    expect(await screen.findByText(formatMoney(49900, "INR"))).toBeTruthy();
    expect(screen.getByText(formatMoney(1800, "USD"))).toBeTruthy();
    const due = screen.getByRole("heading", { name: "Past due" }).parentElement!;
    expect(within(due).getByText("/b/alice")).toBeTruthy();
    expect(screen.getByText(/daily_message_cap=100/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /reconcile now/i }));
    expect(await screen.findByText(/checked 4, fixed 1, errors 0/i)).toBeTruthy();
    expect(calls.filter((c) => c.key === "POST /api/platform/billing/reconcile")).toHaveLength(1);
  });

  it("tenant card shows billing status and comps with days + reason", async () => {
    const prompt = vi.spyOn(window, "prompt").mockReturnValueOnce("10").mockReturnValueOnce("beta tester");
    const { calls } = api({ "POST /api/platform/tenants/b1/comp": () => jsonResponse({ comp_until: "x" }) });
    renderPlatform();
    expect(await screen.findByText("past_due")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /comp days/i }));
    expect(await screen.findByText(/\+10 days/)).toBeTruthy();
    const sent = calls.find((c) => c.key === "POST /api/platform/tenants/b1/comp");
    expect(JSON.parse(String(sent?.init?.body))).toEqual({ days: 10, reason: "beta tester" });
    expect(prompt).toHaveBeenCalledTimes(2);
  });

  it("billing off: a plain note", async () => {
    api({ "GET /api/platform/billing": () => jsonResponse({ ...BILLING, enabled: false }) });
    renderPlatform();
    fireEvent.click(await screen.findByRole("tab", { name: "Billing" }));
    expect(await screen.findByText(/paid plans are off/i)).toBeTruthy();
  });
});
