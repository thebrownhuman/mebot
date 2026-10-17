import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import pkg from "./package.json";

// Backend-served paths (embed page, loader, test page) and the backend's own static
// mounts, proxied in dev so http://localhost:5173 behaves like nginx in production.
const backend = { target: "http://localhost:8000", changeOrigin: true };

export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  build: {
    rollupOptions: {
      // index.html is the app; the embed bundle is a JS entry that the backend's
      // /embed/{slug} page loads from a fixed path (that page sets per-site CSP headers).
      input: { index: "index.html", embed: "src/embed/main.tsx" },
      output: {
        entryFileNames: (chunk) => (chunk.name === "embed" ? "embed-app/embed.js" : "assets/[name]-[hash].js"),
        assetFileNames: (asset) =>
          asset.name === "embed.css" ? "embed-app/embed.css" : "assets/[name]-[hash][extname]",
      },
    },
  },
  server: {
    port: 5173,
    // Proxy API calls to the FastAPI backend so the frontend can use
    // same-origin "/api/..." paths and avoid CORS entirely in dev.
    proxy: {
      "/api": backend,
      "/embed/": backend,
      "/widget": backend,
      "/widget-test": backend,
    },
  },
});
