// Bundle budgets for the widget (run by `npm test`, after `npm run build`):
//   loader  dist/widget/v1.js                          <= 8 KB gzipped
//   embed   dist/embed-app/embed.js + static imports   <= 150 KB gzipped (the lazy orb chunk excluded)
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, posix, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const DIST = join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const KB = 1024;
const BUDGETS = { loader: 8 * KB, embed: 150 * KB };

const gz = (file) => gzipSync(readFileSync(file), { level: 9 }).length;

// Static `import … from "x"` / `import "x"` only; dynamic import("x") stays lazy.
const STATIC = /(?:^|[;}\s])import\s*(?:[\w$\s{},*]+?\s*from\s*)?["']([^"']+\.js)["']/g;

export function staticGraph(entry) {
  const seen = new Set();
  const walk = (file) => {
    if (seen.has(file)) return;
    seen.add(file);
    const src = readFileSync(file, "utf8");
    for (const m of src.matchAll(STATIC)) {
      const spec = m[1];
      const next = spec.startsWith("/") ? join(DIST, spec) : join(dirname(file), spec);
      if (existsSync(next)) walk(next);
    }
  };
  walk(entry);
  return [...seen];
}

function main() {
  const loader = join(DIST, "widget", "v1.js");
  const embed = join(DIST, "embed-app", "embed.js");
  for (const f of [loader, embed]) {
    if (!existsSync(f)) {
      console.error(`size check: ${relative(DIST, f)} missing; run npm run build first`);
      process.exit(1);
    }
  }
  const files = staticGraph(embed);
  const embedSize = files.reduce((n, f) => n + gz(f), 0);
  const rows = [
    ["loader", gz(loader), BUDGETS.loader, ["widget/v1.js"]],
    ["embed", embedSize, BUDGETS.embed, files.map((f) => relative(DIST, f).split("\\").join(posix.sep))],
  ];
  let ok = true;
  for (const [name, size, budget, parts] of rows) {
    const pass = size <= budget;
    ok &&= pass;
    console.log(
      `${pass ? "ok  " : "FAIL"} ${name}: ${(size / KB).toFixed(1)} KB gz / ${budget / KB} KB  (${parts.join(", ")})`,
    );
  }
  if (!ok) process.exit(1);
}

main();
