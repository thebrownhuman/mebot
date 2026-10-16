import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

const where = () => screen.getByTestId("where").textContent;

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <Where />
    </MemoryRouter>,
  );
}

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

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () =>
      jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/health": () => jsonResponse({ ready: true, model: "gpt-4o-mini" }),
    "POST /api/session": () => jsonResponse({ session_id: "s1" }),
    "GET /api/admin/llm": () => jsonResponse(LLM),
    "GET /api/admin/profile/projects": () => jsonResponse({ items: [] }),
    ...extra,
  });
}

const project = (id: string, name: string, sort_order: number) => ({
  id,
  name,
  sort_order,
  summary: `${name} summary`,
  tagline: null,
  tech: ["Go"],
  highlights: [],
  created_at: "2026-10-15T10:00:00Z",
  updated_at: "2026-10-15T10:00:00Z",
});

const type = (label: RegExp, value: string, root: HTMLElement = document.body) =>
  fireEvent.change(within(root).getByLabelText(label), { target: { value } });

describe("admin layout", () => {
  it("navigates with the sidebar", async () => {
    routes();
    renderAt("/admin");
    const nav = await screen.findByRole("navigation", { name: /admin/i });
    fireEvent.click(within(nav).getByRole("link", { name: /^projects$/i }));
    await waitFor(() => expect(where()).toBe("/admin/profile/projects"));
    expect(await screen.findByRole("heading", { name: /^projects$/i })).toBeInTheDocument();
    for (const name of [
      /dashboard/i,
      /identity/i,
      /experience/i,
      /education/i,
      /skills/i,
      /interests & hobbies/i,
      /faq/i,
      /avoid topics/i,
      /notes/i,
      /preview/i,
      /ai provider/i,
      /account/i,
    ]) {
      expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
    }
  });
});

