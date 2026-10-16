import { defineConfig } from "vite";

// The widget loader: one dependency-free ES2017 IIFE at dist/widget/v1.js.
// Runs after the app build (which empties dist/), so it must not empty it again.
export default defineConfig({
  publicDir: false,
  build: {
    emptyOutDir: false,
    outDir: "dist/widget",
    target: "es2017",
    lib: {
      entry: "src/widget/entry.ts",
      name: "MebotLoader",
      formats: ["iife"],
      fileName: () => "v1.js",
    },
  },
});
