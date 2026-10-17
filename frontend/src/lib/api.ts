// Typed client for the FastAPI backend. All paths are same-origin "/api/..."
// because Vite proxies them to http://localhost:8000 in dev.
//
// Auth is a server-side session in an HttpOnly cookie. Mutating requests echo the
// readable `mebot_csrf` cookie in X-CSRF-Token (double-submit). A 401 from an admin
// call fires UNAUTHORIZED_EVENT so the admin guard can send the user to the login page.

import type { PublicChannel } from "./channels";

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

export interface StoredMessage {
  role: "user" | "assistant";
  content: string;
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
    // Seconds from the Retry-After header (rate limits), when present.
    public retryAfter: number | null = null,
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
  const retry = Number(r.headers.get("Retry-After"));
  return new ApiError(
    r.status,
    err?.code ?? "HTTP_ERROR",
    message,
    err?.details ?? [],
    Number.isFinite(retry) && retry > 0 ? retry : null,
  );
}

interface ReqOpts {
  method?: string;
  body?: unknown;
  // Admin calls broadcast 401s; login/me handle 401 themselves.
  notifyUnauthorized?: boolean;
}

// --- hosted mode: which bot a public call is for ----------------------------
// A recruiter page at /b/{slug} (or an embed at /embed/pk_...) talks to the backend
// under the same /b/{ref} prefix, which picks the tenant. Owner APIs never get it.
const TENANT_API = ["/api/public", "/api/session", "/api/chat", "/api/contact", "/api/health"];

export function tenantPrefix(pathname: string): string {
  const b = /^\/b\/([^/]+)/.exec(pathname);
  if (b) return `/b/${b[1]}`;
  const e = /^\/embed\/(pk_[^/]+)/.exec(pathname);
  return e ? `/b/${e[1]}` : "";
}

export function withTenant(path: string, pathname: string): string {
  const prefix = tenantPrefix(pathname);
  return prefix && TENANT_API.some((p) => path.startsWith(p)) ? prefix + path : path;
}

async function send(
  path: string,
  { method = "GET", body, notifyUnauthorized = false }: ReqOpts = {},
) {
  path = withTenant(path, window.location.pathname);
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
    const r = await fetch(withTenant("/api/health", window.location.pathname));
    return (await r.json()) as HealthResp;
  } catch {
    return { ready: false, model: null, message: "backend not reachable" };
  }
}

