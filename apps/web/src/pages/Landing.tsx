import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getRepos, logout, submitRepo, type RepoSummary } from "../api";
import { Arrow, Button, ButtonAnchor, Figure, Icon, Logo, MarginNote, Sheet, Stamp, ThemeToggle } from "../components/ui";
import proof from "../data/proof.json";
import { EVAL, EXAMPLE } from "../data/example";
import { AtlasSheet } from "../features/landing/AtlasSheet";
import { Colophon, GITHUB } from "../features/landing/Footer";
import { useMe } from "../hooks/useMe";
import { useMotionOff } from "../hooks/useMotionOff";

gsap.registerPlugin(ScrollTrigger, SplitText);

const FALLBACK_EXAMPLES = ["psf/requests", "pallets/itsdangerous", "chalk/chalk"];
const MCP_CMD = 'claude mcp add codeatlas -- "$PWD/bin/codeatlas-mcp.sh"';

/** Accepts `owner/repo` or a pasted github.com URL and returns a canonical https URL, or null. */
export function toRepoUrl(input: string): string | null {
  const m = /^(?:https?:\/\/)?(?:www\.)?(?:github\.com\/)?([A-Za-z0-9-]{1,39})\/([A-Za-z0-9._-]{1,100}?)(?:\.git)?\/?$/.exec(input.trim());
  return m ? `https://github.com/${m[1]}/${m[2]}` : null;
}

const short = (p: string) => p.replace(/^src\/requests\//, "");

/**
 * Landing motion (gsap, this page only). Three animations, each with a job, all skipped with reduced motion:
 *   1. the headline sets line by line (reading order, once)
 *   2. the hero map inks in the blast hop by hop (shows what the product does before you read about it)
 *   3. the worked example scrubs with scroll: each hop of the ledger lights up as its ring reaches it
 */
function useLandingMotion(root: React.RefObject<HTMLElement | null>, off: boolean) {
  useLayoutEffect(() => {
    if (off || !root.current) return;
    const ctx = gsap.context(() => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const h1 = root.current!.querySelector("[data-split]");
        if (h1) {
          // masks get room for descenders (index.css); the split is undone when the lines have landed, so the final
          // text is the original markup (same wrapping, selectable, no extra spans for screen readers)
          const split = SplitText.create(h1, { type: "lines", mask: "lines", linesClass: "split-line" });
          gsap.from(split.lines, { yPercent: 110, duration: 0.9, ease: "power4.out", stagger: 0.09, delay: 0.1, onComplete: () => split.revert() });
        }
        const hero = root.current!.querySelector("[data-hero-map]");
        if (hero) {
          gsap.from(hero.querySelectorAll("[data-hop='0']"), { opacity: 0, scale: 0.4, transformOrigin: "center", duration: 0.5, delay: 0.7, ease: "back.out(2)" });
          gsap.from(hero.querySelectorAll("[data-hop='1']"), { opacity: 0, duration: 0.5, delay: 1.3 });
          gsap.from(hero.querySelectorAll("[data-hop='2']"), { opacity: 0, duration: 0.5, delay: 1.9 });
        }
        const ex = root.current!.querySelector("[data-example]");
        if (ex) {
          const tl = gsap.timeline({ scrollTrigger: { trigger: ex, start: "top 70%", end: "bottom 60%", scrub: 0.6 } });
          ex.querySelectorAll("[data-row]").forEach((row) => {
            tl.from(row, { opacity: 0.18, x: -10, duration: 1, ease: "none" });
          });
        }
      });
    }, root);
    return () => ctx.revert();
  }, [root, off]);
}

function CopyCommand({ cmd }: { cmd: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => navigator.clipboard?.writeText(cmd).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600); })}
      className="font-mono text-[11px] uppercase tracking-[0.12em] text-table-muted hover:text-table-ink"
      aria-label="Copy command"
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}

