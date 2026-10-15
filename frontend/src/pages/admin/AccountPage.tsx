import { useState } from "react";
import { Field, FormError, SubmitButton } from "../../components/AuthForm";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import { changePassword } from "../../lib/api";

const MIN_PASSWORD = 10;

export default function AccountPage() {
  const { me, toast } = useAdmin();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    setError(null);
    if (next.length < MIN_PASSWORD) return setError(`Use at least ${MIN_PASSWORD} characters.`);
    if (next !== confirm) return setError("Passwords do not match.");
    setBusy(true);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      toast("Password changed — other devices were signed out");
    } catch (e) {
      setError((e as Error).message || "Could not change password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AdminSection title="Account" intro={`Signed in as ${me.email}.`}>
      <form onSubmit={submit} className="max-w-sm">
        <h2 className="text-term-fg text-sm mb-3">Change password</h2>
        <FormError message={error} />
        <Field
          id="acct-current"
          label="current password"
          type="password"
          autoComplete="current-password"
          required
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <Field
          id="acct-new"
          label="new password"
          type="password"
          autoComplete="new-password"
          required
          value={next}
          hint={`At least ${MIN_PASSWORD} characters.`}
          onChange={(e) => setNext(e.target.value)}
        />
        <Field
          id="acct-confirm"
          label="confirm new password"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <SubmitButton busy={busy}>change password</SubmitButton>
      </form>
    </AdminSection>
  );
}