describe("collection page", () => {
  it("shows a helpful empty state", async () => {
    routes();
    renderAt("/admin/profile/projects");
    expect(await screen.findByText(/add your first project/i)).toBeInTheDocument();
  });

  it("shows the backend error when loading fails", async () => {
    routes({
      "GET /api/admin/profile/projects": () => errorResponse(500, "BOOM", "Database is locked"),
    });
    renderAt("/admin/profile/projects");
    expect(await screen.findByText("Database is locked")).toBeInTheDocument();
  });

  it("adds an item", async () => {
    const { calls } = routes({
      "POST /api/admin/profile/projects": (init) =>
        jsonResponse({ ...project("p1", "mebot", 0), ...JSON.parse(init!.body as string) }, 201),
    });
    renderAt("/admin/profile/projects");
    fireEvent.click(await screen.findByRole("button", { name: /add project/i }));
    const dialog = await screen.findByRole("dialog");
    type(/^name/i, "mebot", dialog);
    type(/^summary/i, "Portfolio chatbot", dialog);
    type(/^backend/i, "FastAPI", dialog);
    const tags = within(dialog).getByLabelText(/^tech/i);
    fireEvent.change(tags, { target: { value: "Python" } });
    fireEvent.keyDown(tags, { key: "Enter" });
    fireEvent.click(within(dialog).getByRole("button", { name: /^save/i }));
    expect(await screen.findByText(/saved/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("mebot")).toBeInTheDocument();
    const body = JSON.parse(
      calls.find((c) => c.key === "POST /api/admin/profile/projects")!.init!.body as string,
    );
    expect(body).toMatchObject({
      name: "mebot",
      summary: "Portfolio chatbot",
      backend: "FastAPI",
      tech: ["Python"],
    });
  });

  it("edits, reorders and deletes", async () => {
    const { calls } = routes({
      "GET /api/admin/profile/projects": () =>
        jsonResponse({ items: [project("a", "Alpha", 0), project("b", "Beta", 1)] }),
      "PUT /api/admin/profile/projects/a": (init) =>
        jsonResponse({ ...project("a", "Alpha", 0), ...JSON.parse(init!.body as string) }),
      "PUT /api/admin/profile/projects/order": () => new Response(null, { status: 204 }),
      "DELETE /api/admin/profile/projects/b": () => new Response(null, { status: 204 }),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderAt("/admin/profile/projects");
    fireEvent.click(await screen.findByRole("button", { name: /edit alpha/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/^name/i)).toHaveValue("Alpha");
    type(/^name/i, "Alpha 2", dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: /^save/i }));
    expect(await screen.findByText("Alpha 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /move alpha 2 down/i }));
    await waitFor(() =>
      expect(calls.some((c) => c.key === "PUT /api/admin/profile/projects/order")).toBe(true),
    );
    const order = calls.find((c) => c.key === "PUT /api/admin/profile/projects/order")!;
    expect(JSON.parse(order.init!.body as string)).toEqual({ ids: ["b", "a"] });

    fireEvent.click(screen.getByRole("button", { name: /delete beta/i }));
    await waitFor(() => expect(screen.queryByText("Beta")).not.toBeInTheDocument());
    expect(window.confirm).toHaveBeenCalled();
    expect(calls.some((c) => c.key === "DELETE /api/admin/profile/projects/b")).toBe(true);
  });

  it("shows backend validation messages on the field", async () => {
    routes({
      "GET /api/admin/profile/experiences": () => jsonResponse({ items: [] }),
      "POST /api/admin/profile/experiences": () =>
        errorResponse(422, "VALIDATION_ERROR", "Invalid request", [
          { field: "end_month", message: "end month is before start month" },
        ]),
    });
    renderAt("/admin/profile/experience");
    fireEvent.click(await screen.findByRole("button", { name: /add experience/i }));
    const dialog = await screen.findByRole("dialog");
    type(/^company/i, "Acme", dialog);
    type(/^title/i, "Engineer", dialog);
    // Passes client checks; the server still has the last word.
    type(/^start month/i, "2021-01", dialog);
    type(/^end month/i, "2022-05", dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: /^save/i }));
    expect(await within(dialog).findByText("end month is before start month")).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/^end month/i)).toHaveAttribute("aria-invalid", "true");
  });

  it("'I currently work here' clears and disables the end month", async () => {
    const { calls } = routes({
      "GET /api/admin/profile/experiences": () => jsonResponse({ items: [] }),
      "POST /api/admin/profile/experiences": (init) =>
        jsonResponse({ id: "e1", sort_order: 0, ...JSON.parse(init!.body as string) }, 201),
    });
    renderAt("/admin/profile/experience");
    fireEvent.click(await screen.findByRole("button", { name: /add experience/i }));
    const dialog = await screen.findByRole("dialog");
    type(/^company/i, "Acme", dialog);
    type(/^title/i, "Engineer", dialog);
    type(/^start month/i, "2022-05", dialog);
    type(/^end month/i, "2023-01", dialog);
    expect(within(dialog).getByLabelText(/^start month/i)).toHaveAttribute("type", "month");
    fireEvent.click(within(dialog).getByLabelText(/i currently work here/i));
    expect(within(dialog).getByLabelText(/^end month/i)).toBeDisabled();
    expect(within(dialog).getByLabelText(/^end month/i)).toHaveValue("");
    fireEvent.click(within(dialog).getByRole("button", { name: /^save/i }));
    await waitFor(() =>
      expect(calls.some((c) => c.key === "POST /api/admin/profile/experiences")).toBe(true),
    );
    const body = JSON.parse(
      calls.find((c) => c.key === "POST /api/admin/profile/experiences")!.init!.body as string,
    );
    expect(body.end_month).toBeNull();
  });

  it("warns before leaving a dirty form", async () => {
    routes();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderAt("/admin/profile/projects");
    fireEvent.click(await screen.findByRole("button", { name: /add project/i }));
    type(/^name/i, "half typed", await screen.findByRole("dialog"));
    const nav = screen.getByRole("navigation", { name: /admin/i });
    fireEvent.click(within(nav).getByRole("link", { name: /^skills$/i }));
    expect(confirm).toHaveBeenCalled();
    expect(where()).toBe("/admin/profile/projects");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("identity, notes and preview", () => {
  it("saves identity", async () => {
    const { calls } = routes({
      "GET /api/admin/profile/identity": () =>
        jsonResponse({ full_name: "Jane", headline: "", location: "", open_to: "", summary: "" }),
      "GET /api/admin/profile/links": () => jsonResponse({ items: [] }),
      "PUT /api/admin/profile/identity": (init) => jsonResponse(JSON.parse(init!.body as string)),
    });
    renderAt("/admin/profile/identity");
    expect(await screen.findByLabelText(/^full name/i)).toHaveValue("Jane");
    type(/^headline/i, "Backend engineer");
    fireEvent.click(screen.getByRole("button", { name: /save identity/i }));
    expect(await screen.findByText(/saved/i)).toBeInTheDocument();
    const body = JSON.parse(
      calls.find((c) => c.key === "PUT /api/admin/profile/identity")!.init!.body as string,
    );
    expect(body).toMatchObject({ full_name: "Jane", headline: "Backend engineer" });
  });

  it("preview shows the text and token count, warning when large", async () => {
    routes({
      "GET /api/admin/profile/preview": () =>
        jsonResponse({ text: "=== IDENTITY ===\nName: Jane", chars: 30000, approx_tokens: 7500 }),
    });
    renderAt("/admin/profile/preview");
    expect(await screen.findByText(/name: jane/i)).toBeInTheDocument();
    expect(screen.getByText(/7,?500/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/large/i);
  });

  it("notes page loads and saves", async () => {
    const { calls } = routes({
      "GET /api/admin/profile/notes": () => jsonResponse({ content: "old blob" }),
      "PUT /api/admin/profile/notes": (init) => jsonResponse(JSON.parse(init!.body as string)),
    });
    renderAt("/admin/profile/notes");
    expect(await screen.findByLabelText(/^notes/i)).toHaveValue("old blob");
    type(/^notes/i, "new");
    fireEvent.click(screen.getByRole("button", { name: /save notes/i }));
    expect(await screen.findByText(/saved/i)).toBeInTheDocument();
    expect(calls.some((c) => c.key === "PUT /api/admin/profile/notes")).toBe(true);
  });
});

describe("grounded answers", () => {
  const FACTS = {
    as_of: "2026-10-16",
    total_experience: {
      months: 40,
      text: "3 years 4 months",
      years: 3.3,
      from: "2023-06",
      to: "2026-10",
      internships_counted: false,
      freelance_counted: true,
    },
    internship_months: 6,
    current_roles: [
      {
        company: "Acme",
        title: "Backend Engineer",
        since: "2024-02",
        months: 33,
        text: "2 years 9 months",
      },
    ],
    upcoming_roles: [],
    last_role_end: null,
    companies: [],
    first_job_start: "2023-06",
    gaps: [],
    skills: [
      {
        name: "Python",
        months: 38,
        text: "3 years 2 months",
        years: 3.2,
        source: "computed",
        evidence: ["work"],
      },
      { name: "Rust", months: null, text: null, years: null, source: null, evidence: [] },
    ],
    education: {
      latest: {
        degree: "B.Tech",
        field: "CS",
        institution: "IIT",
        end_month: "2023-05",
        in_progress: false,
      },
    },
    counts: { projects: 2, projects_by_status: { active: 2 }, companies: 1 },
  };

  it("identity toggles are sent on save", async () => {
    const { calls } = routes({
      "GET /api/admin/profile/identity": () =>
        jsonResponse({
          full_name: "Jane",
          headline: "",
          location: "",
          open_to: "",
          summary: "",
          count_internships: false,
          count_freelance: true,
        }),
      "GET /api/admin/profile/links": () => jsonResponse({ items: [] }),
      "PUT /api/admin/profile/identity": (init) => jsonResponse(JSON.parse(init!.body as string)),
    });
    renderAt("/admin/profile/identity");
    const interns = await screen.findByLabelText(/count internships/i);
    expect(interns).not.toBeChecked();
    expect(screen.getByLabelText(/count freelance/i)).toBeChecked();
    fireEvent.click(interns);
    fireEvent.click(screen.getByRole("button", { name: /save identity/i }));
    await screen.findByText(/saved/i);
    const body = JSON.parse(
      calls.find((c) => c.key === "PUT /api/admin/profile/identity")!.init!.body as string,
    );
    expect(body.count_internships).toBe(true);
    expect(body.count_freelance).toBe(true);
  });

  it("preview shows the computed facts card", async () => {
    routes({
      "GET /api/admin/profile/preview": () =>
        jsonResponse({ text: "=== FACTS ===", chars: 13, approx_tokens: 4 }),
      "GET /api/admin/profile/facts": () => jsonResponse(FACTS),
    });
    renderAt("/admin/profile/preview");
    const card = await screen.findByRole("region", { name: /computed facts/i });
    expect(within(card).getByText(/3 years 4 months/)).toBeInTheDocument();
    expect(within(card).getByText(/backend engineer at acme/i)).toBeInTheDocument();
    expect(within(card).getByText(/python/i)).toBeInTheDocument();
    expect(within(card).queryByText(/rust/i)).not.toBeInTheDocument();
    expect(within(card).getByText(/internships excluded/i)).toBeInTheDocument();
  });

  it("dashboard summarises open questions with a link to the inbox", async () => {
    routes({
      "GET /api/admin/open-questions": () =>
        jsonResponse({
          items: [
            {
              id: "q1",
              question: "What is your expected CTC?",
              ask_count: 4,
              first_asked_at: "2026-10-15T09:12:00Z",
              last_asked_at: "2026-10-16T09:12:00Z",
              status: "open",
              answered_fact_id: null,
            },
          ],
          open_count: 1,
        }),
    });
    renderAt("/admin");
    const panel = await screen.findByRole("region", { name: /open questions/i });
    expect(await within(panel).findByText("What is your expected CTC?")).toBeInTheDocument();
    expect(within(panel).getByText("4×")).toBeInTheDocument();
    expect(within(panel).getByText(/1 question the bot couldn.t answer/i)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: /answer them/i })).toHaveAttribute(
      "href",
      "/admin/open-questions",
    );
  });

  it("dashboard shows an empty state when nothing is open", async () => {
    routes({ "GET /api/admin/open-questions": () => jsonResponse({ items: [], open_count: 0 }) });
    renderAt("/admin");
    const panel = await screen.findByRole("region", { name: /open questions/i });
    expect(await within(panel).findByText(/no open questions/i)).toBeInTheDocument();
  });
});
