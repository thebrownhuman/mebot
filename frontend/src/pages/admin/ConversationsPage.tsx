import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import { originLabel } from "../../components/admin/dash/format";
import {
  ApiError,
  conversationExportUrl,
  deleteConversation,
  getConversation,
  listConversations,
  type ConversationDetail,
  type ConversationFilters,
  type ConversationFlag,
  type ConversationItem,
  type RangeKey,
} from "../../lib/api";

const HAS: { key: string; label: string }[] = [
  { key: "unanswered", label: "Unanswered" },
  { key: "contact", label: "Left contact" },
  { key: "owner_reply", label: "Your reply" },
  { key: "leak_blocked", label: "Leak blocked" },
];

const FLAG_LABEL: Record<ConversationFlag, string> = {
  unanswered: "Unanswered",
  contact: "Contact",
  owner_reply: "Your reply",
  leak_blocked: "Leak blocked",
  redacted: "Redacted",
};

const EVENT_LABEL: Record<string, string> = {
  UNANSWERED: "Bot couldn't answer",
  PERSONAL_DECLINED: "Personal question declined",
  LEAK_BLOCKED: "Reply blocked (looked like a prompt leak)",
  CHANNEL_REDACTED: "Contact details redacted from a reply",
  OWNER_REPLIED: "You replied",
  CONTACT_LEFT: "Visitor left their contact",
  RATE_LIMITED: "Visitor was rate limited",
  WIDGET_OPENED: "Opened from the widget",
};

const RANGES: { value: RangeKey | ""; label: string }[] = [
  { value: "", label: "All time" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
];

const MIN_QUERY = 2;

const when = (iso: string) =>
  new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded border border-term-line2 px-1.5 py-px text-[10px] text-term-amber whitespace-nowrap">
      {children}
    </span>
  );
}

