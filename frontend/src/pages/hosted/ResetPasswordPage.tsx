import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CenteredCard, Field, FormError, SubmitButton } from "../../components/AuthForm";
import { ApiError, confirmPasswordReset, requestPasswordReset } from "../../lib/api";

const MIN_PASSWORD = 10;

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Something went wrong. Please try again.";
}

function RequestForm() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await requestPasswordReset(email);
      setSent(true);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <p className="text-term-fg text-sm">
        If <strong>{email}</strong> has an account, a reset link is on its way. It works once,
        for 30 minutes.
      </p>
    );
  }
  return (
    <form onSubmit={submit}>
      <FormError message={error} />
      <Field
        id="rp-email"
        label="e-mail"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <SubmitButton busy={busy}>send reset link</SubmitButton>
    </form>
  );
}

function NewPasswordForm({ token }: { token: string }) {
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pw.length < MIN_PASSWORD) return setError(`At least ${MIN_PASSWORD} characters.`);
    if (pw !== confirm) return setError("The passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      await confirmPasswordReset(token, pw);
      setDone(true);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <p className="text-term-fg text-sm">
        Password changed; you were signed out everywhere.{" "}
        <Link to="/admin/login" className="text-term-bright underline">
          Log in
        </Link>
      </p>
    );
  }
  return (
    <form onSubmit={submit}>
      <FormError message={error} />
      <Field
        id="rp-new"
        label="new password"
        type="password"
        autoComplete="new-password"
        value={pw}
        hint={`At least ${MIN_PASSWORD} characters.`}
        onChange={(e) => setPw(e.target.value)}
      />
      <Field
        id="rp-confirm"
        label="confirm new password"
        type="password"
        autoComplete="new-password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
      />
      <SubmitButton busy={busy}>set password</SubmitButton>
    </form>
  );
}

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  return (
    <CenteredCard title="// reset password" heading={token ? "Choose a new password" : "Forgot your password?"}>
      {token ? <NewPasswordForm token={token} /> : <RequestForm />}
    </CenteredCard>
  );
}
