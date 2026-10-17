// Theming: a strict allow-list. Values become iframe URL params or inline styles we
// build ourselves, so nothing a host page passes can inject raw CSS.

export type ThemeMode = "light" | "dark" | "auto";
export type Font = "system" | "serif" | "mono" | "rounded";

export interface Theme {
  theme?: ThemeMode;
  accent?: string; // #rrggbb
  radius?: number; // px, 0-32
  font?: Font;
  launcherSize?: number; // px, 40-80
  offsetX?: number; // px, 0-200
  offsetY?: number; // px, 0-200
}

const HEX = /^#[0-9a-f]{6}$/i;
const PX = /^\s*(\d{1,3})(px)?\s*$/;
export const FONTS: readonly Font[] = ["system", "serif", "mono", "rounded"];
const MODES: readonly ThemeMode[] = ["light", "dark", "auto"];

function px(v: unknown, min: number, max: number): number | undefined {
  const m = typeof v === "number" ? [String(v), String(v)] : PX.exec(String(v ?? ""));
  if (!m) return undefined;
  const n = Number(m[1]);
  return Number.isInteger(n) && n >= min && n <= max ? n : undefined;
}

// Keeps only valid values; anything else is dropped (defaults apply).
export function cleanTheme(t: Record<string, unknown>): Theme {
  const out: Theme = {};
  if (MODES.includes(t.theme as ThemeMode)) out.theme = t.theme as ThemeMode;
  if (typeof t.accent === "string" && HEX.test(t.accent.trim())) out.accent = t.accent.trim().toLowerCase();
  if (FONTS.includes(t.font as Font)) out.font = t.font as Font;
  const r = px(t.radius, 0, 32);
  if (r !== undefined) out.radius = r;
  const s = px(t.launcherSize, 40, 80);
  if (s !== undefined) out.launcherSize = s;
  const x = px(t.offsetX, 0, 200);
  if (x !== undefined) out.offsetX = x;
  const y = px(t.offsetY, 0, 200);
  if (y !== undefined) out.offsetY = y;
  return out;
}

// --mebot-accent, --mebot-radius, --mebot-font, --mebot-launcher-size, --mebot-offset-x/-y
export function themeFromCss(style: CSSStyleDeclaration): Theme {
  const v = (n: string) => style.getPropertyValue(n).trim().replace(/^["']|["']$/g, "") || undefined;
  return cleanTheme({
    accent: v("--mebot-accent"),
    radius: v("--mebot-radius"),
    font: v("--mebot-font"),
    launcherSize: v("--mebot-launcher-size"),
    offsetX: v("--mebot-offset-x"),
    offsetY: v("--mebot-offset-y"),
  });
}

// What the iframe gets (it validates again): theme, accent (without #), font.
export function iframeParams(t: Theme): string {
  const q: string[] = [];
  if (t.theme) q.push("theme=" + t.theme);
  if (t.accent) q.push("accent=" + t.accent.slice(1));
  if (t.font) q.push("font=" + t.font);
  return q.length ? "&" + q.join("&") : "";
}
