import { useEffect, useState } from "react";
import { AdminSection, useAdmin } from "../../components/admin/AdminLayout";
import { deleteContact, listContacts, type ContactItem } from "../../lib/api";

// Recruiters who left their details from the chat ("Leave my contact").
export default function ContactsPage() {
  const { toast } = useAdmin();
  const [items, setItems] = useState<ContactItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    listContacts()
      .then((xs) => setItems(xs ?? []))
      .catch((e) => {
        setItems([]);
        setError((e as Error).message || "Could not load contacts.");
      });
  }, []);

  async function remove(c: ContactItem) {
    if (!window.confirm(`Delete ${c.name}'s contact details?`)) return;
    setBusy(c.id);
    setError(null);
    try {
      await deleteContact(c.id);
      setItems((xs) => (xs ?? []).filter((x) => x.id !== c.id));
      toast("Contact deleted");
    } catch (e) {
      setError((e as Error).message || "Could not delete the contact.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <AdminSection
      title="Contacts"
      intro="Recruiters who left their details in the chat. Only you can see them."
    >
      {error && (
        <p role="alert" className="text-term-err text-xs mb-3">
          {error}
        </p>
      )}
      {items === null ? (
        <p className="text-term-dim text-xs">loading…</p>
      ) : items.length === 0 ? (
        !error && (
          <p className="text-term-dim text-xs border border-dashed border-term-line rounded px-3 py-6 text-center">
            No one has left their details yet. Recruiters see a “Leave my contact” button in
            the chat.
          </p>
        )
      ) : (
        <div className="space-y-2">
          {items.map((c) => (
            <article
              key={c.id}
              className="border border-term-line rounded bg-term-panel/60 px-3 py-2.5 text-xs"
            >
              <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
                <div className="flex-1 min-w-[12rem]">
                  <div className="text-term-bright text-sm">{c.name}</div>
                  <a href={`mailto:${c.email}`} className="underline text-term-fg break-all">
                    {c.email}
                  </a>
                  {(c.role || c.company) && (
                    <div className="text-term-dim mt-0.5">
                      {[c.role, c.company].filter(Boolean).join(" · ")}
                    </div>
                  )}
                </div>
                <time dateTime={c.created_at} className="text-term-dim">
                  {new Intl.DateTimeFormat(undefined, {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }).format(new Date(c.created_at))}
                </time>
                <button
                  type="button"
                  aria-label={`delete ${c.name}`}
                  disabled={busy === c.id}
                  onClick={() => void remove(c)}
                  className="font-mono text-xs px-2.5 py-1 rounded border border-term-line2 text-term-dim hover:text-term-err hover:border-term-err disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright"
                >
                  {busy === c.id ? "deleting…" : "delete"}
                </button>
              </div>
              {c.note && (
                <p className="mt-2 text-term-fg whitespace-pre-wrap break-words">{c.note}</p>
              )}
            </article>
          ))}
        </div>
      )}
    </AdminSection>
  );
}
