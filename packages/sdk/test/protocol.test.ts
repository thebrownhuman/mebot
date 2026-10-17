import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// The SDK carries its own copy of the iframe protocol; it must stay identical to the
// widget's (frontend/src/widget/protocol.ts), which the embed iframe speaks.
it("protocol.ts matches the widget's copy", () => {
  const read = (p: string) => readFileSync(join(__dirname, p), "utf8").replace(/\r\n/g, "\n");
  expect(read("../src/protocol.ts")).toBe(read("../../../frontend/src/widget/protocol.ts"));
});
