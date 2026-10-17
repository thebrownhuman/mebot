import { readFileSync } from "node:fs";
import { defineConfig } from "vite";

const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as {
  version: string;
};

// CDN build: one IIFE, served by the backend at /sdk/v1/mebot.js (one-day cache) and
// /sdk/<version>/mebot.js (immutable). VERSION tells the backend which exact version it has.
export default defineConfig({
  build: {
    outDir: "dist/cdn",
    emptyOutDir: true,
    target: "es2018",
    lib: { entry: "src/cdn.ts", formats: ["iife"], name: "MebotSDK", fileName: () => "mebot.js" },
  },
  plugins: [
    {
      name: "mebot-version",
      generateBundle() {
        this.emitFile({ type: "asset", fileName: "VERSION", source: version + "\n" });
      },
    },
  ],
});
