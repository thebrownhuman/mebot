import { Link } from "react-router-dom";
import type { Overview, RangeKey } from "../../../lib/api";
import { describeDelta, formatValue, originLabel, type KpiKind } from "./format";

const TILES: { key: keyof Overview["kpis"]; label: string; kind: KpiKind }[] = [
  { key: "chats", label: "Chats", kind: "count" },
  { key: "visitor_messages", label: "Visitor messages", kind: "count" },
  { key: "avg_messages_per_chat", label: "Messages per chat", kind: "decimal" },
  { key: "unanswered_rate", label: "Unanswered replies", kind: "rate" },
  { key: "contacts", label: "Contacts left", kind: "count" },
  { key: "owner_replies", label: "Your replies", kind: "count" },
  { key: "open_questions", label: "Open questions", kind: "count" },
  { key: "tokens", label: "Tokens used", kind: "count" },
];

export function KpiTiles({ kpis, range }: { kpis: Overview["kpis"]; range: RangeKey }) {
  return (
    <ul className="grid grid-cols-2 md:grid-cols-4 gap-2" aria-label="Key numbers">
      {TILES.map(({ key, label, kind }) => {
        const k = kpis[key];
        const delta = key === "open_questions" ? null : describeDelta(k, kind, range);
        const approx = key === "tokens" && k.estimated;
        return (
          <li key={key} className="border border-term-line2 rounded-lg bg-term-panel/60 px-3 py-2.5">
            <div className="text-[11px] text-term-dim">{label}</div>
            <div className="text-term-bright text-xl leading-tight mt-0.5">
              {approx && <span aria-label="about">≈ </span>}
              {formatValue(k.value, kind)}
            </div>
            {delta ? (
              <div className="text-[11px] text-term-dim mt-1">
                <span aria-hidden="true">{delta.arrow} </span>
                {delta.text}
              </div>
            ) : (
              <div className="text-[11px] text-term-dim mt-1">
                {key === "open_questions" ? "right now" : "—"}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function TopQuestions({
  items,
  range,
}: {
  items: Overview["top_questions"];
  range: RangeKey;
}) {
  return (
    <section aria-labelledby="top-q" className="border border-term-line2 rounded-lg bg-term-panel/60 p-3">
      <h2 id="top-q" className="text-xs text-term-amber tracking-wide mb-2">
        // Top questions
      </h2>
      {items.length === 0 ? (
        <p className="text-term-dim text-xs">No questions in this period.</p>
      ) : (
        <ol className="space-y-1.5">
          {items.map((q) => (
            <li key={q.question} className="flex items-baseline gap-2 text-xs">
              <Link
                to={`/admin/conversations?${new URLSearchParams({ q: q.question.slice(0, 80), range })}`}
                className="text-term-fg hover:text-term-bright underline decoration-term-line2 flex-1 min-w-0 break-words"
              >
                {q.question}
              </Link>
              <span className="text-term-amber whitespace-nowrap" aria-label={`asked ${q.count} times`}>
                {q.count}×
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function Sources({
  items,
  range,
}: {
  items: Overview["sources"];
  range: RangeKey;
}) {
  const total = items.reduce((n, s) => n + s.chats, 0) || 1;
  return (
    <section aria-labelledby="sources" className="border border-term-line2 rounded-lg bg-term-panel/60 p-3">
      <h2 id="sources" className="text-xs text-term-amber tracking-wide mb-2">
        // Where chats come from
      </h2>
      {items.length === 0 ? (
        <p className="text-term-dim text-xs">No chats in this period.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((s) => {
            const pct = Math.round((s.chats / total) * 100);
            return (
              <li key={s.origin} className="text-xs">
                <div className="flex items-baseline gap-2">
                  <Link
                    to={`/admin/conversations?${new URLSearchParams({ origin: s.origin, range })}`}
                    className="text-term-fg hover:text-term-bright underline decoration-term-line2 flex-1 min-w-0 truncate"
                    title={s.origin}
                  >
                    {originLabel(s.origin)}
                  </Link>
                  <span className="text-term-dim whitespace-nowrap">
                    {s.chats} {s.chats === 1 ? "chat" : "chats"} · {pct}%
                  </span>
                </div>
                <div className="h-1.5 mt-1 rounded bg-term-line" aria-hidden="true">
                  <div className="h-full rounded bg-term-bright" style={{ width: `${pct}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

type Level = "ok" | "warn" | "off";

const MARK: Record<Level, string> = { ok: "✓", warn: "!", off: "•" };
const TONE: Record<Level, string> = {
  ok: "text-term-bright",
  warn: "text-term-amber",
  off: "text-term-dim",
};

// One place for what the old dashboard scattered as banners: provider, Telegram, widget,
// paused, and today's cap. Each row says its state in words and links to the fix.
export function StatusCard({ status }: { status: Overview["status"] }) {
  const { llm, telegram, widget, today } = status;
  const ratio = today.cap ? today.messages / today.cap : 0;
  const rows: { label: string; level: Level; text: string; to?: string; cta?: string }[] = [
    !llm.configured
      ? { label: "AI provider", level: "warn", text: "Not configured — chat is off", to: "/admin/llm", cta: "Set up" }
      : !llm.ok
        ? { label: "AI provider", level: "warn", text: "Last test or call failed", to: "/admin/llm", cta: "Check key" }
        : { label: "AI provider", level: "ok", text: "Working" },
    telegram.linked
      ? telegram.dead > 0
        ? { label: "Telegram", level: "warn", text: `Linked · ${telegram.dead} message${telegram.dead === 1 ? "" : "s"} could not be delivered`, to: "/admin/notifications", cta: "Open" }
        : { label: "Telegram", level: "ok", text: "Linked" }
      : { label: "Telegram", level: "off", text: "Not linked — you won't hear about new chats", to: "/admin/notifications", cta: "Set up" },
    !widget.enabled
      ? { label: "Widget", level: "off", text: "Off", to: "/admin/widget", cta: "Open" }
      : widget.origins === 0 && !widget.any_origin
        ? { label: "Widget", level: "off", text: "On, but no site is allowed to show it yet", to: "/admin/widget", cta: "Add your site" }
        : {
            label: "Widget",
            level: "ok",
            text: widget.any_origin ? "On · any site" : `On · ${widget.origins} allowed site${widget.origins === 1 ? "" : "s"}`,
          },
    status.paused
      ? { label: "Bot", level: "warn", text: "Paused — visitors can't chat", to: "/admin/limits", cta: "Resume" }
      : { label: "Bot", level: "ok", text: "Running" },
    ratio >= 1
      ? { label: "Today", level: "warn", text: `Message cap reached (${today.messages}/${today.cap}); chats resume at 00:00 UTC`, to: "/admin/limits", cta: "Open limits" }
      : ratio >= 0.8
        ? { label: "Today", level: "warn", text: `${today.messages}/${today.cap} messages (${Math.floor(ratio * 100)}% of the cap)`, to: "/admin/limits", cta: "Open limits" }
        : { label: "Today", level: "ok", text: `${today.messages}/${today.cap} messages` },
  ];
  return (
    <section aria-labelledby="status-h" className="border border-term-line2 rounded-lg bg-term-panel/60 p-3">
      <h2 id="status-h" className="text-xs text-term-amber tracking-wide mb-2">
        // Status
      </h2>
      <ul className="space-y-1.5">
        {rows.map((r) => (
          <li key={r.label} className="flex flex-wrap items-baseline gap-x-2 text-xs">
            <span className={`${TONE[r.level]} w-3 text-center`} aria-hidden="true">
              {MARK[r.level]}
            </span>
            <span className="text-term-dim w-24 shrink-0">{r.label}</span>
            <span className="text-term-fg flex-1 min-w-0">{r.text}</span>
            {r.to && (
              <Link to={r.to} className="text-term-bright underline">
                {r.cta}
              </Link>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
