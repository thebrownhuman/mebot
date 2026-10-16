// The chat stream may end with one control frame: "\x1e" + {"type":"replace","content":"…"}
// (leak-block / channel redaction). The backend strips \x1e from model output, so
// everything after the first separator is the frame.
export const FRAME_SEP = "\x1e";

export interface StreamParts {
  // Text to show while streaming (never includes the frame).
  text: string;
  // Set once a complete replace frame has arrived.
  replace: string | null;
}

export function splitStream(acc: string): StreamParts {
  const i = acc.indexOf(FRAME_SEP);
  if (i < 0) return { text: acc, replace: null };
  const text = acc.slice(0, i);
  try {
    const frame = JSON.parse(acc.slice(i + 1)) as { type?: unknown; content?: unknown };
    if (frame?.type === "replace" && typeof frame.content === "string") {
      return { text, replace: frame.content };
    }
  } catch {
    // frame still arriving (or malformed): show the text before it
  }
  return { text, replace: null };
}
