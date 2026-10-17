import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSetup } from "../components/SetupGate";
import { CenteredCard, Field, FormError, SubmitButton } from "../components/AuthForm";
import { login } from "../lib/api";

export default function LoginPage() {
  const navigate = useNavigate();
  const { hosted } = useSetup();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      navigate("/admin", { replace: true });
    } catch (e) {
      setError((e as Error).message || "Login failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <CenteredCard title="// admin access" heading="Log in">
      <form onSubmit={submit}>
        <FormError message={error} />
        <Field
          id="login-email"
          label="email"
          type="email"
          autoComplete="username"
          autoFocus
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          id="login-password"
          label="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <SubmitButton busy={busy}>log in</SubmitButton>
        {hosted && (
          <p className="text-term-dim text-xs mt-4 flex flex-wrap gap-x-4 gap-y-1">
            <Link to="/reset-password" className="text-term-bright underline">
              forgot password?
            </Link>
            <Link to="/signup" className="text-term-bright underline">
              create an account
            </Link>
          </p>
        )}
      </form>
      <p className="text-term-dim text-xs mt-4">
        Forgot your password? Run <code className="text-term-fg">python -m mebot.cli reset-password</code>{" "}
        on the server.
      </p>
    </CenteredCard>
  );
}
