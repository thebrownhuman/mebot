// Shared building blocks for the setup and login screens, in the terminal/orb style.

export function CenteredCard({
  title,
  heading,
  children,
}: {
  title: string;
  heading?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black px-4 py-10">
      <div className="mx-auto w-full max-w-md border border-term-line2 bg-term-panel rounded-xl p-6">
        <div className="text-term-amber text-sm mb-1">{title}</div>
        {heading && <h1 className="text-term-bright text-lg mb-4">{heading}</h1>}
        {children}
      </div>
    </div>
  );
}

const inputCls =
  "w-full bg-term-bg border rounded text-term-fg font-mono text-sm px-3 py-2 outline-none focus:border-term-bright";

export function Field({
  id,
  label,
  error,
  hint,
  ...input
}: {
  id: string;
  label: string;
  error?: string;
  hint?: React.ReactNode;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  const describedBy = [error && `${id}-error`, hint && `${id}-hint`].filter(Boolean).join(" ");
  return (
    <div className="mb-4">
      <label htmlFor={id} className="block text-xs text-term-dim mb-1">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        className={`${inputCls} ${error ? "border-term-err" : "border-term-line2"}`}
        {...input}
      />
      {hint && (
        <div id={`${id}-hint`} className="text-term-dim text-xs mt-1">
          {hint}
        </div>
      )}
      {error && (
        <div id={`${id}-error`} className="text-term-err text-xs mt-1">
          {error}
        </div>
      )}
    </div>
  );
}

export function SubmitButton({ busy, children }: { busy: boolean; children: React.ReactNode }) {
  return (
    <button
      type="submit"
      disabled={busy}
      aria-busy={busy}
      className="w-full mt-2 border border-term-bright text-term-bright font-mono text-sm py-2.5 rounded hover:bg-term-bright/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-50 disabled:cursor-wait"
    >
      {busy ? "working…" : children}
    </button>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="text-term-err text-sm mb-3">
      {message}
    </div>
  );
}
