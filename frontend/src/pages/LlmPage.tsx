import { useEffect, useState } from "react";
import { FormError } from "../components/AuthForm";
import { AdminSection } from "../components/admin/AdminLayout";
import LlmForm, {
  emptyLlm,
  TestStatus,
  toLlmInput,
  validateLlm,
  type LlmErrors,
  type LlmFormValue,
  type TestState,
} from "../components/LlmForm";
import {
  adminLlmModels,
  getAdminProviders,
  getLlm,
  saveLlm,
  testLlm,
  type LlmConfigView,
  type LlmProvider,
} from "../lib/api";

const btn =
  "flex-1 border font-mono text-sm py-2.5 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-40 disabled:cursor-not-allowed";

function fromView(v: LlmConfigView): LlmFormValue {
  return {
    ...emptyLlm,
    provider: v.provider ?? "",
    model: v.model ?? "",
    base_url: v.base_url ?? "",
  };
}

// Admin -> AI Provider. The saved key is never sent to the browser; leaving the key
// field empty keeps it (for the same provider).
export default function LlmPage() {
  const [cfg, setCfg] = useState<LlmConfigView | null>(null);
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [form, setForm] = useState<LlmFormValue>(emptyLlm);
  const [errors, setErrors] = useState<LlmErrors>({});
  const [test, setTest] = useState<TestState>({ kind: "idle" });
  const [loadError, setLoadError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getLlm()
      .then((v) => {
        setCfg(v);
        setForm(fromView(v));
      })
      .catch((e: Error) => setLoadError(e.message || "could not load settings"));
    getAdminProviders()
      .then(setProviders)
      .catch(() => setProviders([]));
  }, []);

  const sameProviderWithKey = !!cfg?.has_key && cfg.provider === form.provider;
  const provider = providers.find((p) => p.id === form.provider);

  function change(v: LlmFormValue) {
    setForm(v);
    setTest({ kind: "idle" });
    setNote(null);
  }

  function check(): boolean {
    const e = validateLlm(form, provider, sameProviderWithKey);
    setErrors(e);
    return !Object.keys(e).length;
  }

  async function runTest() {
    if (!check()) return;
    setTest({ kind: "running" });
    try {
      const r = await testLlm(toLlmInput(form));
      setTest({ kind: "ok", latencyMs: r.latency_ms });
    } catch (e) {
      setTest({ kind: "failed", message: (e as Error).message || "Test failed." });
    }
  }

  async function save() {
    if (!check()) return;
    setSaving(true);
    setNote(null);
    setTest({ kind: "idle" });
    try {
      const v = await saveLlm(toLlmInput(form));
      setCfg(v);
      setForm(fromView(v));
      setNote("saved ✓ — tested and in use for new messages");
    } catch (e) {
      setTest({ kind: "failed", message: (e as Error).message || "Save failed." });
    } finally {
      setSaving(false);
    }
  }

  const keyHint = sameProviderWithKey
    ? "Leave empty to keep the saved key."
    : "Your own key. It is stored encrypted and never shown again.";

  return (
    <AdminSection
      title="AI Provider"
      intro="Your own AI account. mebot never provides or shares a key."
    >
      <FormError message={loadError} />
      {cfg && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs my-4">
          <dt className="text-term-dim">provider</dt>
          <dd className="text-term-fg">{cfg.provider ?? "not set"}</dd>
          <dt className="text-term-dim">model</dt>
          <dd className="text-term-fg">{cfg.model ?? "—"}</dd>
          <dt className="text-term-dim">key</dt>
          <dd className="text-term-fg font-mono">
            {cfg.has_key && cfg.api_key_last4 ? `••••${cfg.api_key_last4}` : "none"}
          </dd>
          <dt className="text-term-dim">last test</dt>
          <dd className={cfg.last_test_ok === false ? "text-term-err" : "text-term-fg"}>
            {cfg.last_test_ok === null
              ? "never"
              : `${cfg.last_test_ok ? "passed" : "failed"}${
                  cfg.last_tested_at ? " · " + new Date(cfg.last_tested_at).toLocaleString() : ""
                }`}
          </dd>
        </dl>
      )}
      {cfg?.status === "undecryptable" && (
        <p role="alert" className="text-term-err text-xs mb-3">
          The saved key can no longer be decrypted (the server's SECRET_KEY changed). Enter it
          again.
        </p>
      )}
      <LlmForm
        idPrefix="admin-llm"
        providers={providers}
        value={form}
        onChange={change}
        errors={errors}
        keyHint={keyHint}
        loadModels={(v) => adminLlmModels(toLlmInput(v))}
      />
      <TestStatus state={test} />
      {note && (
        <div role="status" className="text-term-bright text-xs mb-3">
          {note}
        </div>
      )}
      <div className="flex gap-3">
        <button
          type="button"
          onClick={runTest}
          disabled={test.kind === "running" || saving}
          className={
            btn + " border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright"
          }
        >
          test
        </button>
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className={btn + " border-term-bright text-term-bright hover:bg-term-bright/10"}
        >
          {saving ? "testing & saving…" : "save"}
        </button>
      </div>
    </AdminSection>
  );
}
