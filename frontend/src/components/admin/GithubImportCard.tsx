import { useEffect, useState } from "react";
import {
  ApiError,
  deleteGithubToken,
  getGithubToken,
  listGithubRepos,
  saveGithubToken,
  startGithubImport,
  type GithubRepo,
  type GithubTokenView,
} from "../../lib/api";

// Import page card: public GitHub repos -> project entries. Paste URLs or pick from a
// username's repos (up to MAX_REPOS), optional token for GitHub's rate limits.

export const MAX_REPOS = 10;
const REPO_URL =
  /^https?:\/\/(www\.)?github\.com\/[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}(\.git)?(\/(tree|blob)\/\S*)?\/?$/i;
const USERNAME = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;

const btn =
  "font-mono text-xs px-2.5 py-1.5 min-h-[32px] rounded border focus-visible:outline focus-visible:outline-2 focus-visible:outline-term-bright disabled:opacity-50";
const ghost = btn + " border-term-line2 text-term-dim hover:text-term-fg hover:border-term-bright";
const primary = btn + " border-term-bright text-term-bright hover:bg-term-bright/10";
const inputCls =
  "w-full bg-term-bg border border-term-line2 rounded text-term-fg font-mono text-xs px-2.5 py-2 outline-none focus:border-term-bright";

export function checkRepoUrls(text: string): { urls: string[]; errors: string[] } {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const errors = lines.filter((l) => !REPO_URL.test(l)).map((l) => `Not a GitHub repo URL: ${l}`);
  const urls = [...new Map(lines.map((l) => [l.toLowerCase().replace(/(\.git)?\/?$/, ""), l])).values()];
  if (!errors.length && urls.length > MAX_REPOS) errors.push(`At most ${MAX_REPOS} repos at a time.`);
  return { urls, errors };
}

function ago(iso: string | null): string {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days < 1) return "today";
  if (days < 31) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

