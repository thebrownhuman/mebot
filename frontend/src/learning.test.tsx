import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const Q = (over: Record<string, unknown> = {}) => ({
  id: "q1",
  question: "Where do you live?",
  ask_count: 4,
  first_asked_at: "2026-10-14T09:00:00Z",
  last_asked_at: "2026-10-16T09:00:00Z",
  status: "open",
  answered_fact_id: null,
  ...over,
});

const F = (over: Record<string, unknown> = {}) => ({
  id: "f1",
  open_question_id: "q1",
  question: "Where do you live?",
  answer_raw: "Bangalore, open to remote",
  fact_text: "Shivansh lives in Bangalore and is open to remote work.",
  status: "pending",
  source: "admin",
  suggested_section: "learned",
  suggested_field: null,
  suggested_value: null,
  current_value: null,
  needs_review: false,
  approved_at: null,
  created_at: "2026-10-16T09:30:00Z",
  updated_at: "2026-10-16T09:30:00Z",
  ...over,
});

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () =>
      jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/admin/llm": () =>
      jsonResponse({ configured: true, status: "ok", last_test_ok: true, model: "m" }),
    "GET /api/admin/open-questions": () => jsonResponse({ items: [Q()], open_count: 1 }),
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

const body = (calls: { key: string; init?: RequestInit }[], key: string) => {
  const matching = calls.filter((x) => x.key === key);
  const c = matching[matching.length - 1];
  return c?.init?.body ? JSON.parse(String(c.init.body)) : undefined;
};

afterEach(() => vi.restoreAllMocks());

describe("sidebar", () => {
  it("links Open questions (with a count badge) and Memory", async () => {
    routes({ "GET /api/admin/open-questions": () => jsonResponse({ items: [Q()], open_count: 3 }) });
    renderAt("/admin/contacts");
    const nav = await screen.findByRole("navigation", { name: /admin/i });
    const link = await within(nav).findByRole("link", { name: /open questions/i });
    expect(link).toHaveAttribute("href", "/admin/open-questions");
    expect(await within(link).findByLabelText("3 open")).toHaveTextContent("3");
    expect(within(nav).getByRole("link", { name: /^memory$/i })).toHaveAttribute(
      "href",
      "/admin/memory",
    );
  });

  it("shows no badge when nothing is open", async () => {
    routes({ "GET /api/admin/open-questions": () => jsonResponse({ items: [], open_count: 0 }) });
    renderAt("/admin/contacts");
    const nav = await screen.findByRole("navigation", { name: /admin/i });
    await within(nav).findByRole("link", { name: /open questions/i });
    expect(screen.queryByLabelText(/\d+ open/)).not.toBeInTheDocument();
  });
});

