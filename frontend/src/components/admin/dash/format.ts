import type { Kpi, RangeKey } from "../../../lib/api";

export const RANGE_LABEL: Record<RangeKey, string> = {
  "7d": "7 days",
  "30d": "30 days",
  "90d": "90 days",
};

export type KpiKind = "count" | "rate" | "decimal";

const num = new Intl.NumberFormat("en");

export function formatValue(v: number | null, kind: KpiKind): string {
  if (v === null) return "—";
  if (kind === "rate") return `${Math.round(v * 100)}%`;
  if (kind === "decimal") return v.toFixed(1);
  return num.format(v);
}

// "▲ 5 more than the previous 7 days": direction is in words and an arrow, never colour only.
export function describeDelta(
  k: Kpi,
  kind: KpiKind,
  range: RangeKey,
): { arrow: string; text: string } | null {
  if (k.previous === null || k.value === null) return null;
  const label = `the previous ${RANGE_LABEL[range]}`;
  if (k.previous === 0 && k.value === 0) return { arrow: "•", text: `no change from ${label}` };
  const diff = k.value - k.previous;
  if (Math.abs(diff) < (kind === "count" ? 0.5 : 0.0005)) {
    return { arrow: "•", text: `same as ${label}` };
  }
  const up = diff > 0;
  const arrow = up ? "▲" : "▼";
  if (kind === "rate") {
    const pts = Math.round(Math.abs(diff) * 100);
    return { arrow, text: `${pts} point${pts === 1 ? "" : "s"} ${up ? "higher" : "lower"} than ${label}` };
  }
  const amount = kind === "decimal" ? Math.abs(diff).toFixed(1) : num.format(Math.abs(diff));
  return { arrow, text: `${amount} ${up ? "more" : "fewer"} than ${label}` };
}

// "2026-10-11" -> "Oct 11". Pure calendar maths (UTC), so it never shifts with the viewer's zone.
export function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", timeZone: "UTC" }).format(
    new Date(Date.UTC(y, m - 1, d)),
  );
}

export function originLabel(origin: string): string {
  return origin === "direct" ? "Direct page" : origin.replace(/^https?:\/\//, "");
}

export function niceMax(v: number): number {
  if (v <= 4) return 4;
  const pow = 10 ** Math.floor(Math.log10(v));
  const n = v / pow;
  const step = n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * pow;
}