export default function Landing() {
  const navigate = useNavigate();
  const off = useMotionOff();
  const { me, reload } = useMe();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const input = useRef<HTMLInputElement | null>(null);
  const root = useRef<HTMLDivElement | null>(null);
  useLandingMotion(root, off);

  useEffect(() => {
    getRepos().then(setRepos).catch(() => setRepos([]));
  }, []);

  const samples = repos.filter((r) => !r.full_name.startsWith("octocat/"));
  const examples = samples.length ? samples.slice(0, 3).map((r) => r.full_name) : FALLBACK_EXAMPLES;
  const blocked = me?.demoMode ? "This is a read-only demo: open one of the repositories already mapped." : me?.authRequired && !me.user ? "Sign in with GitHub to map a repository." : null;
  const known = repos.some((r) => toRepoUrl(value) === `https://github.com/${r.full_name}`);
  const requests = repos.find((r) => r.full_name === EXAMPLE.repo);
  const re = proof.reindex as { incremental_s: number | null; full_cold_s: number | null; changed: number | null } | null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const url = toRepoUrl(value);
    if (!url) return setError("That doesn't look like a GitHub repository. Try owner/repo.");
    setError(null);
    setBusy(true);
    try {
      const { repoId, jobId, existing } = await submitRepo(url);
      navigate(existing ? `/repo/${repoId}/overview` : `/analyze/${repoId}/${jobId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  const navLink = "text-[14px] text-table-muted transition-colors hover:text-table-ink";

  return (
    <div ref={root} className="min-h-screen overflow-x-clip bg-table text-table-ink">
      <header className="mx-auto flex max-w-[1240px] 2xl:max-w-[1440px] items-center gap-7 px-4 py-5 sm:px-6">
        <Link to="/" aria-label="CodeAtlas home" className="rounded-ui"><Logo needle="track" /></Link>
        <nav aria-label="Primary" className="hidden items-center gap-6 md:flex">
          <Link className={navLink} to="/replay">Replay a real bug</Link>
          <a className={navLink} href="#measured">How we measured</a>
          <a className={navLink} href="#mcp">MCP</a>
          <a className={navLink} href={GITHUB}>Source</a>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          {me?.user ? (
            <Button variant="arrow" size="sm" onClick={() => logout().then(reload)} className="text-table-ink">Sign out</Button>
          ) : me?.loginAvailable ? (
            <ButtonAnchor variant="arrow" size="sm" href="/api/auth/github" className="text-table-ink">Sign in <Arrow /></ButtonAnchor>
          ) : null}
        </div>
      </header>

      <main>
        {/* ---------- hero: words left, the map right ---------- */}
        <section className="mx-auto grid max-w-[1240px] 2xl:max-w-[1440px] grid-cols-[minmax(0,1fr)] items-start gap-x-14 gap-y-16 px-4 pb-24 pt-10 sm:px-6 md:pt-16 lg:grid-cols-[1.08fr_0.92fr]">
          <div>
            <p className="mono-label text-table-muted">Sheet 01 · <span className="text-table-signal">for any public GitHub repository</span></p>
            <h1 data-split className="text-display mt-6 text-balance">
              Know what a change <span className="text-wonk text-signal">will break</span> before you merge it.
            </h1>
            <p className="mt-7 max-w-[34em] text-[18.5px] leading-relaxed text-table-muted">
              CodeAtlas reads a repository, never runs it, and draws the map: who imports whom, where the risky files are,
              and <strong className="font-semibold text-table-ink">which files your pull request will drag along</strong>, with the reason for each.
            </p>

            <form onSubmit={submit} aria-label="Map a repository" className="mt-9 max-w-[580px]">
              <div className="paper flex flex-col gap-2 rounded-ui p-1.5 shadow-sheet sm:flex-row sm:items-center">
                <label htmlFor="repo" className="sr-only">GitHub repository, owner/repo or URL</label>
                <input
                  id="repo"
                  ref={input}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder="github.com/owner/repo"
                  autoComplete="off"
                  spellCheck={false}
                  className="min-h-11 min-w-0 flex-1 bg-transparent px-3 font-mono text-[15px] text-ink outline-none placeholder:text-pencil focus-visible:outline-none"
                />
                <Button type="submit" size="lg" disabled={busy || (Boolean(blocked) && !known)}>
                  {busy ? "Unfolding…" : "Draw the map"}
                </Button>
              </div>
              {error && <p role="alert" className="mt-3 text-[14px] text-table-signal">{error}</p>}
              {blocked && <p className="mt-3 text-[14px] text-table-muted">{blocked}</p>}
              <p className="mt-4 text-[14px] text-table-muted">
                Or open one already mapped:{" "}
                {examples.map((ex, i) => {
                  const r = samples.find((s) => s.full_name === ex);
                  const cls = "font-mono text-[13px] text-table-ink underline decoration-table-line decoration-1 underline-offset-4 hover:decoration-signal";
                  return (
                    <span key={ex}>
                      {i > 0 && ", "}
                      {r ? <Link className={cls} to={`/repo/${r.id}/overview`}>{ex}</Link> : <button type="button" className={cls} onClick={() => { setValue(ex); input.current?.focus(); }}>{ex}</button>}
                    </span>
                  );
                })}
              </p>
            </form>
          </div>

          <div className="relative mx-auto w-full max-w-[560px] lg:mt-6">
            <Sheet tilt={0.9} fold className="px-5 pb-4 pt-5" data-hero-map>
              <div className="absolute -right-4 -top-12 z-10 sm:-right-10">
                <Stamp tone="verified" size={92} rotate={13} backed label="Checked by hand: 70 bug pairs">checked<br />by hand<br />70 pairs</Stamp>
              </div>
              <div className="flex items-baseline justify-between gap-3 border-b-[1.5px] border-ink pb-2">
                <span className="font-display text-[20px] font-semibold tracking-[-0.02em]">psf/requests</span>
                <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-pencil">commit {EXAMPLE.commit}</span>
              </div>
              <AtlasSheet />
              <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-rule pt-2 font-mono text-[10.5px] text-pencil">
                <span><span className="text-signal">●</span> changed</span>
                <span><span className="text-signal">◯</span> in the blast</span>
                <span>- - import cycle</span>
                <span>◌ rings = hops</span>
              </div>
            </Sheet>
            <div className="mt-5 pl-10 sm:pl-16">
              <MarginNote tone="hl" arrow="up-right" rotate={-3} className="max-w-[300px]">models.py: changed 17 times recently, and sits in an import cycle</MarginNote>
            </div>
          </div>
        </section>

        <p className="mx-auto max-w-[1240px] 2xl:max-w-[1440px] border-y border-table-line px-4 py-3 font-mono text-[12px] uppercase tracking-[0.12em] text-table-muted sm:px-6">
          Code is read, never run <span className="px-2 text-table-line">/</span> public repositories only <span className="px-2 text-table-line">/</span> free and open source
        </p>

        {/* ---------- the worked example ---------- */}
        <section id="example" className="mx-auto grid max-w-[1240px] 2xl:max-w-[1440px] grid-cols-[minmax(0,1fr)] gap-12 px-4 py-24 sm:px-6 lg:grid-cols-[360px_minmax(0,1fr)]">
          <div className="lg:sticky lg:top-10 lg:self-start">
            <p className="mono-label text-table-muted">A real change, start to finish</p>
            <h2 className="mt-4 font-display text-[clamp(32px,4vw,46px)] font-semibold leading-[1.02] tracking-[-0.035em]">
              One commit to <span className="font-mono text-[0.62em] tracking-normal">models.py</span>. Here is what it reached.
            </h2>
            <p className="mt-5 text-[16px] leading-relaxed text-table-muted">
              Commit <span className="font-mono text-table-ink">{EXAMPLE.commit}</span> in psf/requests changed three files. In {(EXAMPLE.ms / 1000).toFixed(1)} seconds,
              using only static analysis and git history, Blast Radius traced {EXAMPLE.reached} files beyond the change ({EXAMPLE.inBlast} of them strongly), picked the tests to run and
              priced the risk. The three that explain it best:
            </p>
            {requests && (
              <Link to={`/repo/${requests.id}/blast?result=${EXAMPLE.resultId}`} className="group mt-7 inline-flex items-center gap-3 font-mono text-[12px] uppercase tracking-[0.1em] text-table-ink underline decoration-signal decoration-2 underline-offset-[6px]">
                Open this exact result <Arrow />
              </Link>
            )}
          </div>

          <Sheet className="px-5 py-7 sm:px-9" data-example>
            <ol className="flex flex-col">
              <li data-row className="grid grid-cols-[56px_minmax(0,1fr)] gap-4 border-b border-rule pb-5">
                <span className="font-display text-[34px] font-semibold leading-none text-signal-ink">0</span>
                <div>
                  <div className="mono-label">Hop 0 · the change itself</div>
                  <ul className="mt-2 flex flex-col gap-1.5">
                    {EXAMPLE.changed.map((c) => (
                      <li key={c.path} className="flex flex-wrap items-baseline gap-x-3">
                        <span className="font-mono text-[14px] font-medium text-ink">{short(c.path)}</span>
                        <span className="text-[14px] text-ink-2">{c.what}</span>
                        <span className="font-mono text-[12px] text-pencil">+{c.plus} −{c.minus}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </li>
              {[1, 2].map((h) => (
                <li key={h} data-row className="grid grid-cols-[56px_minmax(0,1fr)] gap-4 border-b border-rule py-5">
                  <span className="font-display text-[34px] font-semibold leading-none text-ink">{h}</span>
                  <div>
                    <div className="mono-label">Hop {h} · {h === 1 ? "files that move with it" : "code that calls it"}</div>
                    <ul className="mt-2 flex flex-col gap-1.5">
                      {EXAMPLE.hops.filter((x) => x.hop === h).map((x) => (
                        <li key={x.path} className="flex flex-wrap items-baseline gap-x-3">
                          <span className="font-mono text-[14px] font-medium text-ink">{short(x.path)}</span>
                          <span className="text-[14px] text-ink-2">{x.why}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </li>
              ))}
              <li data-row className="grid grid-cols-[56px_minmax(0,1fr)] gap-4 border-b border-rule py-5">
                <span aria-hidden className="pt-1 text-verified-ink"><Icon name="check" size={26} /></span>
                <div>
                  <div className="mono-label">Tests to run</div>
                  <p className="mt-1.5 text-[15px] text-ink"><span className="font-mono">{EXAMPLE.tests}</span>. Not the whole suite.</p>
                </div>
              </li>
              <li data-row className="relative grid grid-cols-[56px_minmax(0,1fr)] gap-4 pt-5">
                <span className="font-display text-[34px] font-semibold leading-none text-caution-ink">!</span>
                <div className="pr-0 sm:pr-40">
                  <div className="mono-label">Risk</div>
                  <ul className="mt-1.5 flex flex-col gap-1 text-[14.5px] text-ink-2">
                    {EXAMPLE.risk.top.map((t) => <li key={t}>— {t}</li>)}
                  </ul>
                </div>
                <div className="col-span-2 mt-2 justify-self-end sm:absolute sm:-bottom-3 sm:right-0 sm:mt-0">
                  <Stamp tone="caution" shape="rect" rotate={-7} land label={`Risk ${EXAMPLE.risk.score} of 100, ${EXAMPLE.risk.label}`}>risk {EXAMPLE.risk.score} · {EXAMPLE.risk.label}</Stamp>
                </div>
              </li>
            </ol>
          </Sheet>
        </section>

        {/* ---------- what it answers: three different objects, not three identical cards ---------- */}
        <section className="mx-auto max-w-[1240px] 2xl:max-w-[1440px] px-4 py-20 sm:px-6">
          <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-10 lg:grid-cols-[300px_minmax(0,1fr)]">
            <div>
              <p className="mono-label text-table-muted">What else is in the atlas</p>
              <h2 className="mt-4 font-display text-[40px] font-semibold leading-none tracking-[-0.035em]">Questions it answers on day one</h2>
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-8 md:grid-cols-[1.25fr_1fr]">
              <Sheet tilt={-1.1} tape tapeAt="30%" className="p-7">
                <div className="mono-label">Map</div>
                <h3 className="mt-2 font-display text-[26px] font-semibold leading-tight tracking-[-0.02em]">“Where does everything live, and what imports what?”</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-ink-2">Every file on one zoomable plate, grouped by folder. Import cycles are drawn in red, with one path around the loop so you can see it, not just be told about it.</p>
              </Sheet>
              <div className="flex flex-col gap-8">
                <Sheet tilt={0.7} className="p-6">
                  <div className="mono-label">Hotspots</div>
                  <h3 className="mt-2 font-display text-[21px] font-semibold leading-tight">“Which file hurts most to touch?”</h3>
                  <p className="mt-2 text-[14.5px] text-ink-2">Complexity, churn, fan-in and missing tests, with the reason written next to each score.</p>
                </Sheet>
                <Sheet className="p-6">
                  <div className="mono-label">Ask</div>
                  <h3 className="mt-2 font-display text-[21px] font-semibold leading-tight">“How are redirects followed?”</h3>
                  <p className="mt-2 text-[14.5px] text-ink-2">Answers quote the exact lines. Claims that can&apos;t be checked against the code are cut, and “not found” is an allowed answer.</p>
                </Sheet>
              </div>
            </div>
          </div>
          <div className="mt-12 flex justify-end">
            <MarginNote tone="hl" rotate={-2} className="max-w-sm text-right">also: generated docs for every file and folder, and an MCP server so your agent gets the same map</MarginNote>
          </div>
        </section>

        {/* ---------- measured, honestly ---------- */}
        <section id="measured" className="scroll-mt-8 border-t border-table-line">
          <div className="mx-auto grid max-w-[1240px] 2xl:max-w-[1440px] grid-cols-[minmax(0,1fr)] items-start gap-10 px-4 py-24 sm:px-6 lg:grid-cols-[300px_minmax(0,1fr)]">
            <div>
              <p className="mono-label text-table-muted">Measured, not claimed</p>
              <h2 className="mt-4 font-display text-[40px] font-semibold leading-none tracking-[-0.035em]">We tested it on bugs that really happened</h2>
              <p className="mt-5 text-[15.5px] leading-relaxed text-table-muted">
                We mined commits that introduced bugs (SZZ), ran Blast Radius on each one with only the history before it, and checked whether it ranked the file that was later fixed.
                Where it doesn&apos;t win, we say so.
              </p>
              <Link to="/replay" className="group mt-6 inline-flex items-center gap-3 font-mono text-[12px] uppercase tracking-[0.1em] text-table-ink underline decoration-signal decoration-2 underline-offset-[6px]">
                Replay three real bugs, one a miss <Arrow />
              </Link>
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)] gap-8 md:grid-cols-[1.2fr_1fr]">
              <Sheet className="p-7">
                <div className="absolute -right-4 -top-8 sm:-right-6">
                  <Stamp tone="verified" size={92} rotate={10} land backed label={`${EVAL.validated.pairs} pairs confirmed by hand out of ${EVAL.validated.checked} checked`}>{EVAL.validated.pairs} of {EVAL.validated.checked}<br />confirmed</Stamp>
                </div>
                <Figure label={`MRR · ${EVAL.validated.pairs} hand-confirmed bug pairs`} value={EVAL.validated.mrr.toFixed(3)} />
                <div className="mt-5 flex flex-col gap-2">
                  <div className="flex items-center gap-3"><span className="w-28 font-mono text-[11.5px] text-pencil">Blast Radius</span><span className="h-3 bg-ink" style={{ width: `${EVAL.validated.mrr * 60}%` }} /></div>
                  <div className="flex items-center gap-3"><span className="w-28 font-mono text-[11.5px] text-pencil">changed files</span><span className="bg-hatch h-3 border border-rule-strong" style={{ width: `${EVAL.validated.baseline * 60}%` }} /><span className="font-mono text-[11.5px] text-pencil">{EVAL.validated.baseline.toFixed(3)}</span></div>
                </div>
                <p className="mt-5 border-t border-rule pt-4 text-[14.5px] leading-relaxed text-ink-2">
                  On all {EVAL.all.pairs} mined pairs (noisier labels) the gap shrinks to {EVAL.all.mrr} vs {EVAL.all.baseline}, which is <em>not</em> significant. We print both.
                </p>
              </Sheet>
              <Sheet tilt={-0.6} className="p-7">
                <div className="mono-label">The less flattering numbers</div>
                <dl className="mt-4 flex flex-col gap-4 text-[14.5px]">
                  <div><dt className="font-display text-[26px] font-semibold leading-none">{EVAL.beyond.recall10} <span className="font-mono text-[12px] font-normal text-pencil">vs {EVAL.beyond.folder} same-folder guess</span></dt><dd className="mt-1 text-ink-2">recall@10 for files the commit didn&apos;t touch ({EVAL.beyond.pairs} pairs). No better than the simple heuristic, yet.</dd></div>
                  <div><dt className="font-display text-[26px] font-semibold leading-none">{EVAL.tests.median}% <span className="font-mono text-[12px] font-normal text-pencil">of the suite</span></dt><dd className="mt-1 text-ink-2">still catches the fix&apos;s test file in {EVAL.tests.catch}% of cases.</dd></div>
                  <div><dt className="font-display text-[26px] font-semibold leading-none">{EVAL.riskAuc.v1} <span className="font-mono text-[12px] font-normal text-pencil">vs {EVAL.riskAuc.size} for lines changed</span></dt><dd className="mt-1 text-ink-2">risk score AUC. Diff size alone is still a slightly better bug predictor.</dd></div>
                </dl>
              </Sheet>
            </div>
          </div>
        </section>

        {/* ---------- the index of mapped repositories ---------- */}
        {samples.length > 0 && (
          <section className="mx-auto max-w-[1240px] 2xl:max-w-[1440px] px-4 pb-24 sm:px-6" aria-labelledby="index-title">
            <Sheet className="px-5 py-7 sm:px-10">
              <div className="flex flex-wrap items-baseline justify-between gap-3 border-b-2 border-ink pb-3">
                <h2 id="index-title" className="font-display text-[28px] font-semibold tracking-[-0.03em]">Index of mapped repositories</h2>
                <span className="mono-label">open any, no waiting</span>
              </div>
              <ul>
                {samples.map((r) => (
                  <li key={r.id}>
                    <Link to={`/repo/${r.id}/overview`} className="group flex items-baseline gap-3 border-b border-rule py-3 transition-colors hover:bg-paper-2">
                      <span className="font-display text-[19px] font-semibold text-ink group-hover:text-signal-ink">{r.full_name}</span>
                      <span aria-hidden className="mb-1 min-w-6 flex-1 border-b border-dotted border-rule-strong" />
                      <span className="shrink-0 font-mono text-[12.5px] text-pencil">{r.files} files{r.commit_sha ? ` · ${r.commit_sha.slice(0, 7)}` : ""}</span>
                      <span aria-hidden className="shrink-0 text-ink transition-transform group-hover:translate-x-1">→</span>
                    </Link>
                  </li>
                ))}
              </ul>
              {re?.incremental_s != null && (
                <p className="mt-4 text-[13.5px] text-pencil">Re-mapping after a {re.changed}-file change takes {re.incremental_s.toFixed(2)} s instead of {re.full_cold_s?.toFixed(0)} s for a cold run.</p>
              )}
            </Sheet>
          </section>
        )}

        {/* ---------- MCP: on the table, like a terminal on the desk ---------- */}
        <section id="mcp" className="scroll-mt-8 border-t border-table-line">
          <div className="mx-auto grid max-w-[1240px] 2xl:max-w-[1440px] grid-cols-[minmax(0,1fr)] items-center gap-12 px-4 py-24 sm:px-6 lg:grid-cols-[1fr_1.1fr]">
            <div>
              <p className="mono-label text-table-muted">For coding agents</p>
              <h2 className="mt-4 font-display text-[40px] font-semibold leading-none tracking-[-0.035em]">Give your agent the same map</h2>
              <p className="mt-5 max-w-lg text-[16px] leading-relaxed text-table-muted">
                The MCP server lets Claude Code ask for the architecture, a file&apos;s dependencies, the hotspots, a code search, a blast radius or the tests to run:{" "}
                <span className="font-mono text-[13.5px] text-table-ink">get_architecture, get_dependencies, get_hotspots, search_code, find_symbol, explain_file, get_blast_radius, suggest_tests, check_change_risk</span>.
                Read-only, scoped to the repos you allow.
              </p>
              <ButtonAnchor variant="arrow" className="mt-7 text-table-ink" href={`${GITHUB}/blob/main/docs/MCP.md`}>MCP setup guide <Arrow /></ButtonAnchor>
            </div>
            <div className="rounded-ui border border-table-line bg-table-2">
              <div className="flex items-center justify-between border-b border-table-line px-4 py-2">
                <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-table-muted">terminal</span>
                <CopyCommand cmd={MCP_CMD} />
              </div>
              <pre className="overflow-x-auto p-5 font-mono text-[13px] leading-7 text-table-ink">
                <span className="text-table-muted">$ </span>{MCP_CMD}{"\n"}
                <span className="text-verified">✓</span> Added MCP server codeatlas{"\n\n"}
                <span className="text-table-muted">&gt; </span>what does commit 6f66281a in psf/requests put at risk?{"\n"}
                <span className="text-table-signal">get_blast_radius</span>(repo: "psf/requests", commit_sha: "6f66281a"){"\n"}
                <span className="text-table-muted">  sessions.py · __init__.py · compat.py · 4 tests to run</span>
              </pre>
            </div>
          </div>
        </section>
      </main>
      <Colophon />
    </div>
  );
}
