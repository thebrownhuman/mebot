// Typed client for the FastAPI backend. All paths are same-origin "/api/..."
// because Vite proxies them to http://localhost:8000 in dev.

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

const J = { "Content-Type": "application/json" };

export async function getHealth(): Promise<HealthResp> {
  try {
    const r = await fetch("/api/health");
    return (await r.json()) as HealthResp;
  } catch (e) {
    return { ollama: false, model: null, message: "backend not reachable" };
  }
}

export async function getProfile(): Promise<string> {
  const r = await fetch("/api/profile");
  const d = (await r.json()) as { content: string };
  return d.content;
}

export async function saveProfile(content: string): Promise<void> {
  await fetch("/api/profile", { method: "PUT", headers: J, body: JSON.stringify({ content }) });
}

export async function startSession(recruiterName?: string): Promise<string> {
  const r = await fetch("/api/session", {
    method: "POST",
    headers: J,
    body: JSON.stringify({ recruiter_name: recruiterName ?? null }),
  });
  const d = (await r.json()) as { session_id: string };
  return d.session_id;
}

export async function listSessions(): Promise<SessionSummary[]> {
  const r = await fetch("/api/sessions");
  return (await r.json()) as SessionSummary[];
}

export async function getSessionMessages(sid: string): Promise<StoredMessage[]> {
  const r = await fetch(`/api/session/${sid}/messages`);
  return (await r.json()) as StoredMessage[];
}

export async function getLog(limit = 100): Promise<LogEntry[]> {
  const r = await fetch(`/api/log?limit=${limit}`);
  return (await r.json()) as LogEntry[];
}

// Streams the assistant reply. Calls onToken for each chunk; resolves when done.
export async function streamChat(
  sessionId: string,
  message: string,
  onToken: (chunk: string) => void,
): Promise<void> {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: J,
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    onToken(dec.decode(value, { stream: true }));
  }
}
