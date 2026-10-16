import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AdminSection } from "../../components/admin/AdminLayout";
import GithubImportCard from "../../components/admin/GithubImportCard";
import ImportReview, { summaryText } from "../../components/admin/ImportReview";
import {
  ApiError,
  discardImport,
  getImportJob,
  getLlm,
  listImportJobs,
  uploadImport,
  type ImportJob,
  type ImportKind,
  type ImportSummary,
} from "../../lib/api";

// Fill the profile from a resume (PDF/DOCX, via the owner's AI provider) or a LinkedIn
// data export (deterministic). Upload -> processing -> review -> apply.
// Cards are config: file importers are entries in CARDS; GitHub has its own card.

export const POLL_MS = 2000;
const MB = 1024 * 1024;

interface Card {
  kind: ImportKind;
  title: string;
  blurb: string;
  accept: string;
  exts: string[];
  maxBytes: number;
  needsLlm: boolean;
  guide?: React.ReactNode;
}

export const CARDS: Card[] = [
  {
    kind: "resume",
    title: "Resume",
    blurb: "PDF or Word (.docx). Your AI provider reads it; anything it can't find in the file is flagged.",
    accept: ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    exts: ["pdf", "docx"],
    maxBytes: 10 * MB,
    needsLlm: true,
  },
  {
    kind: "linkedin",
    title: "LinkedIn export",
    blurb: "The ZIP from LinkedIn's “Get a copy of your data”. Read exactly as exported — no AI involved.",
    accept: ".zip,application/zip",
    exts: ["zip"],
    maxBytes: 50 * MB,
    needsLlm: false,
    guide: (
      <details className="mt-3 text-xs text-term-dim">
        <summary className="cursor-pointer text-term-fg">How to get your LinkedIn data</summary>
        <ol className="list-decimal ml-5 mt-2 space-y-1">
          <li>On LinkedIn: Me → Settings &amp; Privacy → Data privacy → Get a copy of your data.</li>
          <li>Choose “Want something in particular?” and tick Profile, Positions, Education, Skills, Projects (and Certifications, Languages, Honors if you like).</li>
          <li>Request the archive. LinkedIn emails you when it's ready (usually within minutes).</li>
          <li>Download the ZIP and upload it here as is.</li>
        </ol>
      </details>
    ),
  },
];

type Phase =
  | { name: "pick" }
  | { name: "uploading"; kind: ImportKind; progress: number }
  | { name: "processing"; id: string; kind: ImportKind }
  | { name: "review"; job: ImportJob }
  | { name: "failed"; message: string }
  | { name: "done"; summary: ImportSummary };

const SECTION_LINKS: [string, string, string][] = [
  ["identity", "/admin/profile/identity", "Identity"],
  ["experiences", "/admin/profile/experience", "Experience"],
  ["educations", "/admin/profile/education", "Education"],
  ["skills", "/admin/profile/skills", "Skills"],
  ["projects", "/admin/profile/projects", "Projects"],
  ["interests", "/admin/profile/interests", "Interests"],
  ["links", "/admin/profile/identity", "Contact channels"],
  ["notes", "/admin/profile/notes", "Notes"],
];

const btn =
  "font-mono text-xs px-2.5 py-1.5 min-h-[32px] rounded border focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-50";
const ghost = btn + " border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright";

function precheck(card: Card, file: File): string | null {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "doc" || ext === "docm") return "Old .doc and macro-enabled files aren't supported: save it as .docx.";
  if (!card.exts.includes(ext)) return `Choose a ${card.exts.map((e) => "." + e).join(" or ")} file.`;
  if (file.size > card.maxBytes) return `That file is too large (max ${card.maxBytes / MB} MB).`;
  if (file.size === 0) return "That file is empty.";
  return null;
}

