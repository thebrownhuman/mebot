// npm entry: `import { Mebot } from "@npm-scope/mebot"` (also registers <mebot-chat>).
import { createMebot, type MebotInstance, type MebotOptions } from "./core";
import { defineElement } from "./element";

export type { MebotEvent, MebotInstance, MebotOptions } from "./core";
export type { Font, Theme, ThemeMode } from "./theme";
export { defineElement };

export const Mebot = {
  init(opts: MebotOptions): MebotInstance {
    return createMebot(opts);
  },
};

if (typeof window !== "undefined") defineElement(window);
