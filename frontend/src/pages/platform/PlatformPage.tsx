import { useCallback, useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { CenteredCard, Field, FormError, SubmitButton } from "../../components/AuthForm";
import {
  ApiError,
  platformAudit,
  platformCreateInvite,
  platformInvites,
  platformLogin,
  platformLogout,
  platformMe,
  platformRevokeInvite,
  platformSignups,
  platformTenantAction,
  platformTenants,
  type PlatformTenant,
  type TenantAction,
} from "../../lib/api";

// Operator console (hosted mode). Metadata and account actions only: the API has no way
// to show tenants' keys, profiles or conversations, and neither does this page.

const btn =
  "font-mono text-xs px-2.5 py-1 rounded border border-term-line2 text-term-fg hover:border-term-bright hover:text-term-bright disabled:opacity-50";
const danger =
  "font-mono text-xs px-2.5 py-1 rounded border border-term-err/60 text-term-err hover:border-term-err disabled:opacity-50";

function errText(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—");

export function PlatformLoginPage() {
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await platformLogin(email.trim(), password);
      nav("/platform", { replace: true });
    } catch (err) {
      setError(errText(err, "Login failed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <CenteredCard title="// platform operator" heading="Log in">
      <form onSubmit={submit}>
        <FormError message={error} />
        <Field id="pl-email" label="e-mail" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field id="pl-password" label="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <SubmitButton busy={busy}>log in</SubmitButton>
      </form>
    </CenteredCard>
  );
}

type Tab = "tenants" | "signups" | "invites" | "audit";
const TABS: { id: Tab; label: string }[] = [
  { id: "tenants", label: "Tenants" },
  { id: "signups", label: "Sign-ups" },
  { id: "invites", label: "Invites" },
  { id: "audit", label: "Audit log" },
];

function Loading() {
  return (
    <p role="status" className="text-term-dim text-sm">
      loading…
    </p>
  );
}

function Failed({ message }: { message: string }) {
  return (
    <p role="alert" className="text-term-err text-sm">
      {message}
    </p>
  );
}

function useLoad<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    setError(null);
    load()
      .then(setData)
      .catch((e: unknown) => {
        setData(null);
        setError(errText(e, "Could not load."));
      });
  }, [load]);
  useEffect(reload, [reload]);
  return { data, error, reload };
}

function TenantCard({
  t,
  onAction,
  busy,
}: {
  t: PlatformTenant;
  onAction: (t: PlatformTenant, a: TenantAction) => void;
  busy: boolean;
}) {
  return (
    <li className="border border-term-line2 rounded-lg p-3 bg-term-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <span className="text-term-bright text-sm break-all">/b/{t.slug}</span>
        <span
          className={`text-xs ${t.status === "active" ? "text-term-fg" : t.status === "pending" ? "text-term-amber" : "text-term-err"}`}
        >
          {t.status}
          {t.status_reason ? ` — ${t.status_reason}` : ""}
        </span>
      </div>
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-xs mb-3">
        <dt className="text-term-dim">owner</dt>
        <dd className="text-term-fg break-all">
          {t.owner_email ?? "—"} {t.email_verified ? "" : "(unverified)"}
        </dd>
        <dt className="text-term-dim">plan</dt>
        <dd className="text-term-fg">{t.plan}</dd>
        <dt className="text-term-dim">msgs 7d / 30d</dt>
        <dd className="text-term-fg">
          {t.messages_7d} / {t.messages_30d}
        </dd>
        <dt className="text-term-dim">tokens 30d</dt>
        <dd className="text-term-fg">{t.tokens_30d.toLocaleString()}</dd>
        <dt className="text-term-dim">created</dt>
        <dd className="text-term-fg">{fmt(t.created_at)}</dd>
        <dt className="text-term-dim">last active</dt>
        <dd className="text-term-fg">{fmt(t.last_active_at)}</dd>
      </dl>
      <div className="flex flex-wrap gap-2">
        {t.status === "pending" && (
          <button type="button" className={btn} disabled={busy} onClick={() => onAction(t, "approve")}>
            approve
          </button>
        )}
        {(t.status === "active" || t.status === "pending") && (
          <button type="button" className={btn} disabled={busy} onClick={() => onAction(t, "suspend")}>
            suspend…
          </button>
        )}
        {t.status === "suspended" && (
          <button type="button" className={btn} disabled={busy} onClick={() => onAction(t, "unsuspend")}>
            unsuspend
          </button>
        )}
        {!t.email_verified && t.status !== "deleted" && (
          <button type="button" className={btn} disabled={busy} onClick={() => onAction(t, "resend-verification")}>
            resend verification
          </button>
        )}
        {t.status !== "deleted" && (
          <button type="button" className={danger} disabled={busy} onClick={() => onAction(t, "delete")}>
            delete…
          </button>
        )}
      </div>
    </li>
  );
}

