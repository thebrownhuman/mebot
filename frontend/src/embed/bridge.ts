import { envelope, parseParent, type ChildType, type Envelope, type ParentType } from "../widget/protocol";

// The iframe side of the postMessage protocol. Messages carry no chat content or PII,
// so "*" as the target is safe; the host's origin is unknown until host-info arrives
// (and CSP frame-ancestors already limits who can frame us).

export function framed(): boolean {
  try {
    return window.parent !== window;
  } catch {
    return true;
  }
}

export function postToParent(type: ChildType, payload?: Record<string, unknown>) {
  if (!framed()) return;
  window.parent.postMessage(envelope(type, payload), "*");
}

// Only messages from our direct parent window with a valid envelope get through.
export function onParentMessage(fn: (m: Envelope<ParentType>) => void): () => void {
  function handler(e: MessageEvent) {
    if (e.source !== window.parent || e.source === window) return;
    const m = parseParent(e.data);
    if (m) fn(m);
  }
  window.addEventListener("message", handler);
  return () => window.removeEventListener("message", handler);
}