describe("open questions page", () => {
  it("lists questions with their count", async () => {
    routes({
      "GET /api/admin/open-questions": () =>
        jsonResponse({
          items: [Q(), Q({ id: "q2", question: "Do you drive?", ask_count: 1 })],
          open_count: 2,
        }),
    });
    renderAt("/admin/open-questions");
    expect(await screen.findByRole("heading", { name: /^open questions$/i })).toBeInTheDocument();
    const cards = await screen.findAllByRole("article");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByText("Where do you live?")).toBeInTheDocument();
    expect(within(cards[0]).getByText(/asked 4×/)).toBeInTheDocument();
    expect(within(cards[1]).getByText(/asked 1×/)).toBeInTheDocument();
  });

  it("has loading, empty and error states", async () => {
    routes({ "GET /api/admin/open-questions": () => jsonResponse({ items: [], open_count: 0 }) });
    renderAt("/admin/open-questions");
    expect(await screen.findByText(/no open questions\. when a recruiter/i)).toBeInTheDocument();
    vi.restoreAllMocks();
    routes({
      "GET /api/admin/open-questions": () => errorResponse(500, "INTERNAL", "Server broke"),
    });
    renderAt("/admin/open-questions");
    expect((await screen.findAllByRole("alert")).some((a) => /server broke/i.test(a.textContent ?? ""))).toBe(true);
  });

  it("answer -> cleaned fact card -> approve removes the question", async () => {
    const { calls } = routes({
      "POST /api/admin/open-questions/q1/answer": () => jsonResponse(F(), 201),
      "POST /api/admin/learned-facts/f1/approve": () => jsonResponse(F({ status: "approved" })),
    });
    renderAt("/admin/open-questions");
    const card = await screen.findByRole("article", { name: /question: where do you live/i });
    fireEvent.change(within(card).getByLabelText(/your answer/i), {
      target: { value: "Bangalore, open to remote" },
    });
    fireEvent.click(within(card).getByRole("button", { name: /^answer$/i }));
    expect(
      await within(card).findByText("Shivansh lives in Bangalore and is open to remote work."),
    ).toBeInTheDocument();
    expect(body(calls, "POST /api/admin/open-questions/q1/answer")).toEqual({
      answer: "Bangalore, open to remote",
    });
    fireEvent.click(within(card).getByRole("button", { name: /^approve$/i }));
    await waitFor(() => expect(screen.queryByRole("article", { name: /question:/i })).toBeNull());
    expect(body(calls, "POST /api/admin/learned-facts/f1/approve")).toEqual({});
    expect(await screen.findByText(/no open questions/i)).toBeInTheDocument();
  });

  it("edit then save & approve sends the corrected text", async () => {
    const { calls } = routes({
      "POST /api/admin/open-questions/q1/answer": () => jsonResponse(F(), 201),
      "POST /api/admin/learned-facts/f1/approve": () => jsonResponse(F({ status: "approved" })),
    });
    renderAt("/admin/open-questions");
    const card = await screen.findByRole("article", { name: /question:/i });
    fireEvent.change(within(card).getByLabelText(/your answer/i), { target: { value: "Bangalore" } });
    fireEvent.click(within(card).getByRole("button", { name: /^answer$/i }));
    await within(card).findByRole("button", { name: /^edit$/i });
    fireEvent.click(within(card).getByRole("button", { name: /^edit$/i }));
    fireEvent.change(within(card).getByLabelText(/^fact$/i), {
      target: { value: "Shivansh is based in Bangalore." },
    });
    fireEvent.click(within(card).getByRole("button", { name: /save & approve/i }));
    await waitFor(() => expect(screen.queryByRole("article", { name: /question:/i })).toBeNull());
    expect(body(calls, "POST /api/admin/learned-facts/f1/approve")).toEqual({
      fact_text: "Shivansh is based in Bangalore.",
    });
  });

  it("identity suggestion: shows current vs new and asks Replace / Keep both on 409", async () => {
    const fact = F({
      suggested_section: "identity",
      suggested_field: "location",
      suggested_value: "Bangalore",
      current_value: "Pune",
    });
    let first = true;
    const { calls } = routes({
      "POST /api/admin/open-questions/q1/answer": () => jsonResponse(fact, 201),
      "POST /api/admin/learned-facts/f1/approve": (init) => {
        if (first) {
          first = false;
          return errorResponse(409, "IDENTITY_FIELD_SET", "Location is already set.", [
            { field: "location", current: "Pune", new: "Bangalore" },
          ]);
        }
        expect(JSON.parse(String(init?.body))).toEqual({ mode: "replace" });
        return jsonResponse({ ...fact, status: "approved" });
      },
    });
    renderAt("/admin/open-questions");
    const card = await screen.findByRole("article", { name: /question:/i });
    fireEvent.change(within(card).getByLabelText(/your answer/i), { target: { value: "Bangalore" } });
    fireEvent.click(within(card).getByRole("button", { name: /^answer$/i }));
    expect(await within(card).findByText(/also fills your profile/i)).toBeInTheDocument();
    expect(within(card).getByText(/currently “Pune”/)).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: /^approve$/i }));
    const alert = await within(card).findByRole("alert");
    expect(alert).toHaveTextContent(/location is already “Pune”/i);
    expect(alert).toHaveTextContent(/replace it with “Bangalore”/i);
    expect(within(card).getByRole("button", { name: /keep both/i })).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: /^replace$/i }));
    await waitFor(() => expect(screen.queryByRole("article", { name: /question:/i })).toBeNull());
    expect(calls.filter((c) => c.key === "POST /api/admin/learned-facts/f1/approve")).toHaveLength(2);
  });

  it("reject returns to the answer box", async () => {
    routes({
      "POST /api/admin/open-questions/q1/answer": () => jsonResponse(F(), 201),
      "POST /api/admin/learned-facts/f1/reject": () => jsonResponse(F({ status: "rejected" })),
    });
    renderAt("/admin/open-questions");
    const card = await screen.findByRole("article", { name: /question:/i });
    fireEvent.change(within(card).getByLabelText(/your answer/i), { target: { value: "Pune" } });
    fireEvent.click(within(card).getByRole("button", { name: /^answer$/i }));
    fireEvent.click(await within(card).findByRole("button", { name: /^reject$/i }));
    expect(await within(card).findByLabelText(/your answer/i)).toBeInTheDocument();
    expect(screen.getByRole("article", { name: /question:/i })).toBeInTheDocument();
  });

  it("shows the server's message when the answer is personal", async () => {
    routes({
      "POST /api/admin/open-questions/q1/answer": () =>
        errorResponse(422, "PERSONAL_ANSWER", "That answer is about a personal topic."),
    });
    renderAt("/admin/open-questions");
    const card = await screen.findByRole("article", { name: /question:/i });
    fireEvent.change(within(card).getByLabelText(/your answer/i), { target: { value: "x" } });
    fireEvent.click(within(card).getByRole("button", { name: /^answer$/i }));
    expect(await within(card).findByRole("alert")).toHaveTextContent(/personal topic/i);
    expect(within(card).getByLabelText(/your answer/i)).toHaveValue("x");
  });

  it("answer button is disabled until there is text", async () => {
    routes();
    renderAt("/admin/open-questions");
    const card = await screen.findByRole("article", { name: /question:/i });
    expect(within(card).getByRole("button", { name: /^answer$/i })).toBeDisabled();
  });

  it("dismiss removes the question", async () => {
    const { calls } = routes({
      "POST /api/admin/open-questions/q1/dismiss": () => jsonResponse(Q({ status: "dismissed" })),
    });
    renderAt("/admin/open-questions");
    const card = await screen.findByRole("article", { name: /question:/i });
    fireEvent.click(within(card).getByRole("button", { name: /dismiss/i }));
    await waitFor(() => expect(screen.queryByRole("article", { name: /question:/i })).toBeNull());
    expect(calls.some((c) => c.key === "POST /api/admin/open-questions/q1/dismiss")).toBe(true);
  });

  it("never answer this asks for confirmation first", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const { calls } = routes({
      "POST /api/admin/open-questions/q1/never": () => jsonResponse(Q({ status: "never" })),
    });
    renderAt("/admin/open-questions");
    const card = await screen.findByRole("article", { name: /question:/i });
    fireEvent.click(within(card).getByRole("button", { name: /never answer this/i }));
    expect(calls.some((c) => c.key.endsWith("/never"))).toBe(false);
    fireEvent.click(within(card).getByRole("button", { name: /never answer this/i }));
    await waitFor(() => expect(screen.queryByRole("article", { name: /question:/i })).toBeNull());
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(calls.some((c) => c.key === "POST /api/admin/open-questions/q1/never")).toBe(true);
  });
});

