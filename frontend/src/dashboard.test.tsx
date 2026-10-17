import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Overview } from "./lib/api";
import { describeDelta, niceMax, shortDate } from "./components/admin/dash/format";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

function Where() {
  const l = useLocation();
  return <div data-testid="where">{l.pathname + l.search}</div>;
}


function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <Where />
    </MemoryRouter>,
  );
}

const kpi = (value: number | null, previous: number | null = null) => ({ value, previous });

function overview(over: Partial<Overview> = {}): Overview {
  return {
    range: { key: "7d", from: "2026-10-11", to: "2026-10-17", timezone: "Asia/Kolkata" },
    kpis: {
      chats: kpi(14, 9),
      visitor_messages: kpi(60, 70),
      avg_messages_per_chat: kpi(4.3, 4.3),
      unanswered_rate: kpi(0.12, 0.2),
      open_questions: kpi(3),
      contacts: kpi(2, 0),
      owner_replies: kpi(1, 1),
      tokens: { value: 1200, previous: 800, estimated: true },
    },
    series: [
      { date: "2026-10-11", chats: 2, visitor_messages: 9, unanswered: 0 },
      { date: "2026-10-12", chats: 5, visitor_messages: 20, unanswered: 2 },
      { date: "2026-10-13", chats: 0, visitor_messages: 0, unanswered: 0 },
    ],
    top_questions: [
      { question: "What is his tech stack?", count: 6 },
      { question: "Is he open to remote work?", count: 2 },
    ],
    sources: [
      { origin: "https://shivansh.dev", chats: 10 },
      { origin: "direct", chats: 4 },
    ],
    status: {
      llm: { configured: true, ok: true, last_tested_at: null },
      telegram: { linked: false, dead: 0 },
      widget: { enabled: true, origins: 0, any_origin: false },
      paused: false,
      today: { messages: 31, cap: 500, tokens: 0, token_cap: null },
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
    "GET /api/admin/analytics/overview": () => jsonResponse(overview()),
    ...extra,
  });
}

describe("format helpers", () => {
  it("describes deltas in words, not colour", () => {
    expect(describeDelta(kpi(14, 9), "count", "7d")).toEqual({
      arrow: "▲",
      text: "5 more than the previous 7 days",
    });
    expect(describeDelta(kpi(1, 4), "count", "30d")?.text).toBe("3 fewer than the previous 30 days");
    expect(describeDelta(kpi(0.12, 0.2), "rate", "7d")?.text).toBe(
      "8 points lower than the previous 7 days",
    );
    expect(describeDelta(kpi(2, 2), "count", "7d")?.text).toContain("same as");
    expect(describeDelta(kpi(0, 0), "count", "7d")?.text).toContain("no change");
    expect(describeDelta(kpi(null, 2), "rate", "7d")).toBeNull();
    expect(describeDelta(kpi(3, null), "count", "7d")).toBeNull();
  });

  it("formats dates and axis maxima", () => {
    expect(shortDate("2026-10-11")).toBe("Oct 11");
    expect(niceMax(0)).toBe(4);
    expect(niceMax(7)).toBe(10);
    expect(niceMax(130)).toBe(200);
  });
});

