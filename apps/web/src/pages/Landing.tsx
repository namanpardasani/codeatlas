import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getRepos, logout, submitRepo, type RepoSummary } from "../api";
import { Button, Logo, ScaleBar } from "../components/ui";
import { LiveMapIllustration } from "../features/LiveMapIllustration";
import proof from "../data/proof.json";
import { useMe } from "../hooks/useMe";
import { rise } from "../ui/motion";

const EXAMPLES = ["sindresorhus/p-limit", "pallets/itsdangerous", "chalk/chalk"];
const GITHUB = "https://github.com/namanpardasani/codeatlas";

/** Accepts `owner/repo` or a pasted github.com URL and returns a canonical https URL, or null. */
export function toRepoUrl(input: string): string | null {
  const m = /^(?:https?:\/\/)?(?:www\.)?(?:github\.com\/)?([A-Za-z0-9-]{1,39})\/([A-Za-z0-9._-]{1,100}?)(?:\.git)?\/?$/.exec(input.trim());
  return m ? `https://github.com/${m[1]}/${m[2]}` : null;
}

const fmt = (v: number | null | undefined, digits = 3) => (v === null || v === undefined ? "—" : v.toFixed(digits));

function Icon({ kind }: { kind: "map" | "hot" | "cite" | "mcp" }) {
  const common = { width: 28, height: 28, viewBox: "0 0 28 28", fill: "none", strokeWidth: 1.6, strokeLinecap: "round" as const, "aria-hidden": true };
  if (kind === "map")
    return (
      <svg {...common} stroke="var(--color-cyan)">
        <circle cx="6" cy="8" r="2.5" />
        <circle cx="22" cy="6" r="2.5" />
        <circle cx="14" cy="21" r="2.5" />
        <path d="M8 9 L12 19 M20 8 L16 19 M8.5 8 L19.5 6" />
      </svg>
    );
  if (kind === "hot")
    return (
      <svg {...common} stroke="var(--color-amber)">
        <path d="M5 22 V14 M11 22 V8 M17 22 V16 M23 22 V5" />
      </svg>
    );
  if (kind === "cite")
    return (
      <svg {...common} stroke="var(--color-cyan)">
        <path d="M6 5 H17 L22 10 V23 H6 Z M17 5 V10 H22 M10 15 H18 M10 19 H15" />
      </svg>
    );
  return (
    <svg {...common} stroke="var(--color-cyan)">
      <rect x="4" y="6" width="20" height="16" rx="3" />
      <path d="M9 12 L12 14.5 L9 17 M14.5 17 H19" />
    </svg>
  );
}

const FEATURES = [
  { icon: "map" as const, title: "Dependency map", text: "Every import resolved, folders drawn as regions, circular dependencies traced." },
  { icon: "hot" as const, title: "Hotspots", text: "The files riskiest to change, ranked with the reasons written out." },
  { icon: "cite" as const, title: "Answers with receipts", text: "Each citation is checked against the code. What can't be verified is removed." },
  { icon: "mcp" as const, title: "MCP server", text: "Give Claude Code and other agents the same map, read-only." },
];