describe("memory page", () => {
  const list = (items: unknown[], active = 1) => ({
    "GET /api/admin/learned-facts": () =>
      jsonResponse({ items, active_count: active, max_active: 200 }),
  });

  it("groups pending, approved and rejected facts", async () => {
    routes(
      list([
        F({ id: "p", fact_text: "Pending fact." }),
        F({ id: "a", status: "approved", fact_text: "Approved fact." }),
        F({ id: "r", status: "rejected", fact_text: "Rejected fact." }),
      ]),
    );
    renderAt("/admin/memory");
    expect(await screen.findByRole("heading", { name: /^memory$/i })).toBeInTheDocument();
    const pending = await screen.findByRole("region", { name: /waiting for your approval/i });
    expect(within(pending).getByText("Pending fact.")).toBeInTheDocument();
    const approved = screen.getByRole("region", { name: /^approved$/i });
    expect(within(approved).getByText("Approved fact.")).toBeInTheDocument();
    expect(screen.getByText(/rejected \(1\)/i)).toBeInTheDocument();
  });

  it("has empty and error states", async () => {
    routes(list([], 0));
    renderAt("/admin/memory");
    expect(await screen.findByText(/nothing waiting/i)).toBeInTheDocument();
    expect(screen.getByText(/hasn.t learned anything yet/i)).toBeInTheDocument();
    vi.restoreAllMocks();
    routes({ "GET /api/admin/learned-facts": () => errorResponse(500, "INTERNAL", "Memory broke") });
    renderAt("/admin/memory");
    expect(
      (await screen.findAllByRole("alert")).some((a) => /memory broke/i.test(a.textContent ?? "")),
    ).toBe(true);
  });

  it("adds a fact (cleaned by the AI) into the pending list", async () => {
    const { calls } = routes({
      ...list([], 0),
      "POST /api/admin/learned-facts": () =>
        jsonResponse(F({ id: "n1", fact_text: "Shivansh speaks Hindi." }), 201),
    });
    renderAt("/admin/memory");
    fireEvent.change(await screen.findByLabelText(/teach the bot something/i), {
      target: { value: "Hindi" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add fact/i }));
    expect(await screen.findByText("Shivansh speaks Hindi.")).toBeInTheDocument();
    expect(body(calls, "POST /api/admin/learned-facts")).toEqual({ text: "Hindi" });
    expect(screen.getByLabelText(/teach the bot something/i)).toHaveValue("");
  });

  it("approving moves a fact to Approved", async () => {
    routes({
      ...list([F({ id: "p", fact_text: "Pending fact." })], 0),
      "POST /api/admin/learned-facts/p/approve": () =>
        jsonResponse(F({ id: "p", status: "approved", fact_text: "Pending fact." })),
    });
    renderAt("/admin/memory");
    const pending = await screen.findByRole("region", { name: /waiting for your approval/i });
    fireEvent.click(within(pending).getByRole("button", { name: /^approve$/i }));
    const approved = screen.getByRole("region", { name: /^approved$/i });
    expect(await within(approved).findByText("Pending fact.")).toBeInTheDocument();
    expect(within(pending).queryByText("Pending fact.")).not.toBeInTheDocument();
  });

  it("edits and deletes an approved fact", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { calls } = routes({
      ...list([F({ id: "a", status: "approved", fact_text: "Old wording." })]),
      "PUT /api/admin/learned-facts/a": () =>
        jsonResponse(F({ id: "a", status: "approved", fact_text: "New wording." })),
      "DELETE /api/admin/learned-facts/a": () => new Response(null, { status: 204 }),
    });
    renderAt("/admin/memory");
    const card = await screen.findByRole("article", { name: /fact: old wording/i });
    fireEvent.click(within(card).getByRole("button", { name: /^edit$/i }));
    fireEvent.change(within(card).getByLabelText(/^fact$/i), { target: { value: "New wording." } });
    fireEvent.click(within(card).getByRole("button", { name: /^save$/i }));
    expect(await screen.findByText("New wording.", { selector: "p" })).toBeInTheDocument();
    expect(body(calls, "PUT /api/admin/learned-facts/a")).toEqual({ fact_text: "New wording." });
    fireEvent.click(screen.getByRole("button", { name: /^delete$/i }));
    await waitFor(() => expect(screen.queryByText("New wording.")).not.toBeInTheDocument());
    expect(calls.some((c) => c.key === "DELETE /api/admin/learned-facts/a")).toBe(true);
  });

  it("does not delete when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const { calls } = routes(list([F({ id: "a", status: "approved", fact_text: "Keep me." })]));
    renderAt("/admin/memory");
    fireEvent.click(await screen.findByRole("button", { name: /^delete$/i }));
    expect(screen.getByText("Keep me.")).toBeInTheDocument();
    expect(calls.some((c) => c.key.startsWith("DELETE"))).toBe(false);
  });

  it("warns that only the newest 200 learned facts are used", async () => {
    const many = Array.from({ length: 200 }, (_, i) =>
      F({ id: `a${i}`, status: "approved", fact_text: `Fact ${i}.` }),
    );
    routes(list(many, 200));
    renderAt("/admin/memory");
    expect(await screen.findByText(/uses only the newest 200 learned facts/i)).toBeInTheDocument();
  });

  it("flags facts the AI could not verify", async () => {
    routes(list([F({ needs_review: true, fact_text: "Shivansh: Bangalore" })], 0));
    renderAt("/admin/memory");
    expect(await screen.findByText(/couldn.t rewrite this safely/i)).toBeInTheDocument();
  });
});

