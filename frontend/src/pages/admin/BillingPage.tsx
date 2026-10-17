import { useCallback, useEffect, useState } from "react";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import { inputCls } from "../../components/admin/fields";
import {
  ApiError,
  billingPortal,
  cancelSubscription,
  formatMoney,
  getBilling,
  getInvoices,
  saveGstin,
  startCheckout,
  type BillingInvoice,
  type BillingStatus,
  type BillingView,
} from "../../lib/api";

const btn =
  "font-mono text-xs px-3 py-1.5 rounded border border-term-line2 text-term-fg hover:border-term-bright hover:text-term-bright disabled:opacity-50";
const primary =
  "font-mono text-xs px-3 py-1.5 rounded border border-term-bright text-term-bright bg-term-bright/10 hover:bg-term-bright/20 disabled:opacity-50";

const STATUS_LABEL: Record<BillingStatus, string> = {
  none: "No plan",
  trialing: "Free trial",
  active: "Active",
  past_due: "Payment failed",
  cancelled: "Cancelled",
  inactive: "Inactive",
};

function day(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso));
}

function errText(e: unknown, fallback: string): string {
  return e instanceof ApiError || e instanceof Error ? e.message || fallback : fallback;
}

// What's going on, in one line, for the top of the page.
function Banner({ v }: { v: BillingView }) {
  if (v.status === "past_due") {
    return (
      <div role="alert" className="border border-term-err text-term-err rounded px-3 py-2 mb-4 text-xs">
        Your last payment failed. Your assistant stays online until {day(v.grace_until)} while the
        payment is retried — update your payment method to keep it online.
      </div>
    );
  }
  if (!v.serving) {
    return (
      <div role="alert" className="border border-term-amber/60 text-term-amber rounded px-3 py-2 mb-4 text-xs">
        Your assistant is offline for visitors until you subscribe. Your data is kept.
      </div>
    );
  }
  if (v.status === "cancelled") {
    return (
      <div role="status" className="border border-term-line2 rounded px-3 py-2 mb-4 text-xs text-term-dim">
        Cancelled — your assistant stays online until {day(v.current_period_end)}.
      </div>
    );
  }
  return null;
}

