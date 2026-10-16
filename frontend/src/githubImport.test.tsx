import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { checkRepoUrls, MAX_REPOS } from "./components/admin/GithubImportCard";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const repos = Array.from({ length: 12 }, (_, i) => ({
  name: `repo${i}`,
  full_name: `jane/repo${i}`,
  description: i === 0 ? "Portfolio bot" : null,
  language: "Python",
  stars: 12 - i,
  pushed_at: "2026-10-01T00:00:00Z",
  fork: false,
  archived: false,
  html_url: `https://github.com/jane/repo${i}`,
}));

const GH_JOB = {
  id: "g1",
  kind: "github",
  status: "ready",
  filename: "jane/mebot",
  size_bytes: 1,
  error_code: null,
  error_message: null,
  applied_summary: null,
  created_at: "2026-10-17T10:00:00Z",
  expires_at: "2026-10-24T10:00:00Z",
  source_text: null,
  draft: {
    sections: {
      projects: [
        {
          temp_id: "p1",
          data: { name: "mebot", summary: "Bot", tech: ["Python", "FastAPI"] },
          match: { status: "new" },
          needs_review: false,
          default_action: "add",
          evidence: [
            { tech: "Python", file: "GitHub languages", key: "60%" },
            { tech: "FastAPI", file: "backend/requirements.txt", key: "fastapi" },
          ],
        },
      ],
    },
    errors: [{ source: "jane/private", code: "REPO_NOT_FOUND", message: "Repo not found (private repos can't be imported)." }],
  },
};

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () => jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/admin/llm": () => jsonResponse({ configured: true, status: "ok", last_test_ok: true, model: "m" }),
    "GET /api/admin/import/jobs": () => jsonResponse({ items: [] }),
    "GET /api/admin/integrations/github": () => jsonResponse({ configured: false, token_last4: null, env_token: false }),
    "GET /api/admin/import/github/repos": () => jsonResponse({ items: repos }),
    "POST /api/admin/import/github": () => jsonResponse({ id: "g1", status: "processing" }, 202),
    "GET /api/admin/import/jobs/g1": () => jsonResponse(GH_JOB),
    ...extra,
  });
}

function renderAt() {
  return render(
    <MemoryRouter initialEntries={["/admin/import"]}>
      <App />
    </MemoryRouter>,
  );
}

const lastBody = (api: ReturnType<typeof routes>, key: string) =>
  JSON.parse(String(api.calls.filter((c) => c.key === key).pop()!.init!.body));

describe("checkRepoUrls", () => {
  it("validates, dedupes and caps", () => {
    expect(checkRepoUrls("https://github.com/a/b\nhttps://github.com/a/b.git\n\nhttps://github.com/a/c/tree/main/x")).toEqual({
      urls: ["https://github.com/a/b.git", "https://github.com/a/c/tree/main/x"],
      errors: [],
    });
    expect(checkRepoUrls("https://gitlab.com/a/b").errors[0]).toMatch(/not a github repo url/i);
    const many = Array.from({ length: MAX_REPOS + 1 }, (_, i) => `https://github.com/a/r${i}`).join("\n");
    expect(checkRepoUrls(many).errors[0]).toMatch(/at most 10/i);
  });
});