function TenantList({ load, empty }: { load: () => Promise<PlatformTenant[]>; empty: string }) {
  const { data, error, reload } = useLoad(load);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function act(t: PlatformTenant, a: TenantAction) {
    let reason: string | undefined;
    if (a === "suspend" || a === "delete") {
      const r = window.prompt(
        a === "delete"
          ? `Delete /b/${t.slug}? It goes offline now and is erased after 7 days. Reason (only you see it):`
          : `Suspend /b/${t.slug}? Reason (only you see it):`,
      );
      if (!r || !r.trim()) return;
      reason = r.trim();
    }
    setBusy(true);
    setNote(null);
    try {
      await platformTenantAction(t.id, a, reason);
      setNote(`${a.replace("-", " ")}: /b/${t.slug} done.`);
      reload();
    } catch (e) {
      setNote(errText(e, "That didn't work."));
    } finally {
      setBusy(false);
    }
  }

  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;
  return (
    <>
      {note && (
        <p role="status" className="text-term-amber text-xs mb-3">
          {note}
        </p>
      )}
      {data.length === 0 ? (
        <p className="text-term-dim text-sm">{empty}</p>
      ) : (
        <ul className="space-y-3">
          {data.map((t) => (
            <TenantCard key={t.id} t={t} onAction={act} busy={busy} />
          ))}
        </ul>
      )}
    </>
  );
}

function Invites() {
  const { data, error, reload } = useLoad(platformInvites);
  const [note, setNote] = useState("");
  const [days, setDays] = useState("30");
  const [code, setCode] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    try {
      setCode(await platformCreateInvite(note.trim(), Number(days) || 0));
      setNote("");
      reload();
    } catch (err) {
      setFormError(errText(err, "Could not create an invite."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form onSubmit={create} className="max-w-sm mb-6">
        <FormError message={formError} />
        <Field id="inv-note" label="note (who it's for)" value={note} onChange={(e) => setNote(e.target.value)} />
        <Field id="inv-days" label="valid for days (0 = forever)" type="number" min={0} max={365} value={days} onChange={(e) => setDays(e.target.value)} />
        <SubmitButton busy={busy}>create invite</SubmitButton>
      </form>
      {code && (
        <p role="status" className="text-sm mb-6 break-all">
          New code (shown once): <code className="text-term-bright">{code}</code>
        </p>
      )}
      {error && <Failed message={error} />}
      {!error && !data && <Loading />}
      {data && data.length === 0 && <p className="text-term-dim text-sm">No invites yet.</p>}
      {data && data.length > 0 && (
        <ul className="space-y-2">
          {data.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 border border-term-line2 rounded px-3 py-2 text-xs">
              <span className="text-term-fg">{i.note || "(no note)"}</span>
              <span className="text-term-dim">
                {i.used_at ? `used ${fmt(i.used_at)}` : `expires ${fmt(i.expires_at)}`}
              </span>
              {!i.used_at && (
                <button type="button" className={btn} onClick={() => platformRevokeInvite(i.id).then(reload, reload)}>
                  revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function Audit() {
  const { data, error } = useLoad(platformAudit);
  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;
  if (data.length === 0) return <p className="text-term-dim text-sm">No operator actions yet.</p>;
  return (
    <ul className="space-y-1 text-xs">
      {data.map((a, n) => (
        <li key={n} className="border-b border-term-line py-1.5 flex flex-wrap gap-x-3">
          <span className="text-term-dim">{fmt(a.at)}</span>
          <span className="text-term-fg">{a.actor ?? "?"}</span>
          <span className="text-term-bright">{a.action}</span>
          {a.tenant && <span className="text-term-fg">/b/{a.tenant}</span>}
          {a.detail && <span className="text-term-dim break-all">— {a.detail}</span>}
        </li>
      ))}
    </ul>
  );
}

export default function PlatformPage() {
  const [me, setMe] = useState<{ email: string } | null | "anon">(null);
  const [tab, setTab] = useState<Tab>("tenants");

  useEffect(() => {
    platformMe()
      .then(setMe)
      .catch(() => setMe("anon"));
  }, []);

  if (me === "anon") return <Navigate to="/platform/login" replace />;
  if (me === null) {
    return (
      <div role="status" className="fixed inset-0 flex items-center justify-center text-term-dim text-sm">
        loading…
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black px-4 py-6 md:px-8">
      <div className="mx-auto max-w-5xl">
        <header className="flex flex-wrap items-center justify-between gap-3 mb-5">
          <div>
            <div className="text-term-amber text-xs">// mebot platform</div>
            <h1 className="text-term-bright text-lg">Operator console</h1>
          </div>
          <div className="flex items-center gap-3 text-xs text-term-dim">
            <span className="break-all">{me.email}</span>
            <button type="button" className={btn} onClick={() => platformLogout().finally(() => setMe("anon"))}>
              log out
            </button>
          </div>
        </header>
        <nav role="tablist" className="flex flex-wrap gap-2 mb-5">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={`${btn} ${tab === t.id ? "border-term-bright text-term-bright" : ""}`}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <section role="tabpanel">
          {tab === "tenants" && <TenantList load={platformTenants} empty="No tenants yet." />}
          {tab === "signups" && <TenantList load={platformSignups} empty="Nobody is waiting for approval." />}
          {tab === "invites" && <Invites />}
          {tab === "audit" && <Audit />}
        </section>
      </div>
    </div>
  );
}
