// postMessage protocol between the loader (host page) and the embed iframe.
// Envelope: { source: "mebot", v: 1, type, payload }. Never chat content or PII.
// Shared by the loader bundle, so keep this file dependency-free and tiny.

export const SOURCE = "mebot";
export const VERSION = 1;

export type ChildType = "ready" | "resize" | "close" | "unread" | "message" | "open-link";
export type ParentType = "open" | "close" | "host-info";

export interface Envelope<T extends string = string> {
  source: typeof SOURCE;
  v: typeof VERSION;
  type: T;
  payload?: Record<string, unknown>;
}

const CHILD: readonly string[] = ["ready", "resize", "close", "unread", "message", "open-link"];
const PARENT: readonly string[] = ["open", "close", "host-info"];

export function envelope<T extends string>(type: T, payload?: Record<string, unknown>): Envelope<T> {
  return payload ? { source: SOURCE, v: VERSION, type, payload } : { source: SOURCE, v: VERSION, type };
}

function parse(data: unknown, allowed: readonly string[]): Envelope | null {
  if (!data || typeof data !== "object") return null;
  const d = data as Record<string, unknown>;
  if (d.source !== SOURCE || d.v !== VERSION || typeof d.type !== "string") return null;
  if (!allowed.includes(d.type)) return null;
  if (d.payload !== undefined && (typeof d.payload !== "object" || d.payload === null)) return null;
  return d as unknown as Envelope;
}

export const parseChild = (data: unknown) => parse(data, CHILD) as Envelope<ChildType> | null;
export const parseParent = (data: unknown) => parse(data, PARENT) as Envelope<ParentType> | null;

// Links the iframe asks the host page to open in a new tab: http(s) and mailto only.
export function safeLink(href: unknown): string | null {
  if (typeof href !== "string" || href.length > 2000) return null;
  try {
    const u = new URL(href);
    return u.protocol === "https:" || u.protocol === "http:" || u.protocol === "mailto:" ? u.href : null;
  } catch {
    return null;
  }
}