function TokenBox() {
  const [view, setView] = useState<GithubTokenView | null>(null);
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    getGithubToken()
      .then(setView)
      .catch(() => setView(null));
  }, []);
  async function save() {
    setBusy(true);
    setError(null);
    try {
      setView(await saveGithubToken(token.trim()));
      setToken("");
    } catch (e) {
      setError((e as Error).message || "Could not save the token.");
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    setBusy(true);
    try {
      await deleteGithubToken();
      setView((v) => (v ? { ...v, configured: false, token_last4: null } : v));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="mt-3 text-xs text-term-dim">
      <summary className="cursor-pointer text-term-fg">GitHub token (optional, for rate limits)</summary>
      <p className="mt-2 leading-relaxed">
        Without a token GitHub allows about 60 requests an hour, roughly 5 repos. A fine-grained token
        with <strong className="text-term-fg">no permissions</strong> (public data only) is enough.
      </p>
      {view?.configured ? (
        <div className="mt-2 flex items-center gap-2">
          <span className="font-mono text-term-fg">saved ••••{view.token_last4}</span>
          <button type="button" className={ghost} disabled={busy} onClick={() => void remove()}>
            remove
          </button>
        </div>
      ) : (
        <div className="mt-2 flex gap-2">
          <input
            type="password"
            autoComplete="off"
            aria-label="GitHub token"
            placeholder="github_pat_… or ghp_…"
            className={inputCls}
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
          <button type="button" className={ghost} disabled={busy || !token.trim()} onClick={() => void save()}>
            save
          </button>
        </div>
      )}
      {view?.env_token && !view.configured && <p className="mt-1">Using the server's GITHUB_TOKEN.</p>}
      {error && (
        <p role="alert" className="mt-1 text-term-err">
          {error}
        </p>
      )}
    </details>
  );
}

function Picker({ onPick }: { onPick: (urls: string[]) => void }) {
  const [username, setUsername] = useState("");
  const [forks, setForks] = useState(false);
  const [repos, setRepos] = useState<GithubRepo[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);

  async function load(e?: React.FormEvent) {
    e?.preventDefault();
    if (!USERNAME.test(username.trim())) {
      setError("That isn't a GitHub username.");
      return;
    }
    setLoading(true);
    setError(null);
    setPicked([]);
    try {
      setRepos(await listGithubRepos(username.trim(), forks));
    } catch (err) {
      setRepos(null);
      setError(
        err instanceof ApiError && err.code === "USER_NOT_FOUND"
          ? "No GitHub user with that name."
          : (err as Error).message || "Couldn't load repos.",
      );
    } finally {
      setLoading(false);
    }
  }

  function toggle(full: string) {
    setPicked((p) => (p.includes(full) ? p.filter((x) => x !== full) : p.length >= MAX_REPOS ? p : [...p, full]));
  }

  return (
    <div>
      <form onSubmit={(e) => void load(e)} className="flex gap-2">
        <input
          aria-label="GitHub username"
          placeholder="username"
          className={inputCls}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <button type="submit" className={ghost} disabled={loading}>
          {loading ? "loading…" : "list repos"}
        </button>
      </form>
      <label className="mt-2 flex items-center gap-2 text-xs text-term-dim">
        <input type="checkbox" checked={forks} onChange={(e) => setForks(e.target.checked)} /> show forks
      </label>
      {error && (
        <p role="alert" className="mt-2 text-xs text-term-err">
          {error}
        </p>
      )}
      {repos && repos.length === 0 && <p className="mt-2 text-xs text-term-dim">No public repos found.</p>}
      {repos && repos.length > 0 && (
        <>
          <p className="mt-2 text-xs text-term-dim">
            {picked.length}/{MAX_REPOS} selected
          </p>
          <ul aria-label="Repos" className="mt-1 max-h-72 overflow-y-auto border border-term-line rounded divide-y divide-term-line">
            {repos.map((r) => {
              const on = picked.includes(r.full_name);
              const full = !on && picked.length >= MAX_REPOS;
              return (
                <li key={r.full_name}>
                  <label className={"flex items-start gap-2 px-2.5 py-2 text-xs " + (full ? "opacity-50" : "cursor-pointer hover:bg-term-panel")}>
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={on}
                      disabled={full}
                      onChange={() => toggle(r.full_name)}
                      aria-label={r.full_name}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-term-fg truncate">
                        {r.name}
                        {r.archived && <span className="ml-1 text-term-dim">(archived)</span>}
                        {r.fork && <span className="ml-1 text-term-dim">(fork)</span>}
                      </span>
                      {r.description && <span className="block text-term-dim truncate">{r.description}</span>}
                      <span className="block text-term-dim">
                        ★ {r.stars}
                        {r.language ? ` · ${r.language}` : ""}
                        {r.pushed_at ? ` · pushed ${ago(r.pushed_at)}` : ""}
                      </span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
          <button
            type="button"
            className={primary + " mt-3"}
            disabled={picked.length === 0}
            onClick={() => onPick(picked.map((f) => `https://github.com/${f}`))}
          >
            import {picked.length || ""} repo{picked.length === 1 ? "" : "s"}
          </button>
        </>
      )}
    </div>
  );
}

export default function GithubImportCard({ onStarted }: { onStarted: (jobId: string) => void }) {
  const [tab, setTab] = useState<"urls" | "user">("urls");
  const [text, setText] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function start(urls: string[]) {
    setBusy(true);
    setErrors([]);
    try {
      const r = await startGithubImport(urls);
      onStarted(r.id);
    } catch (e) {
      const details = e instanceof ApiError ? e.details.map((d) => d.message) : [];
      setErrors(details.length ? details : [(e as Error).message || "Couldn't start the import."]);
    } finally {
      setBusy(false);
    }
  }

  function submitUrls() {
    const { urls, errors: errs } = checkRepoUrls(text);
    if (errs.length || !urls.length) {
      setErrors(errs.length ? errs : ["Paste at least one repo URL."]);
      return;
    }
    void start(urls);
  }

  const tabCls = (on: boolean) =>
    "font-mono text-xs px-2.5 py-1.5 min-h-[32px] border-b-2 " +
    (on ? "border-term-bright text-term-bright" : "border-transparent text-term-dim hover:text-term-fg");

  return (
    <div className="border border-term-line2 rounded-lg p-4 flex flex-col">
      <h2 className="text-term-fg text-sm mb-1">GitHub</h2>
      <p className="text-term-dim text-xs mb-3 leading-relaxed">
        Public repos become project entries. Tech is read from manifests; your AI provider (if set) writes the
        summary from the README.
      </p>
      <div role="tablist" aria-label="GitHub import source" className="flex gap-1 border-b border-term-line mb-3">
        <button type="button" role="tab" aria-selected={tab === "urls"} className={tabCls(tab === "urls")} onClick={() => setTab("urls")}>
          Repo URL(s)
        </button>
        <button type="button" role="tab" aria-selected={tab === "user"} className={tabCls(tab === "user")} onClick={() => setTab("user")}>
          From username
        </button>
      </div>
      {tab === "urls" ? (
        <div>
          <label htmlFor="gh-urls" className="block text-xs text-term-dim mb-1">
            one URL per line (up to {MAX_REPOS})
          </label>
          <textarea
            id="gh-urls"
            rows={3}
            className={inputCls}
            placeholder="https://github.com/you/your-repo"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setErrors([]);
            }}
          />
          <button type="button" className={primary + " mt-2"} disabled={busy} onClick={submitUrls}>
            {busy ? "starting…" : "import"}
          </button>
        </div>
      ) : (
        <Picker onPick={(urls) => void start(urls)} />
      )}
      {errors.length > 0 && (
        <ul role="alert" className="mt-2 text-xs text-term-err space-y-0.5">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      <TokenBox />
    </div>
  );
}
