import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CenteredCard, Field, FormError, SubmitButton } from "../../components/AuthForm";
import Turnstile from "../../components/Turnstile";
import { ApiError, getHostedConfig, signup, type HostedConfig } from "../../lib/api";

const MIN_PASSWORD = 10;
const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{1,30})[a-z0-9]$/;

export function slugProblem(slug: string): string | null {
  if (!SLUG_RE.test(slug) || slug.includes("--")) {
    return "3-32 lowercase letters, digits or single hyphens (not at the ends).";
  }
  return null;
}

function suggestSlug(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32);
}

type Errors = Partial<Record<"email" | "password" | "bot_name" | "slug" | "invite_code", string>>;

export default function SignupPage() {
  const [cfg, setCfg] = useState<HostedConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [invite, setInvite] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [errors, setErrors] = useState<Errors>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [queued, setQueued] = useState(false);

  useEffect(() => {
    getHostedConfig()
      .then(setCfg)
      .catch((e: Error) => setLoadError(e.message || "Could not load sign-up."));
  }, []);

  if (loadError) {
    return (
      <CenteredCard title="// sign up">
        <p role="alert" className="text-term-err text-sm">
          {loadError}
        </p>
      </CenteredCard>
    );
  }
  if (!cfg) {
    return (
      <div role="status" className="fixed inset-0 flex items-center justify-center text-term-dim text-sm">
        loading…
      </div>
    );
  }
  if (cfg.signup_mode === "closed") {
    return (
      <CenteredCard title="// sign up" heading="Sign-up is closed">
        <p className="text-term-dim text-sm">
          New accounts aren't being created right now.{" "}
          <Link to="/admin/login" className="text-term-bright underline">
            Log in
          </Link>{" "}
          if you already have one.
        </p>
      </CenteredCard>
    );
  }
  if (done) {
    return (
      <CenteredCard title="// sign up" heading="Check your e-mail">
        <p className="text-term-fg text-sm">
          We sent a link to <strong>{email}</strong>. Open it to confirm your address
          {queued
            ? ". Your sign-up also needs approval; we'll e-mail you once it's approved."
            : ", then log in to set up your assistant."}
        </p>
      </CenteredCard>
    );
  }

  function validate(): Errors {
    const e: Errors = {};
    if (!/^\S+@\S+\.\S+$/.test(email)) e.email = "Enter a valid e-mail address.";
    if (password.length < MIN_PASSWORD) e.password = `At least ${MIN_PASSWORD} characters.`;
    if (!name.trim()) e.bot_name = "Enter your name.";
    const sp = slugProblem(slug);
    if (sp) e.slug = sp;
    return e;
  }

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    setError(null);
    const e = validate();
    setErrors(e);
    if (Object.keys(e).length) return;
    if (!token) {
      setError("Please complete the bot check.");
      return;
    }
    setBusy(true);
    try {
      const res = await signup({
        email,
        password,
        bot_name: name.trim(),
        slug,
        invite_code: invite.trim() || undefined,
        turnstile_token: token,
      });
      setQueued(Boolean(res?.approval_required));
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "SLUG_TAKEN") setErrors({ slug: err.message });
        else if (err.code === "INVITE_INVALID") setErrors({ invite_code: err.message });
        else if (err.details.length) {
          setErrors(Object.fromEntries(err.details.map((d) => [d.field, d.message])) as Errors);
        } else setError(err.message);
      } else setError("Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <CenteredCard title="// sign up" heading="Create your assistant">
      <form onSubmit={submit} noValidate>
        <FormError message={error} />
        <Field
          id="su-name"
          label="your name"
          autoComplete="name"
          value={name}
          error={errors.bot_name}
          onChange={(e) => {
            setName(e.target.value);
            if (!slugTouched) setSlug(suggestSlug(e.target.value));
          }}
        />
        <Field
          id="su-slug"
          label="address"
          value={slug}
          error={errors.slug}
          hint={<>Your page: /b/{slug || "your-name"}. You can change it later.</>}
          onChange={(e) => {
            setSlugTouched(true);
            setSlug(e.target.value.toLowerCase());
          }}
        />
        <Field
          id="su-email"
          label="e-mail"
          type="email"
          autoComplete="email"
          value={email}
          error={errors.email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          id="su-password"
          label="password"
          type="password"
          autoComplete="new-password"
          value={password}
          error={errors.password}
          hint={`At least ${MIN_PASSWORD} characters.`}
          onChange={(e) => setPassword(e.target.value)}
        />
        {cfg.signup_mode === "invite" && (
          <Field
            id="su-invite"
            label="invite code (optional)"
            hint="Without one, your sign-up waits for approval."
            value={invite}
            error={errors.invite_code}
            onChange={(e) => setInvite(e.target.value)}
          />
        )}
        {cfg.turnstile_site_key && (
          <div className="mb-4">
            <Turnstile siteKey={cfg.turnstile_site_key} onToken={setToken} onError={setError} />
          </div>
        )}
        <SubmitButton busy={busy}>create account</SubmitButton>
        <p className="text-term-dim text-xs mt-4">
          Already have an account?{" "}
          <Link to="/admin/login" className="text-term-bright underline">
            Log in
          </Link>
        </p>
      </form>
    </CenteredCard>
  );
}