function UploadCard({
  card,
  disabled,
  disabledHint,
  onFile,
}: {
  card: Card;
  disabled: boolean;
  disabledHint?: React.ReactNode;
  onFile: (card: Card, file: File) => void;
}) {
  const [over, setOver] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const id = `import-${card.kind}`;
  function take(file: File | undefined) {
    if (!file || disabled) return;
    const problem = precheck(card, file);
    setErr(problem);
    if (!problem) onFile(card, file);
  }
  return (
    <div className={"border rounded-lg p-4 flex flex-col " + (disabled ? "border-term-line opacity-70" : "border-term-line2")}>
      <h2 className="text-term-fg text-sm mb-1">{card.title}</h2>
      <p className="text-term-dim text-xs mb-3 leading-relaxed">{card.blurb}</p>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          take(e.dataTransfer.files?.[0]);
        }}
        className={
          "border border-dashed rounded-lg px-3 py-6 text-center text-xs " +
          (over ? "border-term-bright bg-term-bright/5 text-term-fg" : "border-term-line2 text-term-dim")
        }
      >
        <p className="mb-2">Drop the file here, or</p>
        <label
          htmlFor={id}
          className={btn + " inline-flex items-center border-term-bright text-term-bright " + (disabled ? "pointer-events-none" : "cursor-pointer hover:bg-term-bright/10")}
        >
          choose {card.exts.map((e) => "." + e).join(" / ")}
        </label>
        <input
          ref={input}
          id={id}
          type="file"
          accept={card.accept}
          disabled={disabled}
          aria-label={`Upload ${card.title}`}
          className="sr-only"
          onChange={(e) => {
            take(e.target.files?.[0]);
            if (input.current) input.current.value = "";
          }}
        />
        <p className="mt-2 text-[11px]">Max {card.maxBytes / MB} MB</p>
      </div>
      {disabled && disabledHint && <p className="mt-2 text-xs text-term-amber">{disabledHint}</p>}
      {err && (
        <p role="alert" className="mt-2 text-xs text-term-err">
          {err}
        </p>
      )}
      {card.guide}
    </div>
  );
}

