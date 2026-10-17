import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { KnowledgeStatus } from "./lib/api";
import { errorResponse, jsonResponse, mockApi, type Handler } from "./test/fetchMock";

vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

const STATUS: KnowledgeStatus = {
  mode: "auto",
  effective: "full",
  reason:
    "Your profile is about 1,200 tokens, within the 6,000-token threshold, so the whole profile is sent with every message.",
  profile_tokens: 1200,
  threshold_tokens: 6000,
  budget_tokens: 2500,
  chunk_count: 0,
  last_indexed_at: null,
  index_stale: true,
  usage: {
    days: 7,
    questions: 0,
    retrieval_replies: 0,
    avg_prompt_tokens: 0,
    avg_profile_tokens: 0,
    saved_percent: 0,
  },
  embeddings: {
    supported: true,
    reason: null,
    enabled: false,
    model: null,
    default_model: "text-embedding-3-small",
    embedded: 0,
    total: 0,
    last_error: null,
  },
};

const LARGE: KnowledgeStatus = {
  ...STATUS,
  effective: "retrieval",
  reason: "Your profile is about 9,000 tokens, above the 6,000-token threshold, so only the parts relevant to each question are sent.",
  profile_tokens: 9000,
  chunk_count: 62,
  last_indexed_at: "2026-10-17T10:00:00Z",
  index_stale: false,
  usage: {
    days: 7,
    questions: 20,
    retrieval_replies: 18,
    avg_prompt_tokens: 2100,
    avg_profile_tokens: 9000,
    saved_percent: 77,
  },
};

