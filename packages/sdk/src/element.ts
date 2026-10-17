// <mebot-chat bot-key="pk_…" theme="light|dark|auto" position="right" host="https://…">
// Theme via CSS variables on the element: --mebot-accent, --mebot-radius, --mebot-font,
// --mebot-launcher-size, --mebot-offset-x, --mebot-offset-y. Events: ready, open, close,
// message (CustomEvent, detail = {role} for message).

import { createMebot, type MebotEvent, type MebotInstance, type MebotOptions } from "./core";
import { themeFromCss } from "./theme";

const EVENTS: MebotEvent[] = ["ready", "open", "close", "message"];
let defaultHost: string | undefined;

export function setDefaultHost(h: string | undefined) {
  defaultHost = h;
}

export function defineElement(win: Window = window): void {
  const reg = win.customElements;
  if (!reg || reg.get("mebot-chat")) return;
  const Base = (win as unknown as { HTMLElement: typeof HTMLElement }).HTMLElement;

  class MebotChatElement extends Base {
    static get observedAttributes() {
      return ["bot-key", "theme", "position", "host"];
    }
    private inst: MebotInstance | null = null;

    connectedCallback() {
      this.start();
    }
    disconnectedCallback() {
      this.inst?.destroy();
      this.inst = null;
    }
    attributeChangedCallback() {
      if (this.inst) this.start();
    }
    open() {
      this.inst?.open();
    }
    close() {
      this.inst?.close();
    }
    toggle() {
      this.inst?.toggle();
    }

    private start() {
      this.inst?.destroy();
      this.inst = null;
      const key = this.getAttribute("bot-key");
      if (!key) return;
      const opts: MebotOptions = {
        botKey: key,
        ...themeFromCss(win.getComputedStyle(this)),
      };
      const theme = this.getAttribute("theme");
      if (theme) (opts as unknown as Record<string, unknown>).theme = theme;
      const pos = this.getAttribute("position");
      if (pos === "left" || pos === "right") opts.position = pos;
      const h = this.getAttribute("host");
      if (h) opts.host = h;
      try {
        this.inst = createMebot(opts, defaultHost, win);
      } catch (e) {
        console.warn(String(e instanceof Error ? e.message : e));
        return;
      }
      for (const ev of EVENTS) {
        this.inst.on(ev, (detail) => this.dispatchEvent(new CustomEvent(ev, { detail })));
      }
    }
  }
  reg.define("mebot-chat", MebotChatElement);
}
