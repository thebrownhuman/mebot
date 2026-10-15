// Typed client for the FastAPI backend. All paths are same-origin "/api/..."
// because Vite proxies them to http://localhost:8000 in dev.
//
// Auth is a server-side session in an HttpOnly cookie. Mutating requests echo the
// readable `mebot_csrf` cookie in X-CSRF-Token (double-submit). A 401 from an admin
// call fires UNAUTHORIZED_EVENT so the admin guard can send the user to the login page.

export interface HealthResp {
  ollama: boolean;
  model: string | null;
  message?: string;
}

export interface SessionSummary {
  id: string;
  recruiter_name: string | null;
  started_at: number;
  turns: number;
}

export interface StoredMessage {
  role: "user" | "assistant";
  content: string;
  ts: number;
}

export interface LogEntry {
  event: string;
  detail: string | null;
  ip: string | null;
  ts: number;
}

export interface Me {
  email: string;
  bot_name: string;
  bot_slug: string;
}

export interface SetupReq {
  email: string;
  password: string;
  bot_name: string;
  bot_slug: string;
  registration_consent: boolean;
  setup_token?: string;
}

export interface FieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: FieldError[] = [],
  ) {
    super(message);
  }
}

export const UNAUTHORIZED_EVENT = "mebot:unauthorized";
export const CSRF_COOKIE = "mebot_csrf";

export function readCookie(name: string): string | null {
  for (const part of document.cookie.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return decodeURIComponent(v.join("="));
  }
  return null;
}

async function toApiError(r: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    // non-JSON error body
  }
  const err = (body as { error?: { code?: string; message?: string; details?: FieldError[] } })
    ?.error;
  const detail = (body as { detail?: unknown })?.detail;
  const message =
    err?.message || (typeof detail === "string" ? detail : "") || `Request failed (${r.status})`;
  return new ApiError(r.status, err?.code ?? "HTTP_ERROR", message, err?.details ?? []);
}

interface ReqOpts {
  method?: string;
  body?: unknown;
  // Admin calls broadcast 401s; login/me handle 401 themselves.
  notifyUnauthorized?: boolean;
}

async function send(path: string, { method = "GET", body, notifyUnauthorized = false }: ReqOpts = {}) {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && method !== "HEAD") {
    const token = readCookie(CSRF_COOKIE);
    if (token) headers["X-CSRF-Token"] = token;
  }
  const r = await fetch(path, {
    method,
    headers,
    credentials: "include",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    if (r.status === 401 && notifyUnauthorized) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw await toApiError(r);
  }
  return r;
}

async function json<T>(path: string, opts?: ReqOpts): Promise<T> {
  const r = await send(path, opts);
  return (await r.json()) as T;
}

const admin = { notifyUnauthorized: true };

// --- public ------------------------------------------------------------------

export async function getHealth(): Promise<HealthResp> {
  try {
    const r = await fetch("/api/health");
    return (await r.json()) as HealthResp;
  } catch {
    return { ollama: false, model: null, message: "backend not reachable" };
  }
}

export async function startSession(recruiterName?: string): Promise<string> {
  const d = await json<{ session_id: string }>("/api/session", {
    method: "POST",
    body: { recruiter_name: recruiterName ?? null },
  });
  return d.session_id;
}

// Streams the assistant reply. Calls onToken for each chunk; resolves when done.
export async function streamChat(
  sessionId: string,
  message: string,
  onToken: (chunk: string) => void,
): Promise<void> {
  const r = await send("/api/chat", { method: "POST", body: { session_id: sessionId, message } });
  if (!r.body) throw new Error(`HTTP ${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    onToken(dec.decode(value, { stream: true }));
  }
}

// --- setup + auth ------------------------------------------------------------

export async function getSetupStatus(): Promise<{ setup_required: boolean }> {
  return json("/api/setup/status");
}

export async function runSetup(req: SetupReq): Promise<{ email: string; bot_slug: string }> {
  return json("/api/setup", { method: "POST", body: req });
}

export async function login(email: string, password: string): Promise<void> {
  await send("/api/auth/login", { method: "POST", body: { email, password } });
}

export async function logout(): Promise<void> {
  await send("/api/auth/logout", { method: "POST" });
}

export async function getMe(): Promise<Me> {
  return json("/api/auth/me");
}

export async function changePassword(currentPassword: string, newPassword: string) {
  await send("/api/auth/password", {
    method: "POST",
    body: { current_password: currentPassword, new_password: newPassword },
    ...admin,
  });
}

// --- admin -------------------------------------------------------------------

export async function getProfile(): Promise<string> {
  const d = await json<{ content: string }>("/api/admin/profile", admin);
  return d.content;
}

export async function saveProfile(content: string): Promise<void> {
  await send("/api/admin/profile", { method: "PUT", body: { content }, ...admin });
}

export async function listSessions(): Promise<SessionSummary[]> {
  return json("/api/admin/sessions", admin);
}

export async function getSessionMessages(sid: string): Promise<StoredMessage[]> {
  return json(`/api/admin/sessions/${encodeURIComponent(sid)}/messages`, admin);
}

export async function getLog(limit = 100): Promise<LogEntry[]> {
  return json(`/api/admin/log?limit=${limit}`, admin);
}
