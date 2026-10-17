import { useId, useState } from "react";
import type { SeriesDay } from "../../../lib/api";
import { niceMax, shortDate } from "./format";

// Daily chats (solid bars) next to unanswered replies (hatched bars). Hand-rolled SVG on
// the theme's tokens, so it follows whatever theme the app is in. The pattern, not just
// the colour, tells the two series apart; "Show as table" gives the same numbers as text.

const W = 640;
const H = 220;
const M = { top: 12, right: 8, bottom: 26, left: 34 };

export default function ActivityChart({ series }: { series: SeriesDay[] }) {
  const uid = useId();
  const [asTable, setAsTable] = useState(false);
  const totalChats = series.reduce((n, d) => n + d.chats, 0);
  const totalUnanswered = series.reduce((n, d) => n + d.unanswered, 0);
  const max = niceMax(Math.max(0, ...series.map((d) => Math.max(d.chats, d.unanswered))));
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const slot = plotW / Math.max(series.length, 1);
  const barW = Math.max(1, Math.min(14, slot * 0.38));
  const y = (v: number) => M.top + plotH - (v / max) * plotH;
  const ticks = [0, max / 2, max];
  const labelEvery = Math.ceil(series.length / 7);
  const summary = `${totalChats} chats and ${totalUnanswered} unanswered replies over ${series.length} days.`;

  return (
    <section aria-labelledby={`${uid}-h`} className="border border-term-line2 rounded-lg bg-term-panel/60 p-3">
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <h2 id={`${uid}-h`} className="text-xs text-term-amber tracking-wide flex-1">
          // Activity
        </h2>
        <span className="flex items-center gap-3 text-[11px] text-term-dim" aria-hidden="true">
          <span className="flex items-center gap-1">
            <svg width="10" height="10">
              <rect width="10" height="10" className="fill-term-bright" />
            </svg>
            chats
          </span>
          <span className="flex items-center gap-1">
            <svg width="10" height="10">
              <rect width="10" height="10" className="fill-term-bg stroke-term-amber" />
              <path d="M0 10L10 0" className="stroke-term-amber" />
            </svg>
            unanswered
          </span>
        </span>
        <button
          type="button"
          aria-pressed={asTable}
          onClick={() => setAsTable((t) => !t)}
          className="font-mono text-[11px] px-2 py-1 rounded border border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright"
        >
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-xs text-left">
            <caption className="sr-only">{summary}</caption>
            <thead className="text-term-dim">
              <tr>
                <th scope="col" className="py-1 pr-3 font-normal">Date</th>
                <th scope="col" className="py-1 pr-3 font-normal text-right">Chats</th>
                <th scope="col" className="py-1 pr-3 font-normal text-right">Visitor messages</th>
                <th scope="col" className="py-1 font-normal text-right">Unanswered</th>
              </tr>
            </thead>
            <tbody>
              {series.map((d) => (
                <tr key={d.date} className="border-t border-term-line">
                  <th scope="row" className="py-1 pr-3 font-normal text-term-fg">
                    {shortDate(d.date)}
                  </th>
                  <td className="py-1 pr-3 text-right">{d.chats}</td>
                  <td className="py-1 pr-3 text-right">{d.visitor_messages}</td>
                  <td className="py-1 text-right">{d.unanswered}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-labelledby={`${uid}-t ${uid}-d`}
          className="w-full h-auto block"
        >
          <title id={`${uid}-t`}>Daily chats and unanswered replies</title>
          <desc id={`${uid}-d`}>{summary}</desc>
          <defs>
            <pattern id={`${uid}-hatch`} width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="4" height="4" className="fill-term-bg" />
              <line x1="0" y1="0" x2="0" y2="4" strokeWidth="2" className="stroke-term-amber" />
            </pattern>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} className="stroke-term-line" strokeWidth="1" />
              <text x={M.left - 6} y={y(t) + 3} textAnchor="end" className="fill-term-dim" fontSize="10">
                {Number.isInteger(t) ? t : t.toFixed(1)}
              </text>
            </g>
          ))}
          {series.map((d, i) => {
            const x0 = M.left + i * slot + slot / 2;
            return (
              <g key={d.date}>
                <title>{`${shortDate(d.date)}: ${d.chats} chats, ${d.unanswered} unanswered`}</title>
                {d.chats > 0 && (
                  <rect x={x0 - barW} y={y(d.chats)} width={barW} height={y(0) - y(d.chats)} className="fill-term-bright" />
                )}
                {d.unanswered > 0 && (
                  <rect
                    x={x0}
                    y={y(d.unanswered)}
                    width={barW}
                    height={y(0) - y(d.unanswered)}
                    fill={`url(#${uid}-hatch)`}
                    className="stroke-term-amber"
                    strokeWidth="1"
                  />
                )}
                {i % labelEvery === 0 && (
                  <text x={x0} y={H - 8} textAnchor="middle" className="fill-term-dim" fontSize="10">
                    {shortDate(d.date)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
    </section>
  );
}