describe("identity persona", () => {
  const IDENT = {
    full_name: "Shivansh Mishra",
    pronouns: "he/him",
    assistant_greeting: null,
    headline: "",
    location: "",
    open_to: "",
    summary: "",
    count_internships: false,
    count_freelance: true,
  };

  it("lets the owner choose pronouns and previews the greeting", async () => {
    const { calls } = routes({
      "GET /api/admin/profile/identity": () => jsonResponse(IDENT),
      "GET /api/admin/profile/links": () => jsonResponse({ items: [] }),
      "PUT /api/admin/profile/identity": (init) => jsonResponse(JSON.parse(String(init?.body))),
    });
    renderAt("/admin/profile/identity");
    const select = await screen.findByLabelText(/^pronouns/i);
    expect(select).toHaveValue("he/him");
    expect(screen.getByTestId("greeting-preview")).toHaveTextContent(
      "Hi! I'm Shivansh's assistant. Ask me anything about his work, experience or projects.",
    );
    fireEvent.change(select, { target: { value: "they/them" } });
    expect(screen.getByTestId("greeting-preview")).toHaveTextContent(/about their work/);
    fireEvent.change(screen.getByLabelText(/assistant greeting/i), {
      target: { value: "Hello from {first_name}'s bot. {pronoun_subj} codes." },
    });
    expect(screen.getByTestId("greeting-preview")).toHaveTextContent(
      "Hello from Shivansh's bot. they codes.",
    );
    fireEvent.click(screen.getByRole("button", { name: /save identity/i }));
    await waitFor(() => expect(body(calls, "PUT /api/admin/profile/identity")).toBeTruthy());
    expect(body(calls, "PUT /api/admin/profile/identity")).toMatchObject({
      pronouns: "they/them",
      assistant_greeting: "Hello from {first_name}'s bot. {pronoun_subj} codes.",
    });
  });
});

