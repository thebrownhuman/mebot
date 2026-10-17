import { useEffect, useState } from "react";
import { slugProblem } from "../../pages/hosted/SignupPage";
import {
  ApiError,
  changeSlug,
  deleteHostedAccount,
  getHostedAccount,
  hostedExportUrl,
  type HostedAccount,
} from "../../lib/api";
import { Field, FormError, SubmitButton } from "../AuthForm";
import { useSetup } from "../SetupGate";
import { useAdmin } from "./AdminLayout";

const btn =
  "font-mono text-xs px-3 py-1.5 rounded border border-term-line2 text-term-fg hover:border-term-bright hover:text-term-bright";

// Hosted mode only: public address, data export, account deletion.
export default function HostedAccountSection() {
  const { hosted } = useSetup();
  const { toast } = useAdmin();
  const [acct, setAcct] = useState<HostedAccount | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [slug, setSlug] = useState("");
  const [slugError, setSlugError] = useState<string | null>(null);
  const [savingSlug, setSavingSlug] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [password, setPassword] = useState("");
  const [delError, setDelError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!hosted) return;
    getHostedAccount()
      .then((a) => {
        setAcct(a);
        setSlug(a.slug);
      })
      .catch((e: Error) => setLoadError(e.message || "Could not load your account."));
  }, [hosted]);

  if (!hosted) return null;
  if (loadError) {
    return (
      <p role="alert" className="text-term-err text-sm mb-6">
        {loadError}
      </p>
    );
  }
  if (!acct) {
    return (
      <p role="status" className="text-term-dim text-sm mb-6">
        loading…
      </p>
    );
  }

  async function saveSlug(e: React.FormEvent) {
    e.preventDefault();
    const problem = slugProblem(slug);
    if (problem) return setSlugError(problem);
    setSavingSlug(true);
    setSlugError(null);
    try {
      const a = await changeSlug(slug);
      setAcct(a);
      toast("Address changed. The old one redirects for 30 days.");
    } catch (err) {
      setSlugError(err instanceof ApiError ? err.message : "Could not change the address.");
    } finally {
      setSavingSlug(false);
    }
  }

  async function remove(e: React.FormEvent) {
    e.preventDefault();
    setDeleting(true);
    setDelError(null);
    try {
      await deleteHostedAccount(password);
      window.location.assign("/admin/login");
    } catch (err) {
      setDelError(err instanceof ApiError ? err.message : "Could not delete the account.");
      setDeleting(false);
    }
  }

  const url = acct.hosted_domain
    ? `https://${acct.slug}.${acct.hosted_domain}`
    : `${window.location.origin}${acct.public_path}`;

  return (
    <div className="mb-8 space-y-8 max-w-lg">
      <section>
        <h2 className="text-term-fg text-sm mb-2">Your page</h2>
        <p className="text-sm mb-3 break-all">
          <a href={url} className="text-term-bright underline">
            {url}
          </a>{" "}
          <span className="text-term-dim">
            ({acct.live ? "online" : "offline"} · plan: {acct.plan})
          </span>
        </p>
        <form onSubmit={saveSlug}>
          <Field
            id="ha-slug"
            label="address"
            value={slug}
            error={slugError ?? undefined}
            hint="Widgets keep working after a change; links to the old address redirect for 30 days."
            onChange={(e) => setSlug(e.target.value.toLowerCase())}
          />
          <SubmitButton busy={savingSlug}>change address</SubmitButton>
        </form>
      </section>
      <section>
        <h2 className="text-term-fg text-sm mb-2">Export</h2>
        <p className="text-term-dim text-xs mb-2">
          A zip of your profile, learned facts and conversations (JSON). Never your keys.
        </p>
        <a href={hostedExportUrl} className={btn} download>
          download export
        </a>
      </section>
      <section>
        <h2 className="text-term-err text-sm mb-2">Delete account</h2>
        <p className="text-term-dim text-xs mb-2">
          Your assistant goes offline now; everything is erased for good after 7 days. Export
          first if you want a copy.
        </p>
        {!confirming ? (
          <button type="button" className={btn} onClick={() => setConfirming(true)}>
            delete my account…
          </button>
        ) : (
          <form onSubmit={remove}>
            <FormError message={delError} />
            <Field
              id="ha-del-pw"
              label="password to confirm"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <SubmitButton busy={deleting}>permanently delete</SubmitButton>
          </form>
        )}
      </section>
    </div>
  );
}