function routes(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/auth/me": () =>
      jsonResponse({ email: "o@example.com", bot_name: "Jane", bot_slug: "jane" }),
    "GET /api/admin/llm": () => jsonResponse({ configured: true, last_test_ok: true }),
    "GET /api/admin/open-questions": () => jsonResponse({ items: [], open_count: 0 }),
    "GET /api/admin/knowledge": () => jsonResponse(STATUS),
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

const sent = (calls: { key: string; init?: RequestInit }[], key: string) =>
  JSON.parse(String(calls.filter((c) => c.key === key).slice(-1)[0].init!.body));

describe("knowledge page", () => {
  it("is in the sidebar and explains whole-profile mode", async () => {
    routes();
    renderAt("/admin/knowledge");
    expect(await screen.findByRole("heading", { name: /^knowledge$/i })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: /admin/i });
    expect(within(nav).getByRole("link", { name: /^knowledge$/i })).toBeInTheDocument();
    expect(await screen.findByText("whole profile")).toBeInTheDocument();
    expect(screen.getByText(/within the 6,000-token threshold/)).toBeInTheDocument();
    expect(screen.getByText("~1,200 tokens")).toBeInTheDocument();
    expect(screen.getByText(/nothing is indexed yet/i)).toBeInTheDocument(); // empty state
    expect(screen.getByText(/no replies used retrieval yet/i)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /automatic/i })).toBeChecked();
  });

  it("shows retrieval mode, chunk count, last indexed and the savings", async () => {
    routes({ "GET /api/admin/knowledge": () => jsonResponse(LARGE) });
    renderAt("/admin/knowledge");
    expect(await screen.findByText("retrieval")).toBeInTheDocument();
    expect(screen.getByText("62")).toBeInTheDocument();
    expect(screen.getByText(/18 of 20 questions used retrieval/)).toBeInTheDocument();
    expect(screen.getByText("77% less")).toBeInTheDocument();
    expect(screen.queryByText(/nothing is indexed yet/i)).toBeNull();
  });

  it("shows a loading state, then a load error that can be retried", async () => {
    let fail = true;
    routes({
      "GET /api/admin/knowledge": () =>
        fail ? errorResponse(500, "INTERNAL", "Database is locked") : jsonResponse(STATUS),
    });
    renderAt("/admin/knowledge");
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Database is locked");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("whole profile")).toBeInTheDocument();
  });

  it("saves the chosen mode", async () => {
    const api = routes({
      "PUT /api/admin/knowledge": (init) =>
        jsonResponse({ ...LARGE, mode: JSON.parse(String(init!.body)).mode }),
    });
    renderAt("/admin/knowledge");
    fireEvent.click(await screen.findByRole("radio", { name: /always retrieve/i }));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(api.calls.some((c) => c.key === "PUT /api/admin/knowledge")).toBe(true));
    expect(sent(api.calls, "PUT /api/admin/knowledge")).toMatchObject({ mode: "always" });
    expect(await screen.findByRole("radio", { name: /always retrieve/i })).toBeChecked();
  });

  it("enables embeddings with a model", async () => {
    const api = routes({
      "PUT /api/admin/knowledge": (init) => {
        const b = JSON.parse(String(init!.body));
        return jsonResponse({
          ...LARGE,
          embeddings: {
            ...LARGE.embeddings,
            enabled: b.embeddings_enabled,
            model: b.embedding_model ?? "text-embedding-3-small",
            embedded: 62,
            total: 62,
          },
        });
      },
    });
    renderAt("/admin/knowledge");
    fireEvent.click(await screen.findByRole("checkbox", { name: /also rank by meaning/i }));
    fireEvent.change(screen.getByLabelText(/embedding model/i), { target: { value: "my-embed" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(api.calls.some((c) => c.key === "PUT /api/admin/knowledge")).toBe(true));
    expect(sent(api.calls, "PUT /api/admin/knowledge")).toMatchObject({
      embeddings_enabled: true,
      embedding_model: "my-embed",
    });
    expect(await screen.findByText(/62 of 62 chunks embedded with my-embed/)).toBeInTheDocument();
  });

  it("disables embeddings with an explanation when the provider has none", async () => {
    routes({
      "GET /api/admin/knowledge": () =>
        jsonResponse({
          ...STATUS,
          embeddings: {
            ...STATUS.embeddings,
            supported: false,
            reason: "Anthropic has no embeddings API, so ranking stays keyword-based.",
          },
        }),
    });
    renderAt("/admin/knowledge");
    const box = await screen.findByRole("checkbox", { name: /also rank by meaning/i });
    expect(box).toBeDisabled();
    expect(screen.getByText(/anthropic has no embeddings api/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/embedding model/i)).toBeNull();
  });

  it("shows save errors and the paused-embeddings notice", async () => {
    routes({
      "GET /api/admin/knowledge": () =>
        jsonResponse({
          ...LARGE,
          embeddings: {
            ...LARGE.embeddings,
            enabled: true,
            model: "m",
            last_error: "OpenAI rejected the API key (401).",
          },
        }),
      "PUT /api/admin/knowledge": () =>
        errorResponse(422, "EMBEDDINGS_UNSUPPORTED", "Set up your AI provider first.", [
          { field: "embeddings_enabled", message: "Set up your AI provider first." },
        ]),
    });
    renderAt("/admin/knowledge");
    expect(await screen.findByText(/embeddings paused: openai rejected the api key/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect((await screen.findAllByText(/set up your ai provider first/i)).length).toBeGreaterThan(0);
  });

  it("rebuilds the index", async () => {
    const api = routes({
      "POST /api/admin/knowledge/rebuild": () => jsonResponse({ ...LARGE, chunk_count: 70 }),
    });
    renderAt("/admin/knowledge");
    fireEvent.click(await screen.findByRole("button", { name: /rebuild index/i }));
    expect(await screen.findByText("70")).toBeInTheDocument();
    expect(api.calls.some((c) => c.key === "POST /api/admin/knowledge/rebuild")).toBe(true);
  });
});

describe("conversation detail: retrieved profile parts", () => {
  const DETAIL = {
    id: "a",
    recruiter_name: "Ann",
    started_at: "2026-10-16T10:00:00Z",
    origin: "direct",
    messages: [
      {
        role: "user",
        content: "Tell me about Kafka",
        created_at: "2026-10-16T10:00:30Z",
        unanswered: false,
        from_owner: false,
      },
      {
        role: "assistant",
        content: "He built a streaming pipeline.",
        created_at: "2026-10-16T10:00:40Z",
        unanswered: false,
        from_owner: false,
        chunks: [
          { id: "c1", section: "projects", title: "Project Kafka 0" },
          { id: "c2", section: "experiences", title: "Engineer at Acme" },
        ],
      },
    ],
    events: [],
    contact: null,
  };

  it("lists the chunk titles used for a bot reply only", async () => {
    routes({
      "GET /api/admin/conversations": () =>
        jsonResponse({
          items: [
            {
              id: "a",
              recruiter_name: "Ann",
              started_at: "2026-10-16T10:00:00Z",
              last_message_at: "2026-10-16T10:05:00Z",
              messages: 2,
              origin: "direct",
              flags: [],
              preview: "Tell me about Kafka",
            },
          ],
          next_cursor: null,
        }),
      "GET /api/admin/conversations/a": () => jsonResponse(DETAIL),
    });
    renderAt("/admin/conversations");
    fireEvent.click(await screen.findByRole("button", { name: /ann/i }));
    const summary = await screen.findByText(/profile parts used \(2\)/i);
    expect(screen.getAllByText(/profile parts used/i)).toHaveLength(1);
    fireEvent.click(summary);
    expect(screen.getByText(/Project Kafka 0/)).toBeInTheDocument();
    expect(screen.getByText(/Engineer at Acme/)).toBeInTheDocument();
  });
});
