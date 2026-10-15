// Typed client for the FastAPI backend. All paths are same-origin "/api/..."
// because Vite proxies them to http://localhost:8000 in dev.
//
// Auth is a server-side session in an HttpOnly cookie. Mutating requests echo the
// readable `mebot_csrf` cookie in X-CSRF-Token (double-submit). A 401 from an admin
// call fires UNAUTHORIZED_EVENT so the admin guard can send the user to the login page.

export interface HealthResp {
  ready: boolean;
  model: string | null;
  message?: string;
}

export interface LlmProvider {
  id: string;
  name: string;
  key_required: boolean;
  default_base_url: string | null;
  key_url: string | null;
  suggested_models: string[];
  base_url_required: boolean;
}

export interface LlmInput {
  provider: string;
  model: string;
  api_key?: string;
  base_url?: string;
}

export interface LlmConfigView {
  configured: boolean;
  status: "ok" | "missing" | "undecryptable";
  provider: string | null;
  model: string | null;
  base_url: string | null;
  has_key: boolean;
  api_key_last4: string | null;
  temperature: number;
  max_tokens: number;
  last_tested_at: string | null;
  last_test_ok: boolean | null;
}

export interface LlmTestResult {
  ok: boolean;
  latency_ms: number;
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
  llm: LlmInput;
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

async function send(
  path: string,
  { method = "GET", body, notifyUnauthorized = false }: ReqOpts = {},
) {
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
    return { ready: false, model: null, message: "backend not reachable" };
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

// Drop empty optional fields so the backend sees "absent", not "".
export function cleanLlm(inp: LlmInput): LlmInput {
  const out: LlmInput = { provider: inp.provider, model: inp.model.trim() };
  if (inp.api_key?.trim()) out.api_key = inp.api_key.trim();
  if (inp.base_url?.trim()) out.base_url = inp.base_url.trim();
  return out;
}

export async function getSetupProviders(): Promise<LlmProvider[]> {
  const d = await json<{ providers: LlmProvider[] }>("/api/setup/llm-providers");
  return d?.providers ?? [];
}

export async function setupLlmTest(inp: LlmInput, setupToken?: string): Promise<LlmTestResult> {
  return json("/api/setup/llm-test", {
    method: "POST",
    body: { ...cleanLlm(inp), ...(setupToken ? { setup_token: setupToken } : {}) },
  });
}

export async function setupLlmModels(inp: LlmInput, setupToken?: string): Promise<string[]> {
  const d = await json<{ models: string[] }>("/api/setup/llm-models", {
    method: "POST",
    body: { ...cleanLlm(inp), ...(setupToken ? { setup_token: setupToken } : {}) },
  });
  return d?.models ?? [];
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

export async function listSessions(): Promise<SessionSummary[]> {
  return json("/api/admin/sessions", admin);
}

export async function getSessionMessages(sid: string): Promise<StoredMessage[]> {
  return json(`/api/admin/sessions/${encodeURIComponent(sid)}/messages`, admin);
}

export async function getLog(limit = 100): Promise<LogEntry[]> {
  return json(`/api/admin/log?limit=${limit}`, admin);
}

// --- admin: AI provider -------------------------------------------------------

export interface LlmUpdate extends LlmInput {
  temperature?: number;
  max_tokens?: number;
}

export async function getLlm(): Promise<LlmConfigView> {
  return json("/api/admin/llm", admin);
}

export async function getAdminProviders(): Promise<LlmProvider[]> {
  const d = await json<{ providers: LlmProvider[] }>("/api/admin/llm/providers", admin);
  return d?.providers ?? [];
}

export async function saveLlm(u: LlmUpdate): Promise<LlmConfigView> {
  const body: LlmUpdate = cleanLlm(u);
  if (u.temperature !== undefined) body.temperature = u.temperature;
  if (u.max_tokens !== undefined) body.max_tokens = u.max_tokens;
  return json("/api/admin/llm", { method: "PUT", body, ...admin });
}

// No argument: test the saved config (and record the result).
export async function testLlm(inp?: LlmInput): Promise<LlmTestResult> {
  return json("/api/admin/llm/test", {
    method: "POST",
    ...(inp ? { body: cleanLlm(inp) } : {}),
    ...admin,
  });
}

export async function adminLlmModels(inp: LlmInput): Promise<string[]> {
  const d = await json<{ models: string[] }>("/api/admin/llm/models", {
    method: "POST",
    body: { ...cleanLlm(inp), model: inp.model || "-" },
    ...admin,
  });
  return d?.models ?? [];
}

// --- admin: structured profile -------------------------------------------------

// API section slugs (see backend mebot/profile/sections.py).
export type ProfileSection =
  | "links"
  | "experiences"
  | "educations"
  | "skills"
  | "projects"
  | "interests"
  | "faqs"
  | "avoid-topics";

export type ProfileItem = { id: string; sort_order: number } & Record<string, unknown>;
export type ProfileFields = Record<string, unknown>;

export interface ProfilePreview {
  text: string;
  chars: number;
  approx_tokens: number;
}

const P = "/api/admin/profile";

export async function listProfileItems(section: ProfileSection): Promise<ProfileItem[]> {
  const d = await json<{ items: ProfileItem[] }>(`${P}/${section}`, admin);
  return d?.items ?? [];
}

export async function createProfileItem(
  section: ProfileSection,
  body: ProfileFields,
): Promise<ProfileItem> {
  return json(`${P}/${section}`, { method: "POST", body, ...admin });
}

export async function updateProfileItem(
  section: ProfileSection,
  id: string,
  body: ProfileFields,
): Promise<ProfileItem> {
  return json(`${P}/${section}/${encodeURIComponent(id)}`, { method: "PUT", body, ...admin });
}

export async function deleteProfileItem(section: ProfileSection, id: string): Promise<void> {
  await send(`${P}/${section}/${encodeURIComponent(id)}`, { method: "DELETE", ...admin });
}

export async function reorderProfileItems(section: ProfileSection, ids: string[]): Promise<void> {
  await send(`${P}/${section}/order`, { method: "PUT", body: { ids }, ...admin });
}

export async function getIdentity(): Promise<ProfileFields> {
  return json(`${P}/identity`, admin);
}

export async function saveIdentity(body: ProfileFields): Promise<ProfileFields> {
  return json(`${P}/identity`, { method: "PUT", body, ...admin });
}

export async function getNotes(): Promise<string> {
  const d = await json<{ content: string }>(`${P}/notes`, admin);
  return d?.content ?? "";
}

export async function saveNotes(content: string): Promise<string> {
  const d = await json<{ content: string }>(`${P}/notes`, {
    method: "PUT",
    body: { content },
    ...admin,
  });
  return d?.content ?? "";
}

export async function getProfilePreview(): Promise<ProfilePreview> {
  return json(`${P}/preview`, admin);
}

// --- admin: computed facts & unanswered questions ---------------------------------------

export interface FactsDuration {
  months: number;
  text: string;
  years: number;
}

export interface ProfileFacts {
  as_of: string;
  total_experience:
    | (FactsDuration & {
        from: string | null;
        to: string | null;
        internships_counted: boolean;
        freelance_counted: boolean;
      })
    | null;
  internship_months: number;
  current_roles: { company: string; title: string; since: string; months: number; text: string }[];
  upcoming_roles: { company: string; title: string; starts: string }[];
  last_role_end: string | null;
  first_job_start: string | null;
  skills: {
    name: string;
    months: number | null;
    text: string | null;
    years: number | null;
    source: "computed" | "stated" | null;
    evidence: string[];
  }[];
  education: {
    latest: {
      degree: string;
      field: string | null;
      institution: string;
      end_month: string | null;
      in_progress: boolean;
    } | null;
  };
  counts: { projects: number; projects_by_status: Record<string, number>; companies: number };
}

export interface UnansweredItem {
  session_id: string | null;
  question: string | null;
  created_at: string;
}

export async function getProfileFacts(): Promise<ProfileFacts> {
  return json(`${P}/facts`, admin);
}

export async function getUnanswered(limit = 10): Promise<UnansweredItem[]> {
  const d = await json<{ items: UnansweredItem[] }>(`/api/admin/unanswered?limit=${limit}`, admin);
  return d?.items ?? [];
}

// --- limits + usage (Feature 6) ------------------------------------------------

export interface Limits {
  per_ip_per_minute: number;
  per_ip_per_day: number;
  per_session_messages: number;
  sessions_per_ip_per_hour: number;
  daily_message_cap: number;
  daily_token_cap: number | null;
  max_message_chars: number;
  history_turns: number;
  paused: boolean;
  paused_message: string | null;
  turnstile_enabled: boolean;
}

export interface LimitsView extends Limits {
  turnstile_available: boolean;
}

export interface UsageDay {
  date: string;
  messages: number;
  tokens: number;
  tokens_estimated: boolean;
  rate_limited: number;
  leak_blocked: number;
}

export interface Usage {
  days: UsageDay[];
  top_visitors: { ip_hash: string; messages: number }[];
}

export interface PublicConfig {
  turnstile_site_key: string | null;
  max_message_chars: number;
  paused: boolean;
}

export async function getLimits(): Promise<LimitsView> {
  return json<LimitsView>("/api/admin/limits", admin);
}

export async function saveLimits(body: Partial<Limits>): Promise<LimitsView> {
  return json<LimitsView>("/api/admin/limits", { method: "PUT", body, ...admin });
}

export async function getUsage(days = 7): Promise<Usage> {
  return json<Usage>(`/api/admin/usage?days=${days}`, admin);
}

export async function getPublicConfig(): Promise<PublicConfig> {
  return json<PublicConfig>("/api/public/config");
}