export default function Landing() {
  const navigate = useNavigate();
  const { me, reload } = useMe();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  useEffect(() => {
    getRepos().then(setRepos).catch(() => setRepos([]));
  }, []);
  // example chips: repositories that are really analysed here; the defaults only when the list is unavailable
  const examples = repos.length ? repos.slice(0, 3).map((r) => r.full_name) : EXAMPLES;

  const blocked = me?.demoMode
    ? "This is a read-only demo: analysis is disabled."
    : me?.authRequired && !me.user
      ? "Sign in with GitHub to map a repository."
      : null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const url = toRepoUrl(value);
    if (!url) return setError("Enter a public repository like owner/repo.");
    setError(null);
    setBusy(true);
    try {
      const { repoId, jobId, existing } = await submitRepo(url);
      // an already-analysed repo in the read-only demo opens directly (there is no job to watch)
      navigate(existing ? `/repo/${repoId}/overview` : `/analyze/${repoId}/${jobId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  const items = proof.items as { key: string; label: string; before: number | null; after: number | null }[];
  const re = proof.reindex as { incremental_s: number | null; full_cold_s: number | null; files: number | null; changed: number | null } | null;

  return (
    <div className="bg-dot-grid min-h-screen">
      <header className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-8 gap-y-3 px-6 py-5">
        <Link to="/" aria-label="CodeAtlas home" className="rounded-ui">
          <Logo />
        </Link>
        <nav aria-label="Primary" className="ml-2 flex flex-wrap items-center gap-x-6 gap-y-2 text-small text-text-3">
          <a className="hover:text-text" href="#how">How it works</a>
          <a className="hover:text-text" href="#proof">Eval results</a>
          <a className="hover:text-text" href="#features">MCP server</a>
          <a className="hover:text-text" href={GITHUB} rel="noreferrer">GitHub</a>
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {me?.user ? (
            <>
              <span className="text-small text-text-3">{me.user.login}</span>
              <Button variant="secondary" onClick={() => logout().then(reload)}>Sign out</Button>
            </>
          ) : me?.loginAvailable ? (
            <a href="/api/auth/github" className="inline-flex min-h-11 items-center rounded-ui border border-border bg-surface px-5 text-body font-semibold hover:border-border-strong hover:bg-surface-2">
              Sign in with GitHub
            </a>
          ) : null}
        </div>
      </header>

      <main>
        <section className="mx-auto grid max-w-7xl items-center gap-12 px-6 pb-20 pt-10 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <motion.div {...rise(0)} className="mono-label mb-6 flex items-center gap-3">
              <span>PLATE 01</span>
              <span aria-hidden className="h-px w-10 bg-border-strong" />
              <span>STATIC ANALYSIS FIRST · AI SECOND</span>
            </motion.div>
            <motion.h1 {...rise(1)} className="text-hero">
              Any codebase, <span className="text-cyan">mapped</span> in a minute.
            </motion.h1>
            <motion.p {...rise(2)} className="mt-6 max-w-[520px] text-[17px] text-text-3">
              Paste a public GitHub repository. CodeAtlas reads it, draws the dependency map, ranks the files that are riskiest to change, and
              answers questions with citations you can check.
            </motion.p>
            <motion.form {...rise(3)} onSubmit={submit} className="mt-8" aria-label="Map a repository">
              <div className="flex flex-wrap items-center gap-3 rounded-shell border border-border-strong bg-surface p-2 pl-5 shadow-deep sm:flex-nowrap">
                <label htmlFor="repo" className="sr-only">
                  GitHub repository, owner/repo
                </label>
                <span aria-hidden className="font-mono text-body text-dim">github.com/</span>
                <input
                  id="repo"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder="owner/repo"
                  autoComplete="off"
                  spellCheck={false}
                  className="min-w-0 flex-1 bg-transparent py-3 font-mono text-body text-text outline-none placeholder:text-dim focus-visible:outline-none"
                />
                <Button type="submit" disabled={busy || !value.trim() || Boolean(blocked)} className="min-h-12 w-full px-6 text-[15px] sm:w-auto">
                  {busy ? "Starting…" : "Map it →"}
                </Button>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className="mono-label mr-1">Try</span>
                {examples.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => setValue(ex)}
                    className="min-h-9 rounded-md border border-border bg-surface px-3 font-mono text-small text-text-3 transition-colors duration-150 hover:border-cyan hover:text-cyan-soft"
                  >
                    {ex}
                  </button>
                ))}
              </div>
              <p className="mt-4 text-small text-muted">Public GitHub repositories only. Private repositories are not supported.</p>
              {blocked && <p className="mt-2 text-small text-text-3">{blocked}</p>}
              {error && (
                <p role="alert" className="mt-2 text-small text-error">
                  {error}
                </p>
              )}
            </motion.form>
          </div>

          <motion.div {...rise(2, 20)} className="overflow-hidden rounded-panel border border-border bg-surface" aria-label="Illustration of a dependency map">
            <div className="flex items-center justify-between border-b border-line bg-bg-raised px-4 py-2.5">
              <span className="font-mono text-small text-text-3">owner/repo · N files</span>
              <span className="font-mono text-small text-cyan-soft">
                live map<span className="anim-caret ml-0.5 inline-block w-1.5 bg-cyan align-middle" style={{ height: "0.95em" }} />
              </span>
            </div>
            <div className="bg-line-grid aspect-[420/260] bg-bg">
              <LiveMapIllustration />
            </div>
            <div className="flex items-center justify-between border-t border-line bg-bg-raised px-4 py-2.5">
              <ScaleBar />
              <span className="mono-label">illustration</span>
            </div>
          </motion.div>
        </section>

        {repos.length > 0 && (
          <section className="mx-auto max-w-7xl px-6 pb-16" aria-label="Already mapped repositories">
            <h2 className="sr-only">Already mapped repositories</h2>
            <div className="mono-label mb-4" aria-hidden>PLATE 02 ——— ALREADY MAPPED · OPEN ONE</div>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {repos.map((r) => (
                <li key={r.id}>
                  <Link
                    to={`/repo/${r.id}/overview`}
                    className="block rounded-card border border-border bg-surface p-4 transition-colors duration-200 hover:border-cyan"
                  >
                    <span className="block truncate font-mono text-body text-text">{r.full_name}</span>
                    <span className="mt-1 block font-mono text-micro text-muted">
                      {r.files} files{r.commit_sha ? ` · ${r.commit_sha.slice(0, 7)}` : ""}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section id="features" className="mx-auto max-w-7xl px-6 pb-20" aria-label="Features">
          <h2 className="sr-only">What you get</h2>
          <div id="how" className="mono-label mb-4" aria-hidden>PLATE 03 ——— WHAT YOU GET</div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((f, i) => (
              <motion.div
                key={f.title}
                initial={{ opacity: 0, y: 14 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-40px" }}
                transition={{ duration: 0.6, delay: i * 0.08, ease: [0.2, 0.7, 0.2, 1] }}
                whileHover={{ y: -4 }}
                className="group rounded-card border border-border bg-surface p-5 transition-colors duration-200 hover:border-cyan"
              >
                <Icon kind={f.icon} />
                <h3 className="mt-4 font-display text-[18px] font-semibold text-text">{f.title}</h3>
                <p className="mt-2 text-small leading-relaxed text-text-3">{f.text}</p>
              </motion.div>
            ))}
          </div>
        </section>

        <section id="proof" className="border-t border-line bg-bg-raised" aria-label="Measured results">
          <div className="mx-auto max-w-7xl px-6 py-14">
            <div className="grid gap-8 lg:grid-cols-[1fr_2fr] lg:items-center">
              <div>
                <div className="mono-label mb-3">PLATE 04 ——— EVALUATION</div>
                <h2 className="text-section">Measured, not claimed.</h2>
                <p className="mt-2 max-w-sm text-small text-muted">
                  From stored evaluation runs. The 50 questions were written by the AI that built the system, so read these as indicative.{" "}
                  <a className="underline hover:text-text" href={`${GITHUB}/blob/main/docs/EVAL.md`}>
                    Method and caveats
                  </a>
                </p>
              </div>
              <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {items.map((it) => (
                  <div key={it.key} className="rounded-card border border-border bg-surface p-4">
                    <dt className="text-[12px] text-muted">{it.label}</dt>
                    <dd className="mt-1 font-mono text-[17px] text-cyan-soft">
                      {fmt(it.before)} → {fmt(it.after)}
                    </dd>
                  </div>
                ))}
                <div className="rounded-card border border-border bg-surface p-4">
                  <dt className="text-[12px] text-muted">re-index after a {re?.changed ?? "—"}-file change</dt>
                  <dd className="mt-1 font-mono text-[17px] text-cyan-soft">
                    {fmt(re?.incremental_s, 2)} s <span className="text-dim">vs</span> {fmt(re?.full_cold_s, 1)} s
                  </dd>
                </div>
              </dl>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
