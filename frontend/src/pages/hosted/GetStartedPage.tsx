import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Field, FormError, SubmitButton } from "../../components/AuthForm";
import LlmForm, {
  emptyLlm,
  toLlmInput,
  validateLlm,
  type LlmErrors,
  type LlmFormValue,
} from "../../components/LlmForm";
import { AdminSection } from "../../components/admin/AdminLayout";
import {
  ApiError,
  adminLlmModels,
  getAdminProviders,
  getHostedAccount,
  hostedSetup,
  type LlmProvider,
} from "../../lib/api";

// Hosted mode: the per-tenant setup wizard (name, AI provider tested, profile basics).
export default function GetStartedPage() {
  const nav = useNavigate();
  const [providers, setProviders] = useState<LlmProvider[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [headline, setHeadline] = useState("");
  const [llm, setLlm] = useState<LlmFormValue>(emptyLlm);
  const [llmErrors, setLlmErrors] = useState<LlmErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([getAdminProviders(), getHostedAccount()])
      .then(([p, acct]) => {
        if (acct.setup_done) nav("/admin", { replace: true });
        setName(acct.bot_name);
        setProviders(p);
      })
      .catch((e: Error) => setLoadError(e.message || "Could not load setup."));
  }, [nav]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const errs = validateLlm(llm, providers?.find((p) => p.id === llm.provider));
    setLlmErrors(errs);
    if (!name.trim()) return setError("Enter your name.");
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      await hostedSetup({
        bot_name: name.trim(),
        full_name: name.trim(),
        headline: headline.trim() || undefined,
        llm: toLlmInput(llm),
      });
      nav("/admin", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Setup failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AdminSection title="Get started" intro="Three things and your assistant can go live.">
      {loadError && (
        <p role="alert" className="text-term-err text-sm">
          {loadError}
        </p>
      )}
      {!loadError && !providers && (
        <p role="status" className="text-term-dim text-sm">
          loading…
        </p>
      )}
      {providers && (
        <form onSubmit={submit} className="max-w-lg">
          <FormError message={error} />
          <h2 className="text-term-fg text-sm mb-3">1. You</h2>
          <Field id="gs-name" label="your name" value={name} onChange={(e) => setName(e.target.value)} />
          <Field
            id="gs-headline"
            label="headline (optional)"
            placeholder="Backend engineer, Python & Go"
            value={headline}
            onChange={(e) => setHeadline(e.target.value)}
          />
          <h2 className="text-term-fg text-sm mb-3 mt-6">2. Your AI provider</h2>
          <p className="text-term-dim text-xs mb-3">
            Your own key; it's tested before saving and stored encrypted.
          </p>
          <LlmForm
            idPrefix="gs"
            providers={providers}
            value={llm}
            onChange={setLlm}
            errors={llmErrors}
            loadModels={(v) => adminLlmModels(toLlmInput(v))}
          />
          <h2 className="text-term-fg text-sm mb-3 mt-6">3. Go live</h2>
          <SubmitButton busy={busy}>test key and finish</SubmitButton>
        </form>
      )}
    </AdminSection>
  );
}
