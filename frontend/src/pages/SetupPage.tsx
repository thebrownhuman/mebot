import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CenteredCard, Field, FormError, SubmitButton } from "../components/AuthForm";
import { useSetup } from "../components/SetupGate";
import { ApiError, runSetup } from "../lib/api";

const SLUG_RE = /^[a-z0-9-]{3,40}$/;
const RESERVED = new Set(["admin", "setup", "api", "widget", "assets"]);
const MIN_PASSWORD = 10;
// TODO: point at the public repo once it exists (README "Telemetry & registration").
const TELEMETRY_DOCS = "https://github.com/shivansh-ge/mebot#telemetry--registration";

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

type Errors = Partial<Record<"email" | "password" | "confirm" | "bot_name" | "bot_slug", string>>;

function validate(f: {
  email: string;
  password: string;
  confirm: string;
  botName: string;
  slug: string;
}): Errors {
  const e: Errors = {};
  if (!/^\S+@\S+\.\S+$/.test(f.email)) e.email = "Enter a valid email.";
  if (f.password.length < MIN_PASSWORD) e.password = `Use at least ${MIN_PASSWORD} characters.`;
  else if (f.password.length > 256) e.password = "Use at most 256 characters.";
  if (f.confirm !== f.password) e.confirm = "Passwords do not match.";
  if (!f.botName.trim()) e.bot_name = "Give your bot a name.";
  if (!SLUG_RE.test(f.slug)) e.bot_slug = "Use 3–40 lowercase letters, digits or hyphens.";
  else if (RESERVED.has(f.slug)) e.bot_slug = `"${f.slug}" is reserved.`;
  return e;
}

export default function SetupPage() {
  const navigate = useNavigate();
  const { markSetupDone } = useSetup();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [botName, setBotName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [consent, setConsent] = useState(false);
  const [setupToken, setSetupToken] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    const found = validate({ email, password, confirm, botName, slug });
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      await runSetup({
        email: email.trim(),
        password,
        bot_name: botName.trim(),
        bot_slug: slug,
        registration_consent: consent,
        ...(setupToken ? { setup_token: setupToken } : {}),
      });
      markSetupDone();
      navigate("/admin", { replace: true });
    } catch (e) {
      const err = e as ApiError;
      const fieldErrors: Errors = {};
      for (const d of err.details ?? []) {
        if (d.field in { email: 1, password: 1, bot_name: 1, bot_slug: 1 }) {
          fieldErrors[d.field as keyof Errors] = d.message;
        }
      }
      setErrors(fieldErrors);
      setFormError(err.message || "Setup failed.");
      if (err.status === 409) {
        markSetupDone();
        navigate("/admin/login", { replace: true });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <CenteredCard title="// first run" heading="Set up your mebot">
      <form onSubmit={submit} noValidate>
        <FormError message={formError} />
        <Field
          id="setup-email"
          label="email"
          type="email"
          autoComplete="email"
          autoFocus
          value={email}
          error={errors.email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          id="setup-password"
          label="password"
          type="password"
          autoComplete="new-password"
          value={password}
          error={errors.password}
          hint={`At least ${MIN_PASSWORD} characters.`}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Field
          id="setup-confirm"
          label="confirm password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          error={errors.confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <Field
          id="setup-bot-name"
          label="bot name"
          value={botName}
          error={errors.bot_name}
          hint="Usually your name — shown to visitors."
          onChange={(e) => {
            setBotName(e.target.value);
            if (!slugEdited) setSlug(slugify(e.target.value));
          }}
        />
        <Field
          id="setup-slug"
          label="slug"
          value={slug}
          error={errors.bot_slug}
          hint="Lowercase letters, digits and hyphens."
          onChange={(e) => {
            setSlugEdited(true);
            setSlug(e.target.value);
          }}
        />
        <Field
          id="setup-token"
          label="setup token (only if your server sets SETUP_TOKEN)"
          type="password"
          autoComplete="off"
          value={setupToken}
          onChange={(e) => setSetupToken(e.target.value)}
        />
        <div className="flex gap-2 items-start mb-4">
          <input
            id="setup-consent"
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            className="mt-1 accent-term-bright"
          />
          <label htmlFor="setup-consent" className="text-xs text-term-fg leading-relaxed">
            Register this install with the mebot project (sends your email, site URL and
            version) to get security alerts and updates.{" "}
            <a
              href={TELEMETRY_DOCS}
              target="_blank"
              rel="noreferrer"
              className="text-term-bright underline"
            >
              What is sent?
            </a>
          </label>
        </div>
        <SubmitButton busy={busy}>finish setup</SubmitButton>
      </form>
    </CenteredCard>
  );
}
