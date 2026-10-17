/// <reference types="vitest" />
import { defineConfig } from "vite";

// npm build: ESM entries (core + React wrapper). React stays a peer dependency.
export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2018",
    lib: {
      entry: { index: "src/index.ts", react: "src/react.tsx" },
      formats: ["es"],
    },
    rollupOptions: {
      external: ["react", "react/jsx-runtime"],
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
