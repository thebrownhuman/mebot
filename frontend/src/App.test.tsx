import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { errorResponse, jsonResponse, mockApi } from "./test/fetchMock";

// WebGL is unavailable in jsdom; the orb is decorative.
vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

beforeEach(() => {
  mockApi({
    "GET /api/setup/status": () => jsonResponse({ setup_required: false }),
    "GET /api/health": () => jsonResponse({ ollama: true, model: "me-bot" }),
    "GET /api/auth/me": () => errorResponse(401, "UNAUTHENTICATED", "Login required"),
  });
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App routes", () => {
  it("renders the public chat at /", async () => {
    renderAt("/");
    expect(await screen.findByLabelText(/your name/i)).toBeInTheDocument();
    expect(screen.getByText(/talking about the candidate/i)).toBeInTheDocument();
  });

  it("redirects unknown paths to the chat", async () => {
    renderAt("/talkaboutsomeone");
    expect(await screen.findByLabelText(/your name/i)).toBeInTheDocument();
  });

  it("guards the admin page at /admin", async () => {
    renderAt("/admin");
    expect(await screen.findByRole("heading", { name: /log in/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/your name/i)).not.toBeInTheDocument();
  });

  it("does not mention a hardcoded owner name", async () => {
    const { container } = renderAt("/");
    await screen.findByLabelText(/your name/i);
    expect(container.textContent?.toLowerCase()).not.toContain("shivansh");
  });
});