export async function startSession(
  recruiterName?: string,
  turnstileToken?: string,
): Promise<string> {
  const body: Record<string, string | null> = { recruiter_name: recruiterName ?? null };
  if (turnstileToken) body.turnstile_token = turnstileToken;
  const d = await json<{ session_id: string }>("/api/session", { method: "POST", body });
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

export async function getSetupStatus(): Promise<{
  setup_required: boolean;
  mode?: "hosted";
}> {
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

// Deprecated endpoint, still used by the chat hook's loadSession.
export async function getSessionMessages(sid: string): Promise<StoredMessage[]> {
  return json(`/api/admin/sessions/${encodeURIComponent(sid)}/messages`, admin);
}

// --- admin: dashboard, conversations, account ----------------------------------

export type RangeKey = "7d" | "30d" | "90d";

export interface Kpi {
  value: number | null;
  previous: number | null;
  estimated?: boolean;
}

export interface SeriesDay {
  date: string;
  chats: number;
  visitor_messages: number;
  unanswered: number;
}

export interface Overview {
  range: { key: RangeKey; from: string; to: string; timezone: string };
  kpis: {
    chats: Kpi;
    visitor_messages: Kpi;
    avg_messages_per_chat: Kpi;
    unanswered_rate: Kpi;
    open_questions: Kpi;
    contacts: Kpi;
    owner_replies: Kpi;
    tokens: Kpi;
  };
  series: SeriesDay[];
  top_questions: { question: string; count: number }[];
  sources: { origin: string; chats: number }[];
  status: {
    llm: { configured: boolean; ok: boolean; last_tested_at: string | null };
    telegram: { linked: boolean; dead: number };
    widget: { enabled: boolean; origins: number; any_origin: boolean };
    paused: boolean;
    today: { messages: number; cap: number; tokens: number; token_cap: number | null };
  };
}

export async function getOverview(range: RangeKey): Promise<Overview> {
  return json(`/api/admin/analytics/overview?range=${range}`, admin);
}

export type ConversationFlag =
  | "unanswered"
  | "contact"
  | "owner_reply"
  | "leak_blocked"
  | "redacted";

export interface ConversationFilters {
  range?: RangeKey | "";
  from?: string;
  to?: string;
  q?: string;
  has?: string[];
  origin?: string;
}

export interface ConversationItem {
  id: string;
  recruiter_name: string | null;
  started_at: string;
  last_message_at: string;
  messages: number;
  origin: string;
  flags: ConversationFlag[];
  preview: string;
}

export interface ConversationMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
  unanswered: boolean;
  from_owner: boolean;
  // Retrieval mode only: the profile chunks the model saw for this reply.
  chunks?: { id: string; section: string; title: string }[];
}

export interface ConversationDetail {
  id: string;
  recruiter_name: string | null;
  started_at: string;
  origin: string;
  messages: ConversationMessage[];
  events: { event: string; created_at: string; detail?: string }[];
  contact: {
    id: string;
    name: string;
    email: string;
    company: string | null;
    role: string | null;
    note: string | null;
    created_at: string;
  } | null;
}

export function conversationQuery(f: ConversationFilters): string {
  const p = new URLSearchParams();
  if (f.from || f.to) {
    if (f.from) p.set("from", f.from);
    if (f.to) p.set("to", f.to);
  } else if (f.range) {
    p.set("range", f.range);
  }
  if (f.q?.trim()) p.set("q", f.q.trim());
  if (f.has?.length) p.set("has", f.has.join(","));
  if (f.origin) p.set("origin", f.origin);
  return p.toString();
}

export async function listConversations(
  f: ConversationFilters,
  cursor?: string | null,
): Promise<{ items: ConversationItem[]; next_cursor: string | null }> {
  const qs = conversationQuery(f);
  const extra = cursor ? `cursor=${encodeURIComponent(cursor)}` : "";
  const query = [qs, extra].filter(Boolean).join("&");
  return json(`/api/admin/conversations${query ? `?${query}` : ""}`, admin);
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  return json(`/api/admin/conversations/${encodeURIComponent(id)}`, admin);
}

export async function deleteConversation(id: string): Promise<void> {
  await send(`/api/admin/conversations/${encodeURIComponent(id)}`, { method: "DELETE", ...admin });
}

// A plain link: the session cookie authenticates the download and the browser saves it.
export function conversationExportUrl(f: ConversationFilters, format: "csv" | "json"): string {
  const qs = conversationQuery(f);
  return `/api/admin/conversations/export?format=${format}${qs ? `&${qs}` : ""}`;
}

export interface AccountSettings {
  timezone: string;
  retention_days: number | null;
  retention_choices: number[];
  will_delete?: number;
}

export async function getAccount(previewDays?: number): Promise<AccountSettings> {
  const q = previewDays === undefined ? "" : `?preview_days=${previewDays}`;
  return json(`/api/admin/account${q}`, admin);
}

export async function saveAccount(body: {
  timezone?: string;
  retention_days?: number | null;
}): Promise<AccountSettings> {
  return json("/api/admin/account", { method: "PUT", body, ...admin });
}

export async function deleteAllConversations(confirm: string): Promise<{ deleted_sessions: number }> {
  return json("/api/admin/account/delete-conversations", {
    method: "POST",
    body: { confirm },
    ...admin,
  });
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
  // Approved learned facts in the prompt, and size warnings from the server.
  learned_facts?: number;
  warnings?: string[];
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

// --- admin: computed facts ---------------------------------------

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

export async function getProfileFacts(): Promise<ProfileFacts> {
  return json(`${P}/facts`, admin);
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
  // Identity full name (or bot name); shown to recruiters.
  owner_name?: string;
  // The assistant's first chat bubble (rendered by the server, not an AI call).
  assistant_greeting?: string;
  // Chips shown before the first message (admin Widget page).
  suggested_questions?: string[];
}

// --- admin: knowledge (retrieval for large profiles) ---------------------------

export type KnowledgeMode = "auto" | "always" | "off";

export interface KnowledgeStatus {
  mode: KnowledgeMode;
  effective: "full" | "retrieval";
  reason: string;
  profile_tokens: number;
  threshold_tokens: number;
  budget_tokens: number;
  chunk_count: number;
  last_indexed_at: string | null;
  index_stale: boolean;
  usage: {
    days: number;
    questions: number;
    retrieval_replies: number;
    avg_prompt_tokens: number;
    avg_profile_tokens: number;
    saved_percent: number;
  };
  embeddings: {
    supported: boolean;
    reason: string | null;
    enabled: boolean;
    model: string | null;
    default_model: string | null;
    embedded: number;
    total: number;
    last_error: string | null;
  };
}

export interface KnowledgeUpdate {
  mode?: KnowledgeMode;
  embeddings_enabled?: boolean;
  embedding_model?: string | null;
}

export async function getKnowledge(): Promise<KnowledgeStatus> {
  return json<KnowledgeStatus>("/api/admin/knowledge", admin);
}

export async function saveKnowledge(body: KnowledgeUpdate): Promise<KnowledgeStatus> {
  return json<KnowledgeStatus>("/api/admin/knowledge", { method: "PUT", body, ...admin });
}

export async function rebuildKnowledge(): Promise<KnowledgeStatus> {
  return json<KnowledgeStatus>("/api/admin/knowledge/rebuild", { method: "POST", ...admin });
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


// --- Telegram notifications (Feature 7) -------------------------------------------

export interface TelegramToggles {
  notify_new_session: boolean;
  notify_every_question: boolean;
  notify_unanswered: boolean;
  notify_contact: boolean;
  notify_limits: boolean;
  daily_digest: boolean;
}

export type TelegramMode = "polling" | "webhook";

export interface TelegramSettings extends TelegramToggles {
  digest_hour: number;
  timezone: string;
  mode: TelegramMode;
}

export interface TelegramView extends TelegramSettings {
  configured: boolean;
  linked: boolean;
  bot_username: string | null;
  bot_token_last4: string | null;
  webhook_available: boolean;
  error: string | null;
  outbox: { pending: number; failed: number; dead: number; last_sent_at: string | null };
}

const TG = "/api/admin/telegram";

export async function getTelegram(): Promise<TelegramView> {
  return json<TelegramView>(TG, admin);
}

export async function saveTelegramToken(botToken: string): Promise<TelegramView> {
  return json<TelegramView>(TG, { method: "PUT", body: { bot_token: botToken.trim() }, ...admin });
}

export async function patchTelegram(body: Partial<TelegramSettings>): Promise<TelegramView> {
  return json<TelegramView>(TG, { method: "PATCH", body, ...admin });
}

export async function createTelegramLink(): Promise<{ deep_link: string; expires_at: string }> {
  return json(`${TG}/link`, { method: "POST", ...admin });
}

export async function sendTelegramTest(): Promise<void> {
  await send(`${TG}/test`, { method: "POST", ...admin });
}

export async function unlinkTelegram(): Promise<void> {
  await send(TG, { method: "DELETE", ...admin });
}

// --- contacts (Feature 7, req 9) -----------------------------------------------------

export interface ContactIn {
  session_id?: string | null;
  name: string;
  email: string;
  company?: string;
  role?: string;
  note?: string;
  // Honeypot: always empty from real visitors.
  website?: string;
}

export interface ContactItem {
  id: string;
  session_id: string | null;
  name: string;
  email: string;
  company: string | null;
  role: string | null;
  note: string | null;
  created_at: string;
}

export async function leaveContact(body: ContactIn): Promise<void> {
  await send("/api/contact", { method: "POST", body });
}

export async function listContacts(): Promise<ContactItem[]> {
  const d = await json<{ items: ContactItem[] }>("/api/admin/contacts", admin);
  return d?.items ?? [];
}

export async function deleteContact(id: string): Promise<void> {
  await send(`/api/admin/contacts/${encodeURIComponent(id)}`, { method: "DELETE", ...admin });
}

// --- owner replies (Feature 7, req 7) -------------------------------------------------

export interface OwnerMessage {
  role: "assistant";
  from_owner: true;
  content: string;
  created_at: string;
}

export interface SessionUpdates {
  messages: OwnerMessage[];
  // The bot's latest reply in this session couldn't answer the question.
  unanswered: boolean;
}

export async function getSessionUpdates(sid: string, after?: string | null): Promise<SessionUpdates> {
  const q = after ? `?after=${encodeURIComponent(after)}` : "";
  const d = await json<Partial<SessionUpdates>>(
    `/api/session/${encodeURIComponent(sid)}/updates${q}`,
  );
  return { messages: d?.messages ?? [], unanswered: Boolean(d?.unanswered) };
}

// --- learning loop (Feature 7b) -------------------------------------------------------

export type OpenQuestionStatus = "open" | "answered" | "dismissed" | "never";

export interface OpenQuestion {
  id: string;
  question: string;
  ask_count: number;
  first_asked_at: string;
  last_asked_at: string;
  status: OpenQuestionStatus;
  answered_fact_id: string | null;
}

export interface OpenQuestionList {
  items: OpenQuestion[];
  // Open questions in total (drives the sidebar badge).
  open_count: number;
}

export type FactStatus = "pending" | "approved" | "rejected";

export interface LearnedFact {
  id: string;
  open_question_id: string | null;
  question: string;
  answer_raw: string;
  fact_text: string;
  status: FactStatus;
  source: "admin" | "telegram";
  suggested_section: "identity" | "learned";
  suggested_field: string | null;
  suggested_value: string | null;
  // What the identity field holds right now (when the suggestion targets one).
  current_value: string | null;
  // The AI wording could not be verified, so the fact stays close to the owner's words.
  needs_review: boolean;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LearnedFactList {
  items: LearnedFact[];
  active_count: number;
  max_active: number;
}

export type ApproveMode = "replace" | "keep_both";

export interface FactEdit {
  fact_text?: string;
  field?: string | null;
  value?: string | null;
}

const OQ = "/api/admin/open-questions";
const LF = "/api/admin/learned-facts";

export async function listOpenQuestions(status: OpenQuestionStatus | "all" = "open") {
  const d = await json<Partial<OpenQuestionList>>(`${OQ}?status=${status}`, admin);
  return { items: d?.items ?? [], open_count: d?.open_count ?? 0 } as OpenQuestionList;
}

export async function answerOpenQuestion(id: string, answer: string): Promise<LearnedFact> {
  return json(`${OQ}/${encodeURIComponent(id)}/answer`, {
    method: "POST",
    body: { answer },
    ...admin,
  });
}

export async function dismissOpenQuestion(id: string): Promise<OpenQuestion> {
  return json(`${OQ}/${encodeURIComponent(id)}/dismiss`, { method: "POST", ...admin });
}

export async function neverAnswerOpenQuestion(id: string): Promise<OpenQuestion> {
  return json(`${OQ}/${encodeURIComponent(id)}/never`, { method: "POST", ...admin });
}

export async function listLearnedFacts(status?: FactStatus): Promise<LearnedFactList> {
  const d = await json<Partial<LearnedFactList>>(`${LF}${status ? `?status=${status}` : ""}`, admin);
  return {
    items: d?.items ?? [],
    active_count: d?.active_count ?? 0,
    max_active: d?.max_active ?? 200,
  };
}

export async function addLearnedFact(text: string): Promise<LearnedFact> {
  return json(LF, { method: "POST", body: { text }, ...admin });
}

export async function approveLearnedFact(
  id: string,
  opts: FactEdit & { mode?: ApproveMode } = {},
): Promise<LearnedFact> {
  return json(`${LF}/${encodeURIComponent(id)}/approve`, { method: "POST", body: opts, ...admin });
}

export async function rejectLearnedFact(id: string): Promise<LearnedFact> {
  return json(`${LF}/${encodeURIComponent(id)}/reject`, { method: "POST", ...admin });
}

export async function updateLearnedFact(id: string, edit: FactEdit): Promise<LearnedFact> {
  return json(`${LF}/${encodeURIComponent(id)}`, { method: "PUT", body: edit, ...admin });
}

export async function deleteLearnedFact(id: string): Promise<void> {
  await send(`${LF}/${encodeURIComponent(id)}`, { method: "DELETE", ...admin });
}

// --- contact channels (recruiter side) --------------------------------------------

export async function getContactChannels(): Promise<PublicChannel[]> {
  const d = await json<{ items: PublicChannel[] }>("/api/public/contact-channels");
  return d?.items ?? [];
}

// --- widget ------------------------------------------------------------------

export interface WidgetConfig {
  title: string;
  primary_color: string;
  theme: "light" | "dark" | "auto";
  position: "right" | "left";
  avatar_url: string | null;
  launcher_label: string | null;
  greeting: string;
  suggested_questions: string[];
  show_orb: boolean;
  auto_open_seconds: number | null;
  max_message_chars: number;
  turnstile_site_key: string | null;
  owner_first_name: string;
  paused: boolean;
}

export async function getWidgetConfig(slug: string): Promise<WidgetConfig> {
  return json(`/api/public/widget/${encodeURIComponent(slug)}`);
}

// WIDGET_OPENED analytics; the server keeps the origin only if it is an allowed site.
export async function widgetOpened(slug: string, sessionId: string | null, origin: string) {
  await send(`/api/public/widget/${encodeURIComponent(slug)}/opened`, {
    method: "POST",
    body: { session_id: sessionId, origin },
  });
}

export interface WidgetSettings {
  slug: string;
  enabled: boolean;
  allowed_origins: string[];
  allow_any_origin: boolean;
  primary_color: string;
  theme: "light" | "dark" | "auto";
  position: "right" | "left";
  title: string | null;
  avatar_url: string | null;
  launcher_label: string | null;
  suggested_questions: string[];
  show_orb: boolean;
  auto_open_seconds: number | null;
  // Widget on, but no allowed sites: only this install's own pages can show it.
  needs_origins: boolean;
}

export type WidgetUpdate = Partial<Omit<WidgetSettings, "slug" | "needs_origins">> & {
  confirm_any_origin?: boolean;
};

export interface WidgetSnippets {
  script: string;
  inline: string;
  iframe: string;
}

export async function getWidgetSettings(): Promise<WidgetSettings> {
  return json("/api/admin/widget", admin);
}

export async function saveWidgetSettings(body: WidgetUpdate): Promise<WidgetSettings> {
  return json("/api/admin/widget", { method: "PUT", body, ...admin });
}

export async function getWidgetSnippets(): Promise<WidgetSnippets> {
  return json("/api/admin/widget/snippets", admin);
}

// --- imports -------------------------------------------------------------------

export type ImportKind = "resume" | "linkedin" | "github";
export type ImportStatus = "processing" | "ready" | "applied" | "failed" | "expired";
export type ImportAction = "add" | "update" | "skip";

export interface DraftEntry {
  temp_id: string;
  data: Record<string, unknown>;
  match: {
    status: "new" | "same" | "changed";
    existing_id?: string;
    diff?: Record<string, { from: unknown; to: unknown }>;
  };
  needs_review: boolean;
  reason?: string;
  kind?: string;
  snippet?: string;
  // GitHub: which file detected each tech.
  evidence?: { tech: string; file: string; key?: string }[];
  default_action: ImportAction;
}

export type ImportSummary = Record<string, { added: number; updated: number }>;

export interface ImportJobSummary {
  id: string;
  kind: ImportKind;
  status: ImportStatus;
  filename: string | null;
  size_bytes: number | null;
  error_code: string | null;
  error_message: string | null;
  applied_summary: ImportSummary | null;
  created_at: string;
  expires_at: string;
}

export interface ImportJob extends ImportJobSummary {
  draft: {
    sections: Record<string, DraftEntry[]>;
    // Parts that failed on their own (e.g. one repo of several).
    errors?: { source: string; code: string; message: string }[];
  } | null;
  source_text: string | null;
}

export interface ImportDecision {
  temp_id: string;
  action: ImportAction;
  data?: Record<string, unknown>;
}

const IMP = "/api/admin/import";

// XHR rather than fetch: fetch can't report upload progress.
export function uploadImport(
  kind: ImportKind,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<ImportJobSummary | { id: string; status: ImportStatus }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${IMP}/${kind}`);
    xhr.withCredentials = true;
    const token = readCookie(CSRF_COOKIE);
    if (token) xhr.setRequestHeader("X-CSRF-Token", token);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded / e.total);
    };
    xhr.onerror = () => reject(new ApiError(0, "NETWORK", "Upload failed. Check your connection."));
    xhr.onload = async () => {
      const headers = new Headers({ "Content-Type": "application/json" });
      const ra = xhr.getResponseHeader("Retry-After");
      if (ra) headers.set("Retry-After", ra);
      const r = new Response(xhr.responseText || null, { status: xhr.status, headers });
      if (xhr.status >= 200 && xhr.status < 300) resolve(await r.json());
      else {
        if (xhr.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
        reject(await toApiError(r));
      }
    };
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export async function listImportJobs(): Promise<ImportJobSummary[]> {
  const d = await json<{ items: ImportJobSummary[] }>(`${IMP}/jobs`, admin);
  return d?.items ?? [];
}

export async function getImportJob(id: string): Promise<ImportJob> {
  return json(`${IMP}/jobs/${encodeURIComponent(id)}`, admin);
}

export async function applyImport(id: string, decisions: ImportDecision[]): Promise<ImportSummary> {
  const d = await json<{ applied: ImportSummary }>(`${IMP}/jobs/${encodeURIComponent(id)}/apply`, {
    method: "POST",
    body: { decisions },
    ...admin,
  });
  return d?.applied ?? {};
}

export async function discardImport(id: string): Promise<void> {
  await send(`${IMP}/jobs/${encodeURIComponent(id)}`, { method: "DELETE", ...admin });
}

// --- GitHub import -------------------------------------------------------------

export interface GithubRepo {
  name: string;
  full_name: string;
  description: string | null;
  language: string | null;
  stars: number;
  pushed_at: string | null;
  fork: boolean;
  archived: boolean;
  html_url: string;
}

export interface GithubTokenView {
  configured: boolean;
  token_last4: string | null;
  env_token: boolean;
}

export async function startGithubImport(repoUrls: string[]): Promise<{ id: string; status: ImportStatus }> {
  return json(`${IMP}/github`, { method: "POST", body: { repo_urls: repoUrls }, ...admin });
}

export async function listGithubRepos(username: string, includeForks = false): Promise<GithubRepo[]> {
  const q = new URLSearchParams({ username, include_forks: String(includeForks) });
  const d = await json<{ items: GithubRepo[] }>(`${IMP}/github/repos?${q}`, admin);
  return d?.items ?? [];
}

const GH_TOKEN = "/api/admin/integrations/github";

export async function getGithubToken(): Promise<GithubTokenView> {
  return json(GH_TOKEN, admin);
}

export async function saveGithubToken(token: string): Promise<GithubTokenView> {
  return json(GH_TOKEN, { method: "PUT", body: { token }, ...admin });
}

export async function deleteGithubToken(): Promise<void> {
  await send(GH_TOKEN, { method: "DELETE", ...admin });
}

// --- admin: mebot project (install registry) -------------------------------------

export type TelemetryStatus =
  | "off"
  | "unavailable"
  | "not_registered"
  | "waiting_for_public_url"
  | "pending"
  | "registered"
  | "unregister_pending";

export interface HeartbeatPayload {
  install_id: string;
  public_key: string;
  version: string;
  mode: string;
}

export interface TelemetryView {
  telemetry: "on" | "off";
  registry_url: string;
  consent: boolean;
  status: TelemetryStatus;
  registered_at: string | null;
  last_register_error: string | null;
  install_id_prefix: string | null;
  update_contact_email: string | null;
  effective_email: string | null;
  public_url: string | null;
  last_heartbeat: { sent_at: string; payload: HeartbeatPayload } | null;
  payload_preview: HeartbeatPayload | null;
  last_check_at: string | null;
  update: {
    current: string;
    latest: string | null;
    available: boolean;
    dismissed: boolean;
    unsupported: boolean;
    advisory: { id: string; severity: string; title: string; url: string | null } | null;
  };
}

export async function getTelemetry(): Promise<TelemetryView> {
  return json("/api/admin/telemetry", admin);
}

export async function saveTelemetry(body: {
  consent?: boolean;
  update_contact_email?: string | null;
}): Promise<TelemetryView> {
  return json("/api/admin/telemetry", { method: "PUT", body, ...admin });
}

export async function dismissUpdate(version: string): Promise<void> {
  await send("/api/admin/telemetry/dismiss-update", { method: "POST", body: { version }, ...admin });
}

// --- hosted mode: accounts ----------------------------------------------------

export interface HostedConfig {
  signup_mode: "open" | "invite" | "closed";
  turnstile_site_key: string | null;
  hosted_domain: string | null;
}

export interface SignupReq {
  email: string;
  password: string;
  bot_name: string;
  slug: string;
  invite_code?: string;
  turnstile_token?: string;
}

export interface HostedAccount {
  email: string;
  email_verified: boolean;
  bot_name: string;
  slug: string;
  public_key: string;
  plan: string;
  setup_done: boolean;
  live: boolean;
  public_path: string;
  hosted_domain: string | null;
}

export interface HostedSetupReq {
  bot_name: string;
  full_name?: string;
  headline?: string;
  llm: LlmInput;
}

const H = "/api/hosted";

export async function getHostedConfig(): Promise<HostedConfig> {
  return json(`${H}/config`);
}

export async function signup(req: SignupReq): Promise<{ approval_required?: boolean }> {
  return json(`${H}/signup`, { method: "POST", body: req });
}

export async function verifyEmail(token: string): Promise<void> {
  await send(`${H}/verify`, { method: "POST", body: { token } });
}

export async function resendVerification(email: string): Promise<void> {
  await send(`${H}/verify/resend`, { method: "POST", body: { email } });
}

export async function requestPasswordReset(email: string): Promise<void> {
  await send(`${H}/password-reset`, { method: "POST", body: { email } });
}

export async function confirmPasswordReset(token: string, newPassword: string): Promise<void> {
  await send(`${H}/password-reset/confirm`, {
    method: "POST",
    body: { token, new_password: newPassword },
  });
}

export async function getHostedAccount(): Promise<HostedAccount> {
  return json(`${H}/account`, admin);
}

export async function hostedSetup(req: HostedSetupReq): Promise<HostedAccount> {
  return json(`${H}/account/setup`, { method: "POST", body: req, ...admin });
}

export async function changeSlug(slug: string): Promise<HostedAccount> {
  return json(`${H}/account/slug`, { method: "PUT", body: { slug }, ...admin });
}

export const hostedExportUrl = `${H}/account/export`;

export async function deleteHostedAccount(password: string): Promise<void> {
  await send(`${H}/account/delete`, { method: "POST", body: { password }, ...admin });
}

// --- hosted mode: platform operator ---------------------------------------------

export interface PlatformTenant {
  id: string;
  slug: string;
  owner_email: string | null;
  email_verified: boolean;
  created_at: string;
  status: "active" | "suspended" | "deleted" | "pending";
  status_reason: string | null;
  plan: string;
  setup_done: boolean;
  messages_7d: number;
  messages_30d: number;
  tokens_30d: number;
  last_active_at: string | null;
  deletion_requested_at: string | null;
}

export interface PlatformInvite {
  id: string;
  note: string | null;
  created_at: string;
  expires_at: string | null;
  used_at: string | null;
}

export interface PlatformAuditEntry {
  at: string;
  actor: string | null;
  action: string;
  tenant: string | null;
  detail: string | null;
}

const P_ = "/api/platform";

export async function platformLogin(email: string, password: string): Promise<void> {
  await send(`${P_}/auth/login`, { method: "POST", body: { email, password } });
}

export async function platformLogout(): Promise<void> {
  await send(`${P_}/auth/logout`, { method: "POST" });
}

export async function platformMe(): Promise<{ email: string }> {
  return json(`${P_}/auth/me`);
}

export async function platformTenants(): Promise<PlatformTenant[]> {
  return (await json<{ items: PlatformTenant[] }>(`${P_}/tenants`)).items;
}

export async function platformSignups(): Promise<PlatformTenant[]> {
  return (await json<{ items: PlatformTenant[] }>(`${P_}/signups`)).items;
}

export type TenantAction = "approve" | "suspend" | "unsuspend" | "delete" | "resend-verification";

export async function platformTenantAction(
  id: string,
  action: TenantAction,
  reason?: string,
): Promise<void> {
  await send(`${P_}/tenants/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    body: reason === undefined ? undefined : { reason },
  });
}

export async function platformInvites(): Promise<PlatformInvite[]> {
  return (await json<{ items: PlatformInvite[] }>(`${P_}/invites`)).items;
}

export async function platformCreateInvite(note: string, days: number): Promise<string> {
  const d = await json<{ code: string }>(`${P_}/invites`, {
    method: "POST",
    body: { note: note || null, days },
  });
  return d.code;
}

export async function platformRevokeInvite(id: string): Promise<void> {
  await send(`${P_}/invites/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function platformAudit(): Promise<PlatformAuditEntry[]> {
  return (await json<{ items: PlatformAuditEntry[] }>(`${P_}/audit`)).items;
}