describe("dashboard", () => {
  it("shows KPI tiles with text deltas", async () => {
    routes();
    renderAt("/admin");
    const tiles = await screen.findByRole("list", { name: /key numbers/i });
    const chats = within(tiles).getByText("Chats").closest("li")!;
    expect(chats).toHaveTextContent("14");
    expect(chats).toHaveTextContent("5 more than the previous 7 days");
    const unanswered = within(tiles).getByText("Unanswered replies").closest("li")!;
    expect(unanswered).toHaveTextContent("12%");
    expect(unanswered).toHaveTextContent("8 points lower");
    expect(within(tiles).getByText("Tokens used").closest("li")).toHaveTextContent("≈");
    expect(within(tiles).getByText("Open questions").closest("li")).toHaveTextContent("right now");
    expect(screen.getByText(/asia\/kolkata/i)).toBeInTheDocument();
  });

  it("renders a titled SVG chart and a table fallback", async () => {
    routes();
    renderAt("/admin");
    const chart = await screen.findByRole("img", { name: /daily chats and unanswered/i });
    expect(chart.querySelector("desc")?.textContent).toMatch(/7 chats and 2 unanswered/);
    expect(chart.querySelectorAll("rect").length).toBeGreaterThan(2);
    fireEvent.click(screen.getByRole("button", { name: /show as table/i }));
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByRole("rowheader", { name: "Oct 12" }).closest("tr")).toHaveTextContent(
      /Oct 125202/,
    );
    expect(screen.queryByRole("img", { name: /daily chats/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /show as chart/i }));
    expect(screen.getByRole("img", { name: /daily chats/i })).toBeInTheDocument();
  });

  it("switches range and refetches", async () => {
    const { calls } = routes({
      "GET /api/admin/analytics/overview": () => jsonResponse(overview()),
    });
    renderAt("/admin");
    await screen.findByRole("list", { name: /key numbers/i });
    expect(screen.getByRole("button", { name: "7d" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "30d" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "30d" })).toHaveAttribute("aria-pressed", "true"));
    await waitFor(() =>
      expect(calls.filter((c) => c.key === "GET /api/admin/analytics/overview")).toHaveLength(2),
    );
  });

  it("top questions link to conversations filtered by q and range", async () => {
    routes();
    renderAt("/admin");
    const link = await screen.findByRole("link", { name: "What is his tech stack?" });
    expect(link).toHaveAttribute("href", "/admin/conversations?q=What+is+his+tech+stack%3F&range=7d");
  });

  it("lists sources with share bars and the Direct page label", async () => {
    routes();
    renderAt("/admin");
    const link = await screen.findByRole("link", { name: "shivansh.dev" });
    expect(link.closest("li")).toHaveTextContent("10 chats · 71%");
    expect(screen.getByRole("link", { name: "Direct page" }).closest("li")).toHaveTextContent("29%");
  });

  it("consolidates status with links to fix", async () => {
    routes();
    renderAt("/admin");
    const card = (await screen.findByRole("heading", { name: /status/i })).closest("section")!;
    expect(within(card).getByText("Working")).toBeInTheDocument();
    expect(within(card).getByText(/not linked/i)).toBeInTheDocument();
    expect(within(card).getByText(/no site is allowed/i)).toBeInTheDocument();
    expect(within(card).getByText("31/500 messages")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /add your site/i })).toHaveAttribute(
      "href",
      "/admin/widget",
    );
  });

  it("stays quiet about Telegram and the widget when they are set up", async () => {
    const o = overview();
    o.status.telegram = { linked: true, dead: 0 };
    o.status.widget = { enabled: true, origins: 2, any_origin: false };
    routes({ "GET /api/admin/analytics/overview": () => jsonResponse(o) });
    renderAt("/admin");
    const card = (await screen.findByRole("heading", { name: /status/i })).closest("section")!;
    expect(within(card).getByText("Linked")).toBeInTheDocument();
    expect(within(card).getByText("On · 2 allowed sites")).toBeInTheDocument();
    expect(within(card).queryByRole("link")).toBeNull();
  });

  it("warns when paused or near the cap", async () => {
    const o = overview();
    o.status.paused = true;
    o.status.today = { messages: 450, cap: 500, tokens: 0, token_cap: null };
    o.status.llm = { configured: false, ok: false, last_tested_at: null };
    routes({ "GET /api/admin/analytics/overview": () => jsonResponse(o) });
    renderAt("/admin");
    const card = (await screen.findByRole("heading", { name: /status/i })).closest("section")!;
    expect(within(card).getByText(/paused — visitors can't chat/i)).toBeInTheDocument();
    expect(within(card).getByText(/90% of the cap/)).toBeInTheDocument();
    expect(within(card).getByText(/not configured — chat is off/i)).toBeInTheDocument();
  });

  it("keeps the open questions summary", async () => {
    routes({
      "GET /api/admin/open-questions": () =>
        jsonResponse({
          items: [{ id: "q1", question: "Where does he live?", ask_count: 3 }],
          open_count: 1,
        }),
    });
    renderAt("/admin");
    expect(await screen.findByText("Where does he live?")).toBeInTheDocument();
  });

  it("shows an empty state for a brand-new bot", async () => {
    const o = overview({
      kpis: {
        chats: kpi(0, 0),
        visitor_messages: kpi(0, 0),
        avg_messages_per_chat: kpi(null, null),
        unanswered_rate: kpi(null, null),
        open_questions: kpi(0),
        contacts: kpi(0, 0),
        owner_replies: kpi(0, 0),
        tokens: kpi(0, 0),
      },
      series: [{ date: "2026-10-17", chats: 0, visitor_messages: 0, unanswered: 0 }],
      top_questions: [],
      sources: [],
    });
    routes({ "GET /api/admin/analytics/overview": () => jsonResponse(o) });
    renderAt("/admin");
    expect(await screen.findByText(/no chats yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /embed the widget/i })).toHaveAttribute("href", "/admin/widget");
    expect(screen.queryByRole("list", { name: /key numbers/i })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /status/i })).toBeInTheDocument();
  });

  it("shows the error with a retry", async () => {
    let fail = true;
    routes({
      "GET /api/admin/analytics/overview": () =>
        fail ? errorResponse(500, "BOOM", "Database is locked") : jsonResponse(overview()),
    });
    renderAt("/admin");
    expect(await screen.findByRole("alert")).toHaveTextContent("Database is locked");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("list", { name: /key numbers/i })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("has a Try your bot link and no leftover chat or drawers", async () => {
    routes();
    renderAt("/admin");
    const link = await screen.findByRole("link", { name: /try your bot/i });
    expect(link).toHaveAttribute("href", "/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.queryByRole("button", { name: /new session/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/admin panel/i)).not.toBeInTheDocument();
  });
});