function Summary({ v }: { v: BillingView }) {
  const rows: [string, string][] = [["Status", STATUS_LABEL[v.status]]];
  if (v.plan_name && v.status !== "trialing") rows.push(["Plan", v.plan_name]);
  if (v.trial && v.status === "trialing") {
    rows.push(["Trial ends", `${day(v.trial.ends_at)} (${v.trial.days_left} days left)`]);
    rows.push(["Trial messages", `${v.trial.messages_used} of ${v.trial.messages_total} used`]);
  }
  if (v.status === "active" && v.current_period_end) rows.push(["Renews", day(v.current_period_end)]);
  if (v.comp_until) rows.push(["Free until", day(v.comp_until)]);
  rows.push([
    "Usage this period",
    `${v.usage.messages.toLocaleString()} messages · ${v.usage.tokens.toLocaleString()} tokens since ${day(v.usage.since)}`,
  ]);
  return (
    <section aria-labelledby="bill-plan-h" className="border border-term-line rounded-lg p-4 mb-6">
      <h2 id="bill-plan-h" className="text-term-fg text-sm mb-3">
        Your plan
      </h2>
      <dl className="grid grid-cols-1 sm:grid-cols-[10rem_1fr] gap-x-4 gap-y-1.5 text-xs">
        {rows.map(([k, val]) => (
          <div key={k} className="contents">
            <dt className="text-term-dim">{k}</dt>
            <dd className="text-term-fg break-words">{val}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Choose({ v }: { v: BillingView }) {
  const currencies = Array.from(new Set(v.offers.flatMap((o) => Object.keys(o.prices)))).sort();
  const [currency, setCurrency] = useState(currencies.includes("INR") ? "INR" : currencies[0] ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!v.can_checkout) return null;
  if (v.offers.length === 0) {
    return (
      <section className="border border-dashed border-term-line2 rounded-lg p-4 mb-6 text-xs text-term-dim">
        No plans are on sale yet. Please check back soon.
      </section>
    );
  }

  async function go(code: string) {
    setBusy(code);
    setError(null);
    try {
      window.location.assign(await startCheckout(code, currency));
    } catch (e) {
      setError(errText(e, "Could not start the checkout."));
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby="bill-choose-h" className="mb-6">
      <h2 id="bill-choose-h" className="text-term-fg text-sm mb-1">
        Subscribe
      </h2>
      <p className="text-term-dim text-xs mb-3">
        Payment happens on {currency === "INR" ? "Razorpay (UPI AutoPay or card)" : "Stripe"}'s
        secure page; mebot never sees your card or UPI details.
      </p>
      {currencies.length > 1 && (
        <fieldset className="mb-3">
          <legend className="text-xs text-term-dim mb-1">currency</legend>
          <div className="flex flex-wrap gap-2">
            {currencies.map((c) => (
              <label key={c} className="flex items-center gap-1.5 text-xs min-h-[44px] sm:min-h-0">
                <input
                  type="radio"
                  name="currency"
                  value={c}
                  checked={currency === c}
                  onChange={() => setCurrency(c)}
                />
                {c === "INR" ? "INR (India)" : c}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <ul className="grid gap-3 sm:grid-cols-2">
        {v.offers.map((o) => {
          const price = o.prices[currency];
          return (
            <li key={o.code} className="border border-term-line rounded-lg p-4 flex flex-col gap-2">
              <span className="text-term-fg text-sm">{o.name}</span>
              <span className="text-term-bright text-lg font-mono">
                {price ? `${formatMoney(price.amount_minor, currency)} / month` : "not sold in " + currency}
              </span>
              <button
                type="button"
                className={`${primary} self-start min-h-[44px] sm:min-h-0`}
                disabled={!price || busy !== null}
                onClick={() => void go(o.code)}
              >
                {busy === o.code ? "opening checkout…" : `Subscribe to ${o.name}`}
              </button>
            </li>
          );
        })}
      </ul>
      {error && (
        <p role="alert" className="text-term-err text-xs mt-2">
          {error}
        </p>
      )}
    </section>
  );
}

function Manage({ v, onChange }: { v: BillingView; onChange: (v: BillingView) => void }) {
  const { toast } = useAdmin();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState<"portal" | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!v.can_manage && !v.can_cancel) return null;

  async function portal() {
    setBusy("portal");
    setError(null);
    try {
      window.location.assign(await billingPortal());
    } catch (e) {
      setError(errText(e, "Could not open the payment page."));
      setBusy(null);
    }
  }

  async function cancel() {
    setBusy("cancel");
    setError(null);
    try {
      onChange(await cancelSubscription());
      setConfirming(false);
      toast("Subscription cancelled");
    } catch (e) {
      setError(errText(e, "Could not cancel. Try again."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby="bill-manage-h" className="mb-6">
      <h2 id="bill-manage-h" className="text-term-fg text-sm mb-2">
        Manage
      </h2>
      <div className="flex flex-wrap gap-2">
        {v.can_manage && (
          <button type="button" className={`${btn} min-h-[44px] sm:min-h-0`} disabled={busy !== null} onClick={() => void portal()}>
            {busy === "portal"
              ? "opening…"
              : v.provider === "razorpay"
                ? "Update payment method"
                : "Manage billing (Stripe)"}
          </button>
        )}
        {v.can_cancel && !confirming && (
          <button type="button" className={`${btn} min-h-[44px] sm:min-h-0`} onClick={() => setConfirming(true)}>
            Cancel subscription
          </button>
        )}
      </div>
      {confirming && (
        <div role="alertdialog" aria-labelledby="bill-cancel-q" className="mt-3 border border-term-amber/60 rounded p-3 text-xs max-w-md">
          <p id="bill-cancel-q" className="text-term-fg mb-2">
            Cancel at the end of the current period? Your assistant stays online until{" "}
            {day(v.current_period_end)}, then goes offline. You won't be charged again.
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={btn} disabled={busy !== null} onClick={() => void cancel()}>
              {busy === "cancel" ? "cancelling…" : "Yes, cancel"}
            </button>
            <button type="button" className={btn} disabled={busy !== null} onClick={() => setConfirming(false)}>
              Keep subscription
            </button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="text-term-err text-xs mt-2">
          {error}
        </p>
      )}
    </section>
  );
}

function Invoices() {
  const [items, setItems] = useState<BillingInvoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getInvoices()
      .then(setItems)
      .catch((e) => {
        setItems([]);
        setError(errText(e, "Could not load invoices."));
      });
  }, []);
  return (
    <section aria-labelledby="bill-inv-h" className="mb-6">
      <h2 id="bill-inv-h" className="text-term-fg text-sm mb-2">
        Invoices
      </h2>
      {items === null && <p className="text-term-dim text-xs">loading…</p>}
      {error && (
        <p role="alert" className="text-term-err text-xs">
          {error}
        </p>
      )}
      {items !== null && !error && items.length === 0 && (
        <p className="text-term-dim text-xs">No invoices yet. They appear here after each payment.</p>
      )}
      {items !== null && items.length > 0 && (
        <ul className="divide-y divide-term-line border border-term-line rounded-lg text-xs">
          {items.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2">
              <span className="text-term-fg min-w-[7rem]">{day(i.period_start ?? i.created_at)}</span>
              <span className="font-mono text-term-fg">{formatMoney(i.amount_minor, i.currency)}</span>
              <span className={i.status === "paid" ? "text-term-dim" : "text-term-amber"}>{i.status}</span>
              <span className="ml-auto flex gap-3">
                {i.hosted_url && (
                  <a href={i.hosted_url} target="_blank" rel="noopener noreferrer" className="text-term-bright underline">
                    view
                  </a>
                )}
                {i.pdf_url && (
                  <a href={i.pdf_url} target="_blank" rel="noopener noreferrer" className="text-term-bright underline">
                    PDF
                  </a>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Gstin({ v, onChange }: { v: BillingView; onChange: (v: BillingView) => void }) {
  const { toast } = useAdmin();
  const [value, setValue] = useState(v.owner_gstin ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onChange(await saveGstin(value));
      toast("GSTIN saved");
    } catch (err) {
      setError(errText(err, "Could not save the GSTIN."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={save} aria-labelledby="bill-gst-h" className="max-w-sm mb-6">
      <h2 id="bill-gst-h" className="text-term-fg text-sm mb-1">
        GSTIN (optional, India)
      </h2>
      <p className="text-term-dim text-xs mb-2">
        For GST invoices from Razorpay.{v.platform_gstin ? ` Our GSTIN: ${v.platform_gstin}.` : ""}
      </p>
      <label htmlFor="bill-gstin" className="sr-only">
        GSTIN
      </label>
      <input
        id="bill-gstin"
        value={value}
        maxLength={15}
        onChange={(e) => setValue(e.target.value.toUpperCase())}
        placeholder="29ABCDE1234F1Z5"
        className={`${inputCls} ${error ? "border-term-err" : "border-term-line2"} mb-2 font-mono`}
      />
      {error && (
        <p role="alert" className="text-term-err text-xs mb-2">
          {error}
        </p>
      )}
      <button type="submit" className={btn} disabled={busy || value === (v.owner_gstin ?? "")}>
        {busy ? "saving…" : "save GSTIN"}
      </button>
    </form>
  );
}

// Account -> Billing (hosted mode with paid plans): plan, trial, checkout, invoices.
export default function BillingPage() {
  const [v, setV] = useState<BillingView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [off, setOff] = useState(false);
  const returned = new URLSearchParams(window.location.search).get("checkout") === "done";

  const load = useCallback(() => {
    setError(null);
    getBilling()
      .then(setV)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setOff(true);
        else setError(errText(e, "Could not load billing."));
      });
  }, []);
  useEffect(load, [load]);

  return (
    <AdminSection title="Billing" intro="Your plan, payments and invoices.">
      {off && <p className="text-term-dim text-xs">Paid plans aren't enabled on this server.</p>}
      {error && (
        <div role="alert" className="border border-term-err text-term-err rounded px-3 py-2 mb-3 text-xs">
          {error}{" "}
          <button type="button" onClick={load} className="underline text-term-bright">
            Try again
          </button>
        </div>
      )}
      {!v && !error && !off && (
        <p role="status" className="text-term-dim text-xs">
          loading…
        </p>
      )}
      {v && (
        <>
          {returned && v.status !== "active" && (
            <div role="status" className="border border-term-line2 rounded px-3 py-2 mb-4 text-xs text-term-dim">
              Thanks — we're waiting for the payment provider to confirm. This page updates once it
              does; it usually takes a few seconds.{" "}
              <button type="button" onClick={load} className="underline text-term-bright">
                Refresh
              </button>
            </div>
          )}
          <Banner v={v} />
          <Summary v={v} />
          <Choose v={v} />
          <Manage v={v} onChange={setV} />
          <Invoices />
          <Gstin v={v} onChange={setV} />
        </>
      )}
    </AdminSection>
  );
}
