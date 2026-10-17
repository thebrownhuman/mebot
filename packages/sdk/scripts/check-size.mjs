// Size budget: the SDK core (CDN build, everything a page loads) <= 6 KB gzipped.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const DIST = join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const BUDGET = 6 * 1024;
let failed = false;
// The CDN file, and the npm core (index.js + the chunks it shares; React wrapper excluded).
const npm = readdirSync(DIST).filter((f) => f.endsWith(".js") && f !== "react.js");
const groups = { "cdn/mebot.js": ["cdn/mebot.js"], "npm core": npm };
for (const [file, parts] of Object.entries(groups)) {
  const size = gzipSync(Buffer.concat(parts.map((p) => readFileSync(join(DIST, p)))), { level: 9 }).length;
  const ok = size <= BUDGET;
  failed ||= !ok;
  console.log(`${ok ? "ok  " : "FAIL"} ${file}: ${(size / 1024).toFixed(1)} KB gz / 6 KB`);
}
process.exit(failed ? 1 : 0);