describe("github card", () => {
  it("imports pasted URLs and shows the review with evidence and per-repo errors", async () => {
    const api = routes();
    renderAt();
    expect(await screen.findByRole("heading", { name: "GitHub" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/one url per line/i), {
      target: { value: "https://github.com/jane/mebot\nhttps://github.com/jane/private" },
    });
    fireEvent.click(screen.getByRole("button", { name: "import" }));
    expect(await screen.findByText("mebot")).toBeInTheDocument();
    expect(lastBody(api, "POST /api/admin/import/github")).toEqual({
      repo_urls: ["https://github.com/jane/mebot", "https://github.com/jane/private"],
    });
    expect(screen.getByRole("alert")).toHaveTextContent("jane/private");
    const card = screen.getByText("mebot").closest("li")!;
    fireEvent.click(within(card).getByRole("button", { name: "evidence" }));
    const table = within(card).getByRole("table");
    expect(within(table).getByText("backend/requirements.txt (fastapi)")).toBeInTheDocument();
    expect(within(table).getByText("FastAPI")).toBeInTheDocument();
  });

  it("validates URLs client-side", async () => {
    const api = routes();
    renderAt();
    fireEvent.change(await screen.findByLabelText(/one url per line/i), { target: { value: "https://evil.dev/a/b" } });
    fireEvent.click(screen.getByRole("button", { name: "import" }));
    expect(await screen.findByText(/not a github repo url/i)).toBeInTheDocument();
    expect(api.calls.some((c) => c.key === "POST /api/admin/import/github")).toBe(false);
  });

  it("username picker selects at most 10 and imports them", async () => {
    const api = routes();
    renderAt();
    fireEvent.click(await screen.findByRole("tab", { name: "From username" }));
    fireEvent.change(screen.getByLabelText("GitHub username"), { target: { value: "jane" } });
    fireEvent.click(screen.getByRole("button", { name: "list repos" }));
    expect(await screen.findByText("Portfolio bot")).toBeInTheDocument();
    for (let i = 0; i < 11; i++) fireEvent.click(screen.getByLabelText(`jane/repo${i}`));
    expect(screen.getByText(`${MAX_REPOS}/${MAX_REPOS} selected`)).toBeInTheDocument();
    expect(screen.getByLabelText("jane/repo10")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /import 10 repos/i }));
    await waitFor(() => expect(api.calls.some((c) => c.key === "POST /api/admin/import/github")).toBe(true));
    expect(lastBody(api, "POST /api/admin/import/github").repo_urls).toHaveLength(10);
    const listCall = api.calls.find((c) => c.key === "GET /api/admin/import/github/repos")!;
    expect(listCall).toBeTruthy();
  });

  it("picker: unknown user and empty list", async () => {
    routes({ "GET /api/admin/import/github/repos": () => errorResponse(404, "USER_NOT_FOUND", "GitHub user not found.") });
    renderAt();
    fireEvent.click(await screen.findByRole("tab", { name: "From username" }));
    fireEvent.change(screen.getByLabelText("GitHub username"), { target: { value: "ghost" } });
    fireEvent.click(screen.getByRole("button", { name: "list repos" }));
    expect(await screen.findByText(/no github user with that name/i)).toBeInTheDocument();
  });

  it("server-side URL errors are shown", async () => {
    routes({
      "POST /api/admin/import/github": () =>
        errorResponse(422, "INVALID_REPO_URL", "Some repo URLs aren't valid.", [
          { field: "repo_urls.0", message: "Use a GitHub repo URL like https://github.com/owner/repo." },
        ]),
    });
    renderAt();
    fireEvent.change(await screen.findByLabelText(/one url per line/i), { target: { value: "https://github.com/a/b" } });
    fireEvent.click(screen.getByRole("button", { name: "import" }));
    expect(await screen.findByText(/like https:\/\/github.com\/owner\/repo/i)).toBeInTheDocument();
  });

  it("token field: masked input, saved shows last 4, remove", async () => {
    const api = routes({
      "PUT /api/admin/integrations/github": () => jsonResponse({ configured: true, token_last4: "6789", env_token: false }),
      "DELETE /api/admin/integrations/github": () => new Response(null, { status: 204 }),
    });
    renderAt();
    const input = await screen.findByLabelText("GitHub token");
    expect(input).toHaveAttribute("type", "password");
    fireEvent.change(input, { target: { value: "ghp_abcdefghijklmnopqrstuvwxyz0123456789" } });
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    expect(await screen.findByText("saved ••••6789")).toBeInTheDocument();
    expect(lastBody(api, "PUT /api/admin/integrations/github")).toEqual({ token: "ghp_abcdefghijklmnopqrstuvwxyz0123456789" });
    fireEvent.click(screen.getByRole("button", { name: "remove" }));
    expect(await screen.findByLabelText("GitHub token")).toBeInTheDocument();
  });
});