export default function ImportPage() {
  const [phase, setPhase] = useState<Phase | null>(null);
  const [llmOk, setLlmOk] = useState<boolean | null>(null);

  useEffect(() => {
    getLlm()
      .then((l) => setLlmOk(Boolean(l?.configured) && l?.last_test_ok !== false))
      .catch(() => setLlmOk(false));
    // Resume where the owner left off: a running or unreviewed import.
    listImportJobs()
      .then(async (jobs) => {
        const last = jobs[0];
        if (last?.status === "processing") setPhase({ name: "processing", id: last.id, kind: last.kind });
        else if (last?.status === "ready") setPhase({ name: "review", job: await getImportJob(last.id) });
        else setPhase({ name: "pick" });
      })
      .catch(() => setPhase({ name: "pick" }));
  }, []);

  const track = useCallback(async (id: string) => {
    const job = await getImportJob(id);
    if (job.status === "ready") setPhase({ name: "review", job });
    else if (job.status === "failed") setPhase({ name: "failed", message: job.error_message || "The import failed." });
    else if (job.status === "expired") setPhase({ name: "failed", message: "This import expired. Please upload the file again." });
    else if (job.status === "applied") setPhase({ name: "done", summary: job.applied_summary ?? {} });
    return job.status;
  }, []);

  // Poll while processing.
  const processingId = phase?.name === "processing" ? phase.id : null;
  useEffect(() => {
    if (!processingId) return;
    let stop = false;
    const tick = async () => {
      try {
        const s = await track(processingId);
        if (s !== "processing") stop = true;
      } catch (e) {
        stop = true;
        setPhase({ name: "failed", message: (e as Error).message || "Lost track of the import." });
      }
    };
    void tick();
    const t = setInterval(() => {
      if (!stop) void tick();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [processingId, track]);

  async function upload(card: Card, file: File) {
    setPhase({ name: "uploading", kind: card.kind, progress: 0 });
    try {
      const r = await uploadImport(card.kind, file, (p) =>
        setPhase((ph) => (ph?.name === "uploading" ? { ...ph, progress: p } : ph)),
      );
      setPhase({ name: "processing", id: r.id, kind: card.kind });
    } catch (e) {
      const msg =
        e instanceof ApiError && e.code === "IMPORT_IN_PROGRESS"
          ? "Another import is still running. Wait for it to finish."
          : (e as Error).message || "Upload failed.";
      setPhase({ name: "failed", message: msg });
    }
  }

  async function discard(id: string) {
    try {
      await discardImport(id);
    } catch {
      // gone already: either way the owner is back at the start
    }
    setPhase({ name: "pick" });
  }

  const intro = (
    <>
      Upload your resume or LinkedIn export, or pick GitHub repos, and review every item before it's saved.{" "}
      <span className="text-term-fg">Your file isn't stored. We never read your LinkedIn messages or connections.</span>
    </>
  );

  if (!phase) {
    return (
      <AdminSection title="Import" intro={intro}>
        <p className="text-term-dim text-xs">loading…</p>
      </AdminSection>
    );
  }

  return (
    <AdminSection title="Import" intro={intro}>
      {phase.name === "pick" && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {CARDS.map((c) => (
            <UploadCard
              key={c.kind}
              card={c}
              onFile={(card, file) => void upload(card, file)}
              disabled={c.needsLlm && llmOk !== true}
              disabledHint={
                c.needsLlm && llmOk === false ? (
                  <>
                    Resume import uses your AI provider.{" "}
                    <Link to="/admin/llm" className="underline text-term-bright">
                      Set it up first
                    </Link>
                    .
                  </>
                ) : undefined
              }
            />
          ))}
          <GithubImportCard onStarted={(id) => setPhase({ name: "processing", id, kind: "github" })} />
        </div>
      )}

      {phase.name === "uploading" && (
        <div className="border border-term-line2 rounded-lg p-4" aria-live="polite">
          <p className="text-term-fg text-sm mb-2">Uploading…</p>
          <div
            role="progressbar"
            aria-label="Upload progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(phase.progress * 100)}
            className="h-2 rounded bg-term-panel overflow-hidden"
          >
            <div className="h-full bg-term-bright transition-[width]" style={{ width: `${Math.round(phase.progress * 100)}%` }} />
          </div>
        </div>
      )}

      {phase.name === "processing" && (
        <div className="border border-term-line2 rounded-lg p-4" aria-live="polite" aria-busy="true">
          <p className="text-term-fg text-sm mb-1">
            {phase.kind === "resume"
              ? "Reading your resume…"
              : phase.kind === "github"
                ? "Reading your repos on GitHub…"
                : "Reading your LinkedIn export…"}
          </p>
          <p className="text-term-dim text-xs">
            {phase.kind === "linkedin" ? "Usually a few seconds." : "This can take up to a minute."}
          </p>
        </div>
      )}

      {phase.name === "failed" && (
        <div role="alert" className="border border-term-err rounded-lg p-4">
          <p className="text-term-err text-sm mb-3">{phase.message}</p>
          <button type="button" className={ghost} onClick={() => setPhase({ name: "pick" })}>
            try again
          </button>
        </div>
      )}

      {phase.name === "review" && (
        <ImportReview
          job={phase.job}
          onApplied={(summary) => setPhase({ name: "done", summary })}
          onDiscard={() => void discard(phase.job.id)}
        />
      )}

      {phase.name === "done" && (
        <div className="border border-term-bright/60 rounded-lg p-4" role="status">
          <p className="text-term-bright text-sm mb-2">{summaryText(phase.summary)}</p>
          <ul className="flex flex-wrap gap-2 mb-3">
            {SECTION_LINKS.filter(([k]) => phase.summary[k]).map(([k, to, label]) => (
              <li key={k}>
                <Link to={to} className="underline text-term-bright text-xs">
                  {label}
                </Link>
              </li>
            ))}
          </ul>
          <button type="button" className={ghost} onClick={() => setPhase({ name: "pick" })}>
            import another file
          </button>
        </div>
      )}
    </AdminSection>
  );
}
