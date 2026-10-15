import { useState } from "react";
import type { LlmInput, LlmProvider } from "../lib/api";
import { Field } from "./AuthForm";

// Provider / key / model / base URL fields, shared by the setup wizard and the
// Admin -> AI Provider page. The parent owns the value and the Test button.

export interface LlmFormValue {
  provider: string;
  model: string;
  api_key: string;
  base_url: string;
}

export const emptyLlm: LlmFormValue = { provider: "", model: "", api_key: "", base_url: "" };

export function toLlmInput(v: LlmFormValue): LlmInput {
  return { provider: v.provider, model: v.model, api_key: v.api_key, base_url: v.base_url };
}

export type LlmErrors = Partial<Record<keyof LlmFormValue, string>>;

export function validateLlm(v: LlmFormValue, p: LlmProvider | undefined, keyOptional = false) {
  const e: LlmErrors = {};
  if (!p) e.provider = "Choose a provider.";
  if (!v.model.trim()) e.model = "Choose or type a model.";
  if (p?.key_required && !v.api_key.trim() && !keyOptional)
    e.api_key = `${p.name} needs your API key.`;
  if (p?.base_url_required && !v.base_url.trim()) e.base_url = "Enter your API's base URL.";
  if (v.base_url.trim() && !/^https?:\/\/\S+$/.test(v.base_url.trim()))
    e.base_url = "Base URL must start with http:// or https://";
  return e;
}

const selectCls =
  "w-full bg-term-bg border border-term-line2 rounded text-term-fg font-mono text-sm px-3 py-2 outline-none focus:border-term-bright";

export default function LlmForm({
  idPrefix,
  providers,
  value,
  onChange,
  errors = {},
  keyHint,
  loadModels,
}: {
  idPrefix: string;
  providers: LlmProvider[];
  value: LlmFormValue;
  onChange: (v: LlmFormValue) => void;
  errors?: LlmErrors;
  keyHint?: string;
  loadModels: (v: LlmFormValue) => Promise<string[]>;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelsNote, setModelsNote] = useState<string | null>(null);
  const provider = providers.find((p) => p.id === value.provider);
  const set = (patch: Partial<LlmFormValue>) => onChange({ ...value, ...patch });
  const suggestions = Array.from(new Set([...(provider?.suggested_models ?? []), ...models]));
  const showBaseUrl = provider && (provider.base_url_required || provider.id === "ollama");

  async function fetchModels() {
    setLoadingModels(true);
    setModelsNote(null);
    try {
      const list = await loadModels(value);
      setModels(list);
      setModelsNote(
        list.length ? `${list.length} models found` : "no list available — type a model name",
      );
    } catch (e) {
      setModelsNote((e as Error).message || "could not load models");
    } finally {
      setLoadingModels(false);
    }
  }

  return (
    <div>
      <div className="mb-4">
        <label htmlFor={`${idPrefix}-provider`} className="block text-xs text-term-dim mb-1">
          provider
        </label>
        <select
          id={`${idPrefix}-provider`}
          value={value.provider}
          aria-invalid={errors.provider ? true : undefined}
          onChange={(e) => {
            setModels([]);
            setModelsNote(null);
            onChange({ ...value, provider: e.target.value, model: "", base_url: "" });
          }}
          className={selectCls}
        >
          <option value="">Choose a provider…</option>
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        {errors.provider && <div className="text-term-err text-xs mt-1">{errors.provider}</div>}
      </div>

      {provider && (
        <>
          {(provider.key_required || provider.id === "openai_compatible") && (
            <Field
              id={`${idPrefix}-key`}
              label={provider.key_required ? "API key" : "API key (optional)"}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={value.api_key}
              error={errors.api_key}
              hint={
                <>
                  {keyHint ?? "Your own key. It is stored encrypted and never shown again."}{" "}
                  {provider.key_url && (
                    <a
                      href={provider.key_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-term-bright underline"
                    >
                      Get a key
                    </a>
                  )}
                </>
              }
              onChange={(e) => set({ api_key: e.target.value })}
            />
          )}
          {showBaseUrl && (
            <Field
              id={`${idPrefix}-base-url`}
              label={provider.base_url_required ? "base URL" : "base URL (optional)"}
              placeholder={provider.default_base_url ?? "https://example.com/v1"}
              value={value.base_url}
              error={errors.base_url}
              onChange={(e) => set({ base_url: e.target.value })}
            />
          )}
          <Field
            id={`${idPrefix}-model`}
            label="model"
            list={`${idPrefix}-models`}
            spellCheck={false}
            value={value.model}
            error={errors.model}
            hint={
              <>
                Pick a suggestion or type any model id.{" "}
                <button
                  type="button"
                  onClick={fetchModels}
                  disabled={loadingModels}
                  className="text-term-bright underline disabled:opacity-50"
                >
                  {loadingModels ? "loading…" : "load models"}
                </button>
                {modelsNote && <span className="ml-1">({modelsNote})</span>}
              </>
            }
            onChange={(e) => set({ model: e.target.value })}
          />
          <datalist id={`${idPrefix}-models`}>
            {suggestions.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </>
      )}
    </div>
  );
}

export function TestStatus({ state }: { state: TestState }) {
  if (state.kind === "idle") return null;
  if (state.kind === "running")
    return (
      <div role="status" className="text-term-dim text-xs mb-3">
        testing…
      </div>
    );
  if (state.kind === "ok")
    return (
      <div role="status" className="text-term-bright text-xs mb-3">
        ✓ connection works ({state.latencyMs} ms)
      </div>
    );
  return (
    <div role="alert" className="text-term-err text-sm mb-3">
      {state.message}
    </div>
  );
}

export type TestState =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "ok"; latencyMs: number }
  | { kind: "failed"; message: string };
