import HostedBanner from "./HostedBanner";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  dismissUpdate,
  getLlm,
  getTelemetry,
  listOpenQuestions,
  logout,
  type LlmConfigView,
  type Me,
  type TelemetryView,
} from "../../lib/api";

// Admin shell: sidebar (top menu on small screens), AI-provider banner, toasts and
// an unsaved-changes guard shared by every admin page.

interface AdminCtx {
  me: Me;
  setDirty: (dirty: boolean) => void;
  // true if it's fine to navigate away (not dirty, or the owner confirmed).
  confirmLeave: () => boolean;
  toast: (message: string) => void;
  // Re-count open questions (sidebar badge) after a page changed them.
  refreshOpenCount: () => void;
}

const Ctx = createContext<AdminCtx | null>(null);

export function useAdmin(): AdminCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAdmin outside AdminLayout");
  return ctx;
}

export const LEAVE_MESSAGE = "You have unsaved changes. Leave without saving?";

const NAV: { to: string; label: string; end?: boolean; group?: string; badge?: "open" }[] = [
  { to: "/admin", label: "Dashboard", end: true },
  { to: "/admin/conversations", label: "Conversations" },
  { to: "/admin/open-questions", label: "Open questions", badge: "open" },
  { to: "/admin/contacts", label: "Contacts" },
  { to: "/admin/import", label: "Import", group: "Your data" },
  { to: "/admin/profile/identity", label: "Identity" },
  { to: "/admin/profile/experience", label: "Experience" },
  { to: "/admin/profile/education", label: "Education" },
  { to: "/admin/profile/skills", label: "Skills" },
  { to: "/admin/profile/projects", label: "Projects" },
  { to: "/admin/profile/interests", label: "Interests & Hobbies" },
  { to: "/admin/profile/faq", label: "FAQ" },
  { to: "/admin/profile/avoid-topics", label: "Avoid topics" },
  { to: "/admin/profile/notes", label: "Notes" },
  { to: "/admin/memory", label: "Memory" },
  { to: "/admin/profile/preview", label: "Preview" },
  { to: "/admin/llm", label: "AI Provider", group: "Settings" },
  { to: "/admin/limits", label: "Limits" },
  { to: "/admin/notifications", label: "Notifications" },
  { to: "/admin/widget", label: "Widget" },
  { to: "/admin/account", label: "Account" },
];

function Banner({ llm }: { llm: LlmConfigView | null }) {
  if (!llm || (llm.configured && llm.last_test_ok !== false)) return null;
  return (
    <div
      role="alert"
      className="border border-term-err text-term-err rounded px-3 py-2 mb-3 text-xs"
    >
      {!llm.configured
        ? llm.status === "undecryptable"
          ? "Your saved API key can no longer be decrypted (SECRET_KEY changed). Chat is off until you re-enter it."
          : "No AI provider is configured. Chat is off until you add your own API key."
        : "The last call to your AI provider failed — check your key, model or quota."}{" "}
      <Link to="/admin/llm" className="underline text-term-bright">
        {llm.configured ? "Open AI provider settings" : "Set up AI provider"}
      </Link>
    </div>
  );
}

// A security advisory for this version (red, can't be dismissed) or a new release
// (dismissible per version). Quiet when the registry can't be reached or telemetry is off.
function UpdateBanner({ info, onDismiss }: { info: TelemetryView["update"] | null; onDismiss: (v: string) => void }) {
  if (!info) return null;
  const { advisory, latest, current } = info;
  if (advisory) {
    const link = advisory.url && /^https?:\/\//.test(advisory.url) ? advisory.url : null;
    return (
      <div role="alert" className="border border-term-err text-term-err rounded px-3 py-2 mb-3 text-xs">
        <b>Security advisory affects your version ({current}):</b> {advisory.title}.
        {latest && info.available ? ` Update to mebot ${latest}.` : ""}{" "}
        {link && (
          <a href={link} target="_blank" rel="noreferrer" className="underline text-term-bright">
            Details
          </a>
        )}
      </div>
    );
  }
  if (!info.available || info.dismissed || !latest) return null;
  return (
    <div role="status" className="border border-term-amber text-term-amber rounded px-3 py-2 mb-3 text-xs flex flex-wrap items-center gap-2">
      <span className="flex-1 min-w-[12rem]">
        Update available: mebot {latest} (you have {current}).
      </span>
      <button
        type="button"
        onClick={() => onDismiss(latest)}
        className="font-mono px-2 py-0.5 rounded border border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright"
      >
        Dismiss
      </button>
    </div>
  );
}

