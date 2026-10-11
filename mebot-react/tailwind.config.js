/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"SF Mono"', "ui-monospace", "DejaVu Sans Mono", "Menlo", "Consolas", "monospace"],
      },
      colors: {
        term: {
          bg: "#07090d",
          panel: "#0c1016",
          line: "#1b2530",
          line2: "#243140",
          fg: "#c8d6c5",
          dim: "#5d7065",
          bright: "#7dffb0",
          amber: "#ffcc66",
          recruiter: "#6fb4ff",
          err: "#ff6b6b",
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
