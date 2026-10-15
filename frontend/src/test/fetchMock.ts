import { vi } from "vitest";

export type Handler = (init: RequestInit | undefined) => Response | Promise<Response>;

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function errorResponse(status: number, code: string, message: string, details?: unknown) {
  return jsonResponse({ error: { code, message, status, ...(details ? { details } : {}) } }, status);
}

// Routes fetch calls by "METHOD /path" (query string ignored). Unmatched -> 404.
export function mockApi(routes: Record<string, Handler>) {
  const calls: { key: string; init?: RequestInit }[] = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const key = `${(init?.method ?? "GET").toUpperCase()} ${path}`;
    calls.push({ key, init });
    const h = routes[key];
    return h ? h(init) : errorResponse(404, "NOT_FOUND", "Not Found");
  });
  return { spy, calls };
}