export default function AdminLayout({ me }: { me: Me }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const dirty = useRef(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [toasts, setToasts] = useState<{ id: number; text: string }[]>([]);
  const [llm, setLlm] = useState<LlmConfigView | null>(null);
  const [update, setUpdate] = useState<TelemetryView["update"] | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [openCount, setOpenCount] = useState(0);

  useEffect(() => {
    getLlm()
      .then(setLlm)
      .catch(() => setLlm(null));
  }, [pathname]);

  useEffect(() => {
    getTelemetry()
      .then((t) => setUpdate(t?.update ?? null))
      .catch(() => setUpdate(null));
  }, [pathname]);

  const dismiss = useCallback((version: string) => {
    setUpdate((u) => (u ? { ...u, dismissed: true } : u));
    dismissUpdate(version).catch(() => undefined);
  }, []);

  const refreshOpenCount = useCallback(() => {
    listOpenQuestions("open")
      .then((r) => setOpenCount(r.open_count))
      .catch(() => setOpenCount(0));
  }, []);

  useEffect(() => {
    refreshOpenCount();
  }, [pathname, refreshOpenCount]);

  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => {
      if (dirty.current) e.preventDefault();
    };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, []);

  const setDirty = useCallback((d: boolean) => {
    dirty.current = d;
  }, []);

  const confirmLeave = useCallback(() => {
    if (!dirty.current) return true;
    if (!window.confirm(LEAVE_MESSAGE)) return false;
    dirty.current = false;
    return true;
  }, []);

  const toast = useCallback((text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3000);
  }, []);

  async function doLogout() {
    if (!confirmLeave()) return;
    setLoggingOut(true);
    try {
      await logout();
    } catch {
      // Cookie is cleared server-side on success; on failure still leave the panel.
    }
    navigate("/admin/login", { replace: true });
  }

  const current = NAV.find((n) => (n.end ? pathname === n.to : pathname.startsWith(n.to)));

  const nav = (
    <nav aria-label="admin" className="text-sm">
      <ul className="space-y-0.5">
        {NAV.map((n) => (
          <li key={n.to}>
            {n.group && (
              <div className="text-[10px] uppercase tracking-widest text-term-dim mt-4 mb-1 px-2">
                {n.group}
              </div>
            )}
            <NavLink
              to={n.to}
              end={n.end}
              onClick={(e) => {
                if (!confirmLeave()) e.preventDefault();
                else setMenuOpen(false);
              }}
              className={({ isActive }) =>
                "block rounded px-2 py-1.5 font-mono text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright " +
                (isActive
                  ? "bg-term-bright/10 text-term-bright"
                  : "text-term-dim hover:text-term-fg hover:bg-term-panel")
              }
            >
              {n.label}
              {n.badge === "open" && openCount > 0 && (
                <span
                  aria-label={`${openCount} open`}
                  className="ml-2 rounded-full bg-term-amber/20 text-term-amber px-1.5 py-px text-[10px]"
                >
                  {openCount}
                </span>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="border-t border-term-line mt-4 pt-3 px-2">
        <div className="text-term-dim text-[11px] truncate mb-2" title={me.email}>
          {me.bot_name} · {me.email}
        </div>
        <button
          type="button"
          onClick={doLogout}
          disabled={loggingOut}
          className="font-mono text-xs px-2.5 py-1.5 rounded border border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright disabled:opacity-50"
        >
          {loggingOut ? "logging out…" : "log out"}
        </button>
      </div>
      <p className="mt-4 px-2 text-xs text-term-dim">mebot v{__APP_VERSION__}</p>
    </nav>
  );

  return (
    <Ctx.Provider value={{ me, setDirty, confirmLeave, toast, refreshOpenCount }}>
      <div className="relative z-10 min-h-screen md:flex">
        {/* small screens: top bar with a menu toggle */}
        <header className="md:hidden flex items-center gap-3 border-b border-term-line bg-term-panel/95 px-4 py-3 sticky top-0 z-30">
          <button
            type="button"
            aria-expanded={menuOpen}
            aria-controls="admin-menu"
            onClick={() => setMenuOpen((o) => !o)}
            className="font-mono text-xs px-2.5 py-1.5 rounded border border-term-line2 text-term-fg"
          >
            {menuOpen ? "close" : "menu"}
          </button>
          <span className="text-term-amber text-xs">// {current?.label ?? "admin"}</span>
        </header>
        {menuOpen && (
          <div
            id="admin-menu"
            className="md:hidden border-b border-term-line bg-term-panel px-4 py-3"
          >
            {nav}
          </div>
        )}
        <aside className="hidden md:block w-56 shrink-0 border-r border-term-line bg-term-panel/80 px-3 py-5 h-screen sticky top-0 overflow-y-auto">
          <div className="text-term-amber text-xs mb-3 px-2">// mebot admin</div>
          {nav}
        </aside>
        <main className="flex-1 min-w-0 md:h-screen md:overflow-y-auto flex flex-col">
          <div className="px-4 pt-4 md:px-6">
            <HostedBanner />
            <Banner llm={llm} />
            <UpdateBanner info={update} onDismiss={dismiss} />
          </div>
          <div className="flex-1 min-h-0">
            <Outlet />
          </div>
        </main>
      </div>
      <div aria-live="polite" className="fixed bottom-4 right-4 z-50 space-y-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className="border border-term-bright bg-term-panel text-term-bright text-xs font-mono rounded px-3 py-2 shadow-lg"
          >
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

// Page wrapper with a heading, used by every data page.
export function AdminSection({
  title,
  intro,
  actions,
  wide,
  children,
}: {
  title: string;
  intro?: React.ReactNode;
  actions?: React.ReactNode;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className={`${wide ? "max-w-5xl" : "max-w-3xl"} px-4 pb-10 md:px-6`}>
      <div className="flex flex-wrap items-start gap-3 mb-4">
        <div className="flex-1 min-w-[12rem]">
          <h1 className="text-term-bright text-lg">{title}</h1>
          {intro && <p className="text-term-dim text-xs mt-1 leading-relaxed">{intro}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}
