import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { summaryText } from "./components/admin/ImportReview";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const LLM_OK = { configured: true, status: "ok", last_test_ok: true, model: "m" };

const entry = (temp_id: string, data: Record<string, unknown>, over: Record<string, unknown> = {}) => ({
  temp_id,
  data,
  match: { status: "new" },
  needs_review: false,
  default_action: "add",
  ...over,
});

const READY_JOB = {
  id: "j1",
  kind: "resume",
  status: "ready",
  filename: "cv.pdf",
  size_bytes: 100,
  error_code: null,
  error_message: null,
  applied_summary: null,
  created_at: "2026-10-17T10:00:00Z",
  expires_at: "2026-10-24T10:00:00Z",
  source_text: "Jane Doe\nAcme Corp - Backend Engineer, Feb 2021 - Present\nSkills: Python",
  draft: {
    sections: {
      identity: [
        entry("i-headline", { field: "headline", value: "Backend Engineer" }, {
          match: { status: "changed", diff: { value: { from: "Engineer", to: "Backend Engineer" } } },
          default_action: "update",
        }),
      ],
      experiences: [
        entry("e1", { company: "Acme Corp", title: "Backend Engineer", start_month: "2021-02" }, {
          snippet: "Acme Corp - Backend Engineer, Feb 2021 - Present",
        }),
        entry("e2", { company: "Initech", title: "Engineer", start_month: "2018-01" }, {
          needs_review: true,
          reason: "“Initech” isn't in your resume",
          default_action: "skip",
        }),
      ],
      educations: [
        entry("d1", { institution: "CNCF", degree: "CKA", start_month: "2023-03" }, { kind: "certification" }),
      ],
      skills: [
        entry("s1", { name: "Python" }, { match: { status: "same", existing_id: "x" }, default_action: "skip" }),
        entry("s2", { name: "Go" }, { default_action: "skip" }),
      ],
    },
  },
};

const SUMMARY = {
  identity: { added: 0, updated: 1 },
  experiences: { added: 1, updated: 0 },
  skills: { added: 1, updated: 0 },
};

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () => jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/admin/llm": () => jsonResponse(LLM_OK),
    "GET /api/admin/import/jobs": () => jsonResponse({ items: [] }),
    "GET /api/admin/import/jobs/j1": () => jsonResponse(READY_JOB),
    "POST /api/admin/import/jobs/j1/apply": () => jsonResponse({ applied: SUMMARY }),
    "DELETE /api/admin/import/jobs/j1": () => new Response(null, { status: 204 }),
    ...extra,
  });
}

function renderAt(path = "/admin/import") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

// jsdom has no real upload: a minimal XMLHttpRequest that answers like the server.
class FakeXHR {
  static next: { status: number; body: unknown } = { status: 202, body: { id: "j1", status: "processing" } };
  static sent: { url: string; headers: Record<string, string>; body: FormData | null }[] = [];
  status = 0;
  responseText = "";
  withCredentials = false;
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private url = "";
  private headers: Record<string, string> = {};
  open(_m: string, url: string) {
    this.url = url;
  }
  setRequestHeader(k: string, v: string) {
    this.headers[k] = v;
  }
  getResponseHeader() {
    return null;
  }
  send(body: FormData) {
    FakeXHR.sent.push({ url: this.url, headers: this.headers, body });
    this.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
    setTimeout(() => {
      this.status = FakeXHR.next.status;
      this.responseText = JSON.stringify(FakeXHR.next.body);
      this.onload?.();
    }, 0);
  }
}

beforeEach(() => {
  FakeXHR.sent = [];
  FakeXHR.next = { status: 202, body: { id: "j1", status: "processing" } };
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
});
afterEach(() => vi.unstubAllGlobals());

function pick(label: RegExp, file: File) {
  fireEvent.change(screen.getByLabelText(label), { target: { files: [file] } });
}