export default function ConversationsPage() {
  const { toast } = useAdmin();
  const [params, setParams] = useSearchParams();
  const range = (params.get("range") ?? "") as RangeKey | "";
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const q = params.get("q") ?? "";
  const origin = params.get("origin") ?? "";
  const has = useMemo(() => (params.get("has") ?? "").split(",").filter(Boolean), [params]);
  const selected = params.get("c");
  const custom = Boolean(from || to);

  const filters: ConversationFilters = useMemo(
    () => ({ range, from, to, q: q.trim().length >= MIN_QUERY ? q : "", has, origin }),
    [range, from, to, q, has, origin],
  );
  const filterKey = JSON.stringify(filters);

  const update = useCallback(
    (changes: Record<string, string | null>, keepSelection = false) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(changes)) {
            if (v) next.set(k, v);
            else next.delete(k);
          }
          if (!keepSelection && !("c" in changes)) next.delete("c");
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  // --- list ---------------------------------------------------------------------------
  const [items, setItems] = useState<ConversationItem[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const [origins, setOrigins] = useState<string[]>([]);
  const gen = useRef(0);

  const loadFirst = useCallback(() => {
    const mine = ++gen.current;
    setItems(null);
    setError(null);
    listConversations(filters)
      .then((r) => {
        if (mine !== gen.current) return;
        setItems(r.items ?? []);
        setCursor(r.next_cursor ?? null);
        setOrigins((seen) => [...new Set([...seen, ...(r.items ?? []).map((i) => i.origin)])]);
      })
      .catch((e: Error) => {
        if (mine !== gen.current) return;
        setItems([]);
        setCursor(null);
        setError(e.message || "Could not load conversations.");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  useEffect(loadFirst, [loadFirst]);

  async function loadMore() {
    if (!cursor) return;
    const mine = gen.current;
    setMore(true);
    try {
      const r = await listConversations(filters, cursor);
      if (mine !== gen.current) return;
      setItems((xs) => [...(xs ?? []), ...(r.items ?? [])]);
      setCursor(r.next_cursor ?? null);
      setOrigins((seen) => [...new Set([...seen, ...(r.items ?? []).map((i) => i.origin)])]);
    } catch (e) {
      setError((e as Error).message || "Could not load more.");
    } finally {
      setMore(false);
    }
  }

  // --- search (debounced) -------------------------------------------------------------
  const [qInput, setQInput] = useState(q);
  useEffect(() => setQInput(q), [q]);
  useEffect(() => {
    if (qInput === q) return;
    const t = setTimeout(() => update({ q: qInput.trim() || null }), 300);
    return () => clearTimeout(t);
  }, [qInput, q, update]);

  // --- detail -------------------------------------------------------------------------
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    if (!selected) return;
    let live = true;
    getConversation(selected)
      .then((d) => live && setDetail(d))
      .catch((e: Error) => {
        if (!live) return;
        setDetailError(
          e instanceof ApiError && e.status === 404
            ? "This conversation no longer exists. It may have been deleted in another tab or by your retention setting."
            : e.message || "Could not load this conversation.",
        );
      });
    return () => {
      live = false;
    };
  }, [selected]);

  async function remove() {
    if (!detail) return;
    const who = detail.recruiter_name || "this visitor";
    if (!window.confirm(`Delete the conversation with ${who}? This permanently removes the messages and any contact details.`)) return;
    setDeleting(true);
    try {
      await deleteConversation(detail.id);
      setItems((xs) => (xs ?? []).filter((i) => i.id !== detail.id));
      update({ c: null });
      toast("Conversation deleted");
    } catch (e) {
      setDetailError((e as Error).message || "Could not delete the conversation.");
    } finally {
      setDeleting(false);
    }
  }

  function toggleHas(key: string) {
    const next = has.includes(key) ? has.filter((h) => h !== key) : [...has, key];
    update({ has: next.join(",") || null });
  }

  const originOptions = useMemo(
    () => [...new Set([...(origin ? [origin] : []), ...origins.filter((o) => o !== "direct")])],
    [origin, origins],
  );
  const showDetail = Boolean(selected);

  return (
    <AdminSection
      title="Conversations"
      intro="Everything visitors asked your bot. Filter, search, read, export or delete. Only you can see this."
      wide
      actions={
        <div className="flex gap-2">
          {(["csv", "json"] as const).map((f) => (
            <a
              key={f}
              href={conversationExportUrl(filters, f)}
              download
              className="font-mono text-xs px-2.5 py-1.5 rounded border border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright"
            >
              Export {f.toUpperCase()}
            </a>
          ))}
        </div>
      }
    >
      <div className="border border-term-line2 rounded-lg bg-term-panel/60 p-3 mb-3 space-y-3" role="search">
        <div className="flex flex-wrap gap-3 items-end">
          <label className="text-xs text-term-dim block">
            Period
            <select
              value={custom ? "custom" : range}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "custom") update({ range: null, from: from || todayIso(-30), to: to || todayIso(0) });
                else update({ range: v || null, from: null, to: null });
              }}
              className="block mt-1 bg-term-bg border border-term-line2 rounded text-term-fg text-xs px-2 py-1.5"
            >
              {RANGES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
              <option value="custom">Custom dates…</option>
            </select>
          </label>
          {custom && (
            <>
              <label className="text-xs text-term-dim block">
                From
                <input
                  type="date"
                  value={from}
                  max={to || undefined}
                  onChange={(e) => update({ from: e.target.value || null })}
                  className="block mt-1 bg-term-bg border border-term-line2 rounded text-term-fg text-xs px-2 py-1.5"
                />
              </label>
              <label className="text-xs text-term-dim block">
                To
                <input
                  type="date"
                  value={to}
                  min={from || undefined}
                  onChange={(e) => update({ to: e.target.value || null })}
                  className="block mt-1 bg-term-bg border border-term-line2 rounded text-term-fg text-xs px-2 py-1.5"
                />
              </label>
            </>
          )}
          <label className="text-xs text-term-dim block">
            Source
            <select
              value={origin}
              onChange={(e) => update({ origin: e.target.value || null })}
              className="block mt-1 bg-term-bg border border-term-line2 rounded text-term-fg text-xs px-2 py-1.5 max-w-[14rem]"
            >
              <option value="">Any source</option>
              <option value="direct">Direct page</option>
              {originOptions.map((o) => (
                <option key={o} value={o}>
                  {originLabel(o)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-term-dim block flex-1 min-w-[12rem]">
            Search messages
            <input
              type="search"
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              placeholder="e.g. Kubernetes"
              className="block mt-1 w-full bg-term-bg border border-term-line2 rounded text-term-fg text-xs px-2 py-1.5 focus:border-term-bright outline-none"
            />
          </label>
        </div>
        {qInput.trim().length === 1 && (
          <p className="text-term-dim text-[11px]">Type at least {MIN_QUERY} characters to search.</p>
        )}
        <div className="flex flex-wrap gap-2" role="group" aria-label="Only conversations that…">
          {HAS.map((h) => (
            <button
              key={h.key}
              type="button"
              aria-pressed={has.includes(h.key)}
              onClick={() => toggleHas(h.key)}
              className={
                "font-mono text-[11px] px-2.5 py-1 rounded-full border " +
                (has.includes(h.key)
                  ? "border-term-bright text-term-bright bg-term-bright/10"
                  : "border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright")
              }
            >
              {has.includes(h.key) ? "✓ " : ""}
              {h.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p role="alert" className="text-term-err text-xs mb-3">
          {error}{" "}
          <button type="button" onClick={loadFirst} className="underline text-term-bright">
            Try again
          </button>
        </p>
      )}

      <div className="md:grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] md:gap-3 items-start">
        <div className={showDetail ? "hidden md:block" : ""}>
          {items === null ? (
            <p className="text-term-dim text-xs">loading…</p>
          ) : items.length === 0 ? (
            !error && (
              <p className="text-term-dim text-xs border border-dashed border-term-line rounded px-3 py-6 text-center">
                {filterKey === JSON.stringify({ range: "", from: "", to: "", q: "", has: [], origin: "" })
                  ? "No conversations yet. They show up here once someone talks to your bot."
                  : "No conversations match these filters."}
              </p>
            )
          ) : (
            <ul className="space-y-2" aria-label="Conversations">
              {items.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => update({ c: c.id })}
                    aria-current={selected === c.id ? "true" : undefined}
                    className={
                      "w-full text-left border rounded px-3 py-2 text-xs bg-term-panel/60 hover:border-term-bright " +
                      (selected === c.id ? "border-term-bright" : "border-term-line")
                    }
                  >
                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <span className="text-term-fg">{c.recruiter_name || "Anonymous"}</span>
                      <span className="text-term-dim">{when(c.started_at)}</span>
                      <span className="text-term-dim ml-auto">
                        {c.messages === 0 ? "No messages" : `${c.messages} message${c.messages === 1 ? "" : "s"}`}
                      </span>
                    </div>
                    {c.preview && <div className="text-term-dim mt-1 break-words">{c.preview}</div>}
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      <span className="text-[10px] text-term-dim">{originLabel(c.origin)}</span>
                      {c.flags.map((f) => (
                        <Badge key={f}>{FLAG_LABEL[f]}</Badge>
                      ))}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {cursor && (
            <button
              type="button"
              onClick={() => void loadMore()}
              disabled={more}
              className="mt-3 font-mono text-xs px-3 py-1.5 rounded border border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright disabled:opacity-50"
            >
              {more ? "loading…" : "Load more"}
            </button>
          )}
        </div>

        {showDetail && (
          <section
            aria-label="Conversation"
            className="border border-term-line2 rounded-lg bg-term-panel/60 p-3 md:sticky md:top-2"
          >
            <button
              type="button"
              onClick={() => update({ c: null })}
              className="font-mono text-xs text-term-dim hover:text-term-fg mb-3"
            >
              ← Back to list
            </button>
            {detailError && (
              <p role="alert" className="text-term-err text-xs">
                {detailError}
              </p>
            )}
            {!detail && !detailError && <p className="text-term-dim text-xs">loading…</p>}
            {detail && (
              <Transcript detail={detail} onDelete={() => void remove()} deleting={deleting} />
            )}
          </section>
        )}
      </div>
    </AdminSection>
  );
}

function todayIso(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function Transcript({
  detail,
  onDelete,
  deleting,
}: {
  detail: ConversationDetail;
  onDelete: () => void;
  deleting: boolean;
}) {
  const extra = detail.events.filter((e) =>
    ["LEAK_BLOCKED", "CHANNEL_REDACTED", "PERSONAL_DECLINED", "RATE_LIMITED"].includes(e.event),
  );
  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-3 mb-1">
        <h2 className="text-term-bright text-sm">{detail.recruiter_name || "Anonymous"}</h2>
        <span className="text-term-dim text-xs">{when(detail.started_at)}</span>
        <span className="text-term-dim text-xs">{originLabel(detail.origin)}</span>
      </div>
      {detail.contact && (
        <div className="border border-term-line2 rounded px-3 py-2 my-2 text-xs">
          <div className="text-term-amber mb-1">Left their contact</div>
          <div className="text-term-fg">
            {detail.contact.name} ·{" "}
            <a className="underline text-term-bright" href={`mailto:${detail.contact.email}`}>
              {detail.contact.email}
            </a>
          </div>
          {(detail.contact.company || detail.contact.role) && (
            <div className="text-term-dim">
              {[detail.contact.role, detail.contact.company].filter(Boolean).join(" at ")}
            </div>
          )}
          {detail.contact.note && <div className="text-term-dim mt-1 break-words">{detail.contact.note}</div>}
        </div>
      )}
      {extra.length > 0 && (
        <ul className="my-2 space-y-0.5 text-[11px] text-term-dim" aria-label="Events">
          {extra.map((e, i) => (
            <li key={i}>
              <Badge>{EVENT_LABEL[e.event] ?? e.event}</Badge> {when(e.created_at)}
            </li>
          ))}
        </ul>
      )}
      <ol className="space-y-2 my-3" aria-label="Transcript">
        {detail.messages.length === 0 && <li className="text-term-dim text-xs">No messages.</li>}
        {detail.messages.map((m, i) => {
          const who = m.role === "user" ? "Recruiter" : m.from_owner ? "You" : "Bot";
          return (
            <li key={i} className="text-xs">
              <div className="flex flex-wrap items-center gap-2 text-term-dim text-[11px]">
                <span className={m.role === "user" ? "text-term-recruiter" : "text-term-bright"}>{who}</span>
                <span>{when(m.created_at)}</span>
                {m.unanswered && <Badge>Unanswered</Badge>}
                {m.from_owner && <Badge>Owner reply</Badge>}
              </div>
              <div className="text-term-fg whitespace-pre-wrap break-words mt-0.5">{m.content}</div>
              {m.chunks && m.chunks.length > 0 && (
                <details className="mt-1 text-[11px] text-term-dim">
                  <summary className="cursor-pointer hover:text-term-fg">
                    Profile parts used ({m.chunks.length})
                  </summary>
                  <ul className="mt-1 space-y-0.5 pl-3 list-disc break-words">
                    {m.chunks.map((c) => (
                      <li key={c.id}>
                        <span className="uppercase tracking-wide">{c.section}</span> · {c.title}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          );
        })}
      </ol>
      <button
        type="button"
        onClick={onDelete}
        disabled={deleting}
        className="font-mono text-xs px-2.5 py-1.5 rounded border border-term-err text-term-err hover:bg-term-err/10 disabled:opacity-50"
      >
        {deleting ? "deleting…" : "Delete conversation"}
      </button>
    </div>
  );
}
