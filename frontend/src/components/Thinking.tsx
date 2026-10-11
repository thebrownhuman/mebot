import { useEffect, useRef, useState } from "react";

// Mimics Claude Code's "✻ Thinking…" line: a spinner glyph, a cycling verb,
// and an elapsed-seconds counter. Shown while the model generates, replaced by
// the streamed answer once tokens arrive.

const GLYPHS = ["✶", "✸", "✹", "✺", "✹", "✷"];
const WORDS = [
  "Thinking",
  "Considering",
  "Recalling",
  "Composing",
  "Reflecting",
  "Gathering",
  "Phrasing",
];

export default function Thinking() {
  const [glyph, setGlyph] = useState(0);
  const [word, setWord] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const start = useRef(Date.now());

  useEffect(() => {
    const g = setInterval(() => setGlyph((i) => (i + 1) % GLYPHS.length), 120);
    const w = setInterval(() => setWord((i) => (i + 1) % WORDS.length), 1600);
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - start.current) / 1000)), 250);
    return () => {
      clearInterval(g);
      clearInterval(w);
      clearInterval(t);
    };
  }, []);

  return (
    <span className="text-term-amber">
      <span className="inline-block w-4">{GLYPHS[glyph]}</span> {WORDS[word]}…{" "}
      <span className="text-term-dim">({elapsed}s · esc to interrupt)</span>
    </span>
  );
}
