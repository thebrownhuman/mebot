import { useEffect, useState } from "react";
import { CenteredCard, Field, FormError, SubmitButton } from "../components/AuthForm";
import LlmForm, {
  emptyLlm,
  TestStatus,
  toLlmInput,
  validateLlm,
  type LlmErrors,
  type LlmFormValue,
  type TestState,
} from "../components/LlmForm";
import { useSetup } from "../components/SetupGate";
import { TELEMETRY_DOCS, WhatIsSent } from "../components/admin/TelemetryText";
import {
  ApiError,
  cleanLlm,
  getSetupProviders,
  runSetup,
  setupLlmModels,
  setupLlmTest,
  type LlmProvider,
} from "../lib/api";

const SLUG_RE = /^[a-z0-9-]{3,40}$/;
const RESERVED = new Set(["admin", "setup", "api", "widget", "assets"]);
const MIN_PASSWORD = 10;
const STEPS = ["account", "AI provider", "your bot"] as const;

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

type AccountErrors = Partial<Record<"email" | "password" | "confirm", string>>;
type BotErrors = Partial<Record<"bot_name" | "bot_slug", string>>;

const ghostBtn =
  "flex-1 border border-term-line2 text-term-dim font-mono text-sm py-2.5 rounded hover:text-term-fg hover:border-term-bright focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright";
const primaryBtn =
  "flex-1 border border-term-bright text-term-bright font-mono text-sm py-2.5 rounded hover:bg-term-bright/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-40 disabled:cursor-not-allowed";

