import { defineConfig } from "vite";

// CDN build: one IIFE, served by the backend at /sdk/v1/mebot.js (and /sdk/<version>/).
export default defineConfig({
  build: {
    outDir: "dist/cdn",
    emptyOutDir: true,
    target: "es2018",
    lib: { entry: "src/cdn.ts", formats: ["iife"], name: "MebotSDK", fileName: () => "mebot.js" },
  },
});
