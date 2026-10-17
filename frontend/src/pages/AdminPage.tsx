import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AdminSection } from "../components/admin/AdminLayout";
import ActivityChart from "../components/admin/dash/ActivityChart";
import { RANGE_LABEL } from "../components/admin/dash/format";
import { KpiTiles, Sources, StatusCard, TopQuestions } from "../components/admin/dash/Panels";
import OpenQuestionsPanel from "../components/admin/OpenQuestionsPanel";
import { getOverview, type Overview, type RangeKey } from "../lib/api";

const RANGES: RangeKey[] = ["7d", "30d", "90d"];

// Dashboard: key numbers, activity, top questions, sources and system status, all in the
// owner's timezone. To try the bot, open the public chat from the link in the header.
export default function AdminPage() {
  const [range, setRange] = useState<RangeKey>("7d");
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback((r: RangeKey) => {
    setLoading(true);
    setError(null);
    return getOverview(r)
      .then(setData)
      .catch((e: Error) => setError(e.message || "Could not load the dashboard."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    void load(range);
  }, [range, load]);

  const isNew =
    data !== null &&
    data.kpis.chats.value === 0 &&
    data.kpis.chats.previous === 0 &&
    data.series.every((d) => d.visitor_messages === 0);

  const actions = (
    <div className="flex flex-wrap items-center gap-2">
      <div role="group" aria-label="Time range" className="flex">
        {RANGES.map((r, i) => (
          <button
            key={r}
            type="button"
            aria-pressed={range === r}
            onClick={() => setRange(r)}
            className={
              "font-mono text-xs px-2.5 py-1.5 border " +
              (i === 0 ? "rounded-l " : "-ml-px ") +
              (i === RANGES.length - 1 ? "rounded-r " : "") +
              (range === r
                ? "border-term-bright text-term-bright bg-term-bright/10 relative z-10"
                : "border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright")
            }
          >
            {r}
          </button>
        ))}
      </div>
      <a
        href="/"
        target="_blank"
        rel="noopener"
        className="font-mono text-xs px-2.5 py-1.5 rounded border border-term-line2 text-term-bright hover:border-term-bright"
      >
        Try your bot ↗
      </a>
    </div>
  );

  return (
    <AdminSection
      title="Dashboard"
      intro={
        data
          ? `Last ${RANGE_LABEL[range]} (${data.range.from} to ${data.range.to}, ${data.range.timezone}), compared with the ${RANGE_LABEL[range]} before.`
          : "How your bot is doing."
      }
      actions={actions}
      wide
    >
      {error && (
        <div role="alert" className="border border-term-err text-term-err rounded px-3 py-2 mb-3 text-xs">
          {error}{" "}
          <button type="button" onClick={() => void load(range)} className="underline text-term-bright">
            Try again
          </button>
        </div>
      )}
      {data === null && loading && <p className="text-term-dim text-xs">loading…</p>}
      {data && (
        <div className="space-y-3" aria-busy={loading}>
          {isNew ? (
            <section className="border border-dashed border-term-line2 rounded-lg px-4 py-8 text-center">
              <h2 className="text-term-bright text-sm mb-1">No chats yet</h2>
              <p className="text-term-dim text-xs max-w-md mx-auto leading-relaxed">
                Share your link or embed the widget on your site — numbers show up here as
                soon as someone talks to your bot.
              </p>
              <div className="mt-3 flex flex-wrap gap-3 justify-center text-xs">
                <a href="/" target="_blank" rel="noopener" className="text-term-bright underline">
                  Open your public chat
                </a>
                <Link to="/admin/widget" className="text-term-bright underline">
                  Embed the widget
                </Link>
              </div>
            </section>
          ) : (
            <>
              <KpiTiles kpis={data.kpis} range={range} />
              <ActivityChart series={data.series} />
              <div className="grid gap-3 md:grid-cols-2">
                <TopQuestions items={data.top_questions} range={range} />
                <Sources items={data.sources} range={range} />
              </div>
            </>
          )}
          <div className="grid gap-3 md:grid-cols-2">
            <StatusCard status={data.status} />
            <OpenQuestionsPanel />
          </div>
        </div>
      )}
    </AdminSection>
  );
}
