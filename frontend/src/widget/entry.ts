// Built to dist/widget/v1.js (vite.loader.config.ts).
import { boot } from "./loader";

boot(
  (document.currentScript as HTMLScriptElement | null) ??
    document.querySelector<HTMLScriptElement>('script[data-bot][src*="/widget/v1.js"]'),
);
