import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

// WebGL is unavailable in jsdom; the orb is decorative.
vi.mock("./components/Orb", () => ({ default: () => <div data-testid="orb" /> }));

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ ollama: true, model: "me-bot" }), {
      headers: { "Content-Type": "application/json" },
    }),
  );
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App routes", () => {
  it("renders the public chat at /", () => {
    renderAt("/");
    expect(screen.getByLabelText(/your name/i)).toBeInTheDocument();
    expect(screen.getByText(/talking about the candidate/i)).toBeInTheDocument();
  });

  it("redirects unknown paths to the chat", () => {
    renderAt("/talkaboutsomeone");
    expect(screen.getByLabelText(/your name/i)).toBeInTheDocument();
  });

  it("serves the admin page at /admin", () => {
    renderAt("/admin");
    expect(screen.queryByLabelText(/your name/i)).not.toBeInTheDocument();
  });

  it("does not mention a hardcoded owner name", () => {
    const { container } = renderAt("/");
    expect(container.textContent?.toLowerCase()).not.toContain("shivansh");
  });
});
