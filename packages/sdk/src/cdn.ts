// CDN entry (/sdk/v1/mebot.js): window.Mebot.init({botKey}) and <mebot-chat>. The
// default host is the server the script was loaded from.
import { createMebot, type MebotOptions } from "./core";
import { defineElement, setDefaultHost } from "./element";

const script = document.currentScript as HTMLScriptElement | null;
const host = script?.src ? new URL(script.src, location.href).origin : undefined;
setDefaultHost(host);

const w = window as unknown as { Mebot?: unknown };
// The one-line widget loader also defines window.Mebot; never replace it.
if (!w.Mebot) w.Mebot = { init: (o: MebotOptions) => createMebot(o, host), version: "1" };
defineElement(window);