describe("preview", () => {
  it("shows server warnings about the learned facts cap", async () => {
    routes({
      "GET /api/admin/profile/preview": () =>
        jsonResponse({
          text: "=== LEARNED FACTS ===",
          chars: 20,
          approx_tokens: 5,
          learned_facts: 200,
          warnings: ["Only the newest 200 learned facts are used."],
        }),
    });
    renderAt("/admin/profile/preview");
    expect(await screen.findByText(/only the newest 200 learned facts are used/i)).toBeInTheDocument();
  });
});

describe("recruiter greeting", () => {
  const CONFIG = {
    turnstile_site_key: null,
    max_message_chars: 1000,
    paused: false,
    owner_name: "Shivansh Mishra",
    assistant_greeting:
      "Hi! I'm Shivansh's assistant. Ask me anything about his work, experience or projects.",
  };

  async function enter(config: Record<string, unknown>) {
    mockApi({
      "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
      "GET /api/health": () => jsonResponse({ ready: true, model: "m" }),
      "GET /api/public/config": () => jsonResponse(config),
      "POST /api/session": () => jsonResponse({ session_id: "s1" }),
      "GET /api/session/s1/updates": () => jsonResponse({ messages: [], unanswered: false }),
    });
    renderAt("/");
    fireEvent.change(await screen.findByLabelText(/your name/i), { target: { value: "Jo" } });
    fireEvent.keyDown(screen.getByLabelText(/your name/i), { key: "Enter" });
    const input = await screen.findByLabelText(/your question/i);
    await waitFor(() => expect(input).not.toBeDisabled());
  }

  it("shows the greeting as the first bot bubble, without any chat request", async () => {
    await enter(CONFIG);
    expect(
      await screen.findByText(/Hi! I'm Shivansh's assistant\. Ask me anything about his work/),
    ).toBeInTheDocument();
    const fetchMock = globalThis.fetch as unknown as { mock: { calls: unknown[][] } };
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/api/chat"))).toBe(false);
  });

  it("shows nothing extra when the server sends no greeting", async () => {
    await enter({ ...CONFIG, assistant_greeting: undefined });
    expect(screen.queryByText(/assistant\. Ask me anything/)).not.toBeInTheDocument();
  });
});