export default function SetupPage() {
  const { markSetupDone } = useSetup();
  const [step, setStep] = useState(0);

  // step 1
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [accountErrors, setAccountErrors] = useState<AccountErrors>({});

  // step 2
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [llm, setLlm] = useState<LlmFormValue>(emptyLlm);
  const [llmErrors, setLlmErrors] = useState<LlmErrors>({});
  const [test, setTest] = useState<TestState>({ kind: "idle" });

  // step 3
  const [botName, setBotName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [consent, setConsent] = useState(false);
  const [showSent, setShowSent] = useState(false);
  const [botErrors, setBotErrors] = useState<BotErrors>({});

  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getSetupProviders()
      .then(setProviders)
      .catch(() => setProviders([]));
  }, []);

  function nextFromAccount() {
    const e: AccountErrors = {};
    if (!/^\S+@\S+\.\S+$/.test(email)) e.email = "Enter a valid email.";
    if (password.length < MIN_PASSWORD) e.password = `Use at least ${MIN_PASSWORD} characters.`;
    else if (password.length > 256) e.password = "Use at most 256 characters.";
    if (confirm !== password) e.confirm = "Passwords do not match.";
    setAccountErrors(e);
    if (!Object.keys(e).length) setStep(1);
  }

  function changeLlm(v: LlmFormValue) {
    setLlm(v);
    setTest({ kind: "idle" }); // any change needs a fresh test
  }

  async function runTest() {
    const errs = validateLlm(
      llm,
      providers.find((p) => p.id === llm.provider),
    );
    setLlmErrors(errs);
    if (Object.keys(errs).length) return;
    setTest({ kind: "running" });
    try {
      const r = await setupLlmTest(toLlmInput(llm), setupToken || undefined);
      setTest({ kind: "ok", latencyMs: r.latency_ms });
    } catch (e) {
      setTest({ kind: "failed", message: (e as Error).message || "Test failed." });
    }
  }

  async function finish(ev: React.FormEvent) {
    ev.preventDefault();
    const e: BotErrors = {};
    if (!botName.trim()) e.bot_name = "Give your bot a name.";
    if (!SLUG_RE.test(slug)) e.bot_slug = "Use 3–40 lowercase letters, digits or hyphens.";
    else if (RESERVED.has(slug)) e.bot_slug = `"${slug}" is reserved.`;
    setBotErrors(e);
    setFormError(null);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      await runSetup({
        email: email.trim(),
        password,
        bot_name: botName.trim(),
        bot_slug: slug,
        registration_consent: consent,
        llm: cleanLlm(toLlmInput(llm)),
        ...(setupToken ? { setup_token: setupToken } : {}),
      });
      markSetupDone("/admin");
    } catch (err) {
      const apiErr = err as ApiError;
      if (apiErr.status === 409) {
        markSetupDone("/admin/login");
        return;
      }
      if (apiErr.code === "LLM_TEST_FAILED") {
        setTest({ kind: "failed", message: apiErr.message });
        setStep(1);
        return;
      }
      const fields = new Set((apiErr.details ?? []).map((d) => d.field.split(".")[0]));
      if (fields.has("email") || fields.has("password")) setStep(0);
      else if (fields.has("llm")) setStep(1);
      for (const d of apiErr.details ?? []) {
        if (d.field === "bot_name" || d.field === "bot_slug") e[d.field] = d.message;
      }
      setBotErrors(e);
      setFormError(apiErr.message || "Setup failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <CenteredCard title="// first run" heading="Set up your mebot">
      <ol className="flex gap-2 text-xs mb-5" aria-label="setup progress">
        {STEPS.map((s, i) => (
          <li
            key={s}
            aria-current={i === step ? "step" : undefined}
            className={
              "flex-1 border-t-2 pt-1 " +
              (i < step
                ? "border-term-bright text-term-dim"
                : i === step
                  ? "border-term-bright text-term-bright"
                  : "border-term-line2 text-term-dim")
            }
          >
            {i + 1}. {s}
          </li>
        ))}
      </ol>
      <FormError message={formError} />

      {step === 0 && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            nextFromAccount();
          }}
          noValidate
        >
          <Field
            id="setup-email"
            label="email"
            type="email"
            autoComplete="email"
            autoFocus
            value={email}
            error={accountErrors.email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Field
            id="setup-password"
            label="password"
            type="password"
            autoComplete="new-password"
            value={password}
            error={accountErrors.password}
            hint={`At least ${MIN_PASSWORD} characters.`}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Field
            id="setup-confirm"
            label="confirm password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            error={accountErrors.confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          <Field
            id="setup-token"
            label="setup token (only if your server sets SETUP_TOKEN)"
            type="password"
            autoComplete="off"
            value={setupToken}
            onChange={(e) => setSetupToken(e.target.value)}
          />
          <div className="flex gap-3 mt-2">
            <button type="submit" className={primaryBtn}>
              next
            </button>
          </div>
        </form>
      )}

      {step === 1 && (
        <div>
          <p className="text-term-fg text-xs leading-relaxed mb-4">
            mebot uses <em>your own</em> AI account — the project never provides or shares a key.
            Pick a provider, paste your key and test it.
          </p>
          <LlmForm
            idPrefix="setup-llm"
            providers={providers}
            value={llm}
            onChange={changeLlm}
            errors={llmErrors}
            loadModels={(v) => setupLlmModels(toLlmInput(v), setupToken || undefined)}
          />
          <TestStatus state={test} />
          <button
            type="button"
            onClick={runTest}
            disabled={test.kind === "running"}
            className={primaryBtn + " w-full mb-3"}
          >
            test connection
          </button>
          <div className="flex gap-3">
            <button type="button" onClick={() => setStep(0)} className={ghostBtn}>
              back
            </button>
            <button
              type="button"
              onClick={() => setStep(2)}
              disabled={test.kind !== "ok"}
              className={primaryBtn}
            >
              next
            </button>
          </div>
        </div>
      )}

      {step === 2 && (
        <form onSubmit={finish} noValidate>
          <Field
            id="setup-bot-name"
            label="bot name"
            value={botName}
            error={botErrors.bot_name}
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
            error={botErrors.bot_slug}
            hint="Lowercase letters, digits and hyphens."
            onChange={(e) => {
              setSlugEdited(true);
              setSlug(e.target.value);
            }}
          />
          <div className="flex gap-2 items-start mb-2">
            <input
              id="setup-consent"
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              className="mt-1 accent-term-bright"
            />
            <label htmlFor="setup-consent" className="text-xs text-term-fg leading-relaxed">
              Register this install with the mebot project (sends your email, site URL and version)
              to get security alerts and updates.
            </label>
          </div>
          <div className="mb-4 text-xs">
            <button
              type="button"
              aria-expanded={showSent}
              aria-controls="setup-sent"
              onClick={() => setShowSent((v) => !v)}
              className="text-term-bright underline"
            >
              What's sent?
            </button>
            {showSent && (
              <div id="setup-sent" className="mt-2 border border-term-line2 rounded p-3">
                <WhatIsSent />
                <a
                  href={TELEMETRY_DOCS}
                  target="_blank"
                  rel="noreferrer"
                  className="text-term-bright underline block mt-2"
                >
                  Read the details in the README
                </a>
              </div>
            )}
          </div>
          <div className="flex gap-3">
            <button type="button" onClick={() => setStep(1)} className={ghostBtn}>
              back
            </button>
            <div className="flex-1">
              <SubmitButton busy={busy}>finish setup</SubmitButton>
            </div>
          </div>
        </form>
      )}
    </CenteredCard>
  );
}
