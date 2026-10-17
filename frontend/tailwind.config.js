/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"SF Mono"', "ui-monospace", "DejaVu Sans Mono", "Menlo", "Consolas", "monospace"],
      },
      colors: {
        // Channels behind CSS vars so the embed can re-theme shared components (light widget).
        term: {
          bg: "rgb(var(--term-bg, 7 9 13) / <alpha-value>)",
          panel: "rgb(var(--term-panel, 12 16 22) / <alpha-value>)",
          line: "rgb(var(--term-line, 27 37 48) / <alpha-value>)",
          line2: "rgb(var(--term-line2, 36 49 64) / <alpha-value>)",
          fg: "rgb(var(--term-fg, 200 214 197) / <alpha-value>)",
          dim: "rgb(var(--term-dim, 93 112 101) / <alpha-value>)",
          bright: "rgb(var(--term-bright, 125 255 176) / <alpha-value>)",
          amber: "rgb(var(--term-amber, 255 204 102) / <alpha-value>)",
          recruiter: "rgb(var(--term-recruiter, 111 180 255) / <alpha-value>)",
          err: "rgb(var(--term-err, 255 107 107) / <alpha-value>)",
        },
      },
      keyframes: {
        blink: { "50%": { opacity: "0" } },
      },
      animation: {
        blink: "blink 1s steps(2) infinite",
      },
    },
  },
  plugins: [],
};