describe("import page", () => {
  it("is in the sidebar with two cards, a LinkedIn guide and the privacy note", async () => {
    routes();
    renderAt();
    expect(await screen.findByRole("heading", { name: "Import", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Import" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "LinkedIn export" })).toBeInTheDocument();
    expect(screen.getByText(/how to get your linkedin data/i)).toBeInTheDocument();
    expect(screen.getByText(/never read your linkedin messages or connections/i)).toBeInTheDocument();
  });

  it("disables resume import without a working AI provider", async () => {
    routes({ "GET /api/admin/llm": () => jsonResponse({ ...LLM_OK, last_test_ok: false }) });
    renderAt();
    await waitFor(() => expect(screen.getByLabelText(/upload resume/i)).toBeDisabled());
    expect(screen.getByRole("link", { name: /set it up first/i })).toHaveAttribute("href", "/admin/llm");
    expect(screen.getByLabelText(/upload linkedin export/i)).not.toBeDisabled();
  });

  it("pre-checks extension and size before uploading", async () => {
    routes();
    renderAt();
    await waitFor(() => expect(screen.getByLabelText(/upload resume/i)).not.toBeDisabled());
    pick(/upload resume/i, new File(["x"], "cv.doc"));
    expect(await screen.findByText(/save it as \.docx/i)).toBeInTheDocument();
    const big = new File(["x"], "cv.pdf");
    Object.defineProperty(big, "size", { value: 11 * 1024 * 1024 });
    pick(/upload resume/i, big);
    expect(await screen.findByText(/too large/i)).toBeInTheDocument();
    expect(FakeXHR.sent).toHaveLength(0);
  });

  it("uploads with progress, polls while processing, then shows the review", async () => {
    let status = "processing";
    routes({
      "GET /api/admin/import/jobs/j1": () =>
        jsonResponse(status === "processing" ? { ...READY_JOB, status, draft: null } : READY_JOB),
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderAt();
      await waitFor(() => expect(screen.getByLabelText(/upload resume/i)).not.toBeDisabled());
      pick(/upload resume/i, new File(["%PDF-"], "cv.pdf", { type: "application/pdf" }));
      expect(await screen.findByText(/reading your resume/i)).toBeInTheDocument();
      expect(FakeXHR.sent[0].url).toBe("/api/admin/import/resume");
      expect((FakeXHR.sent[0].body as FormData).get("file")).toBeInstanceOf(File);
      status = "ready";
      await act(async () => {
        vi.advanceTimersByTime(2100);
      });
      expect(await screen.findByText("Backend Engineer — Acme Corp")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows upload errors from the server", async () => {
    FakeXHR.next = { status: 415, body: { error: { code: "ENCRYPTED_PDF", message: "That PDF is password-protected." } } };
    routes();
    renderAt();
    await waitFor(() => expect(screen.getByLabelText(/upload resume/i)).not.toBeDisabled());
    pick(/upload resume/i, new File(["x"], "cv.pdf"));
    expect(await screen.findByRole("alert")).toHaveTextContent("password-protected");
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("heading", { name: "Resume" })).toBeInTheDocument();
  });

  it("shows a failed job's message", async () => {
    routes({
      "GET /api/admin/import/jobs": () => jsonResponse({ items: [{ ...READY_JOB, status: "processing" }] }),
      "GET /api/admin/import/jobs/j1": () =>
        jsonResponse({ ...READY_JOB, status: "failed", draft: null, error_message: "Looks like a scanned PDF" }),
    });
    renderAt();
    expect(await screen.findByText(/scanned pdf/i)).toBeInTheDocument();
  });
});

describe("import review", () => {
  async function openReview(extra: Record<string, Handler> = {}) {
    const api = routes({
      "GET /api/admin/import/jobs": () => jsonResponse({ items: [READY_JOB] }),
      ...extra,
    });
    renderAt();
    await screen.findByText("Backend Engineer — Acme Corp");
    return api;
  }

  const lastApply = (api: ReturnType<typeof routes>) =>
    JSON.parse(String(api.calls.filter((c) => c.key === "POST /api/admin/import/jobs/j1/apply").pop()!.init!.body));

  it("shows badges, diffs, needs-review reasons, certifications separately", async () => {
    await openReview();
    const card = (text: string) => screen.getByText(text).closest("li")!;
    expect(within(card("Backend Engineer — Acme Corp")).getByText("New")).toBeInTheDocument();
    expect(within(card("Python")).getByText("Already in profile")).toBeInTheDocument();
    const headline = card("headline: Backend Engineer");
    expect(within(headline).getByText("Changed")).toBeInTheDocument();
    expect(within(headline).getByText("Engineer")).toBeInTheDocument();
    const initech = card("Engineer — Initech");
    expect(within(initech).getByRole("note")).toHaveTextContent("isn't in your resume");
    expect(within(initech).getByRole("radio", { name: "Skip" })).toBeChecked();
    expect(screen.getByRole("heading", { name: /certifications/i })).toBeInTheDocument();
  });

  it("show in source highlights the matched resume text", async () => {
    await openReview();
    fireEvent.click(screen.getByRole("button", { name: /show in source/i }));
    expect(document.querySelector("mark")?.textContent).toBe("Acme Corp - Backend Engineer, Feb 2021 - Present");
  });

  it("accept all new, edit inline, and apply with the decisions", async () => {
    const api = await openReview();
    fireEvent.click(screen.getByRole("button", { name: /accept all new/i }));
    const goCard = screen.getByText("Go").closest("li")!;
    expect(within(goCard).getByRole("radio", { name: "Add" })).toBeChecked();
    // needs-review items stay skipped
    expect(within(screen.getByText("Engineer — Initech").closest("li")!).getByRole("radio", { name: "Skip" })).toBeChecked();
    fireEvent.click(within(goCard).getByRole("button", { name: "edit" }));
    fireEvent.change(within(goCard).getByLabelText("name"), { target: { value: "Golang" } });
    fireEvent.click(within(goCard).getByRole("button", { name: "done" }));
    fireEvent.click(screen.getByRole("button", { name: /^apply \d+ items?/i }));
    expect(await screen.findByText("Added 1 job, 1 skill; updated 1.")).toBeInTheDocument();
    const body = lastApply(api);
    const by = Object.fromEntries(body.decisions.map((d: { temp_id: string }) => [d.temp_id, d]));
    expect(by["s2"]).toEqual({ temp_id: "s2", action: "add", data: { name: "Golang" } });
    expect(by["e2"].action).toBe("skip");
    expect(by["i-headline"].action).toBe("update");
    const done = screen.getByRole("status");
    expect(within(done).getByRole("link", { name: "Experience" })).toHaveAttribute("href", "/admin/profile/experience");
  });

  it("shows per-item errors when apply is rejected", async () => {
    await openReview({
      "POST /api/admin/import/jobs/j1/apply": () =>
        errorResponse(422, "VALIDATION_ERROR", "Some items need fixing; nothing was applied.", [
          { field: "e1.end_month", message: "end month is before start month" },
        ]),
    });
    fireEvent.click(screen.getByRole("button", { name: /^apply/i }));
    expect(await screen.findByText(/nothing was applied/i)).toBeInTheDocument();
    const card = screen.getByText("Backend Engineer — Acme Corp").closest("li")!;
    expect(within(card).getByRole("alert")).toHaveTextContent("end_month: end month is before start month");
  });

  it("discard returns to the cards", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const api = await openReview();
    fireEvent.click(screen.getByRole("button", { name: "discard" }));
    expect(await screen.findByRole("heading", { name: "Resume" })).toBeInTheDocument();
    expect(api.calls.some((c) => c.key === "DELETE /api/admin/import/jobs/j1")).toBe(true);
  });
});

describe("summaryText", () => {
  it("reads naturally", () => {
    expect(
      summaryText({ experiences: { added: 4, updated: 0 }, projects: { added: 2, updated: 1 }, skills: { added: 11, updated: 0 } }),
    ).toBe("Added 4 jobs, 2 projects, 11 skills; updated 1.");
    expect(summaryText({})).toBe("Nothing changed.");
  });
});
