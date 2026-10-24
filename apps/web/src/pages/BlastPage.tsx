import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getBlast, getBlastList, runBlast, type BlastListItem, type BlastResult } from "../api";
import { Arrow, Badge, Button, Card, EmptyState, ErrorState, Icon, PageHead, Panel, ScoreBar, Segmented, Skeleton, Stamp } from "../components/ui";
import { Dialog } from "../features/Dialog";
import { RippleMap } from "../features/RippleMap";
import { useRepo } from "../hooks/RepoData";
import { useMe } from "../hooks/useMe";

const CodeViewer = lazy(() => import("../features/CodeViewer"));

type Mode = "pr" | "commit" | "diff";
const MODES: { id: Mode; label: string }[] = [
  { id: "pr", label: "Pull request" },
  { id: "commit", label: "Commit" },
  { id: "diff", label: "Diff" },
];
const riskTone = (l: string) => (l === "high" ? "signal" : l === "medium" ? "caution" : "verified") as "signal" | "caution" | "verified";

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button variant="arrow" size="sm" onClick={() => navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); })}>
      {done ? "Copied" : "Copy"}
    </Button>
  );
}

export default function BlastPage() {
  const { repoId, graph, name } = useRepo();
  const { me } = useMe();
  const [params, setParams] = useSearchParams();
  const [mode, setMode] = useState<Mode>("pr");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BlastResult | null>(null);
  const [recent, setRecent] = useState<BlastListItem[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [replay, setReplay] = useState(0);
  const [viewer, setViewer] = useState<string | null>(null);
  const [tab, setTab] = useState<"files" | "symbols">("files");

  useEffect(() => {
    getBlastList(repoId).then(setRecent).catch(() => setRecent([]));
  }, [repoId, result?.id]);

  // ?result=<id> (the PR comment links here) loads a stored result
  const resultParam = params.get("result");
  useEffect(() => {
    if (!resultParam || resultParam === result?.id) return;
    setBusy(true);
    getBlast(resultParam).then((r) => { setResult(r); setError(null); }).catch((e) => setError(e.message)).finally(() => setBusy(false));
  }, [resultParam]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await runBlast(repoId, mode === "pr" ? { pr_url: value.trim() } : mode === "commit" ? { commit_sha: value.trim() } : { diff: value });
      setResult(r);
      setSelected(null);
      setReplay((k) => k + 1);
      setParams({ result: r.id }, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setBusy(false);
    }
  }

  const beyond = useMemo(() => (result?.impact?.files ?? []).filter((f) => f.distance > 0), [result]);
  const pathOf = (p: string | null) => {
    if (!p || !result?.impact) return [] as string[];
    const item = result.impact.files.find((f) => f.path === p) ?? result.impact.symbols.find((s) => s.path === p);
    return item ? [...new Set(item.why.map((s) => s.node[1]))] : [p];
  };
  const placeholder = mode === "pr" ? `https://github.com/${name ?? "owner/repo"}/pull/123` : mode === "commit" ? "commit SHA, e.g. 6f66281a" : "paste the output of git diff";

  const strong = beyond.filter((f) => f.score >= 0.1).length;   // the same cut the risk score uses for "breadth"
  const changedFns = result ? result.change.files.reduce((a, f) => a + f.symbols.length, 0) : 0;

  return (
    <div className="flex flex-col gap-10">
      <PageHead sheet="Sheet 03 · Blast Radius" title="What will this change break?">
        The functions it touches, who calls and imports them, the files that usually change with them, the tests to run and a risk
        score. Static analysis and git history only; nothing is executed.{" "}
        <a href="/replay" className="font-medium text-ink underline decoration-signal decoration-[1.5px] underline-offset-4 hover:text-signal-ink">See it replayed on real past bugs</a>.
      </PageHead>

      <form onSubmit={submit} className="flex flex-col gap-4 bg-paper-2 p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Segmented label="Input type" value={mode} onChange={(m) => { setMode(m); setValue(""); }} options={MODES} />
          {me?.demoMode && <span className="text-small text-pencil">Read-only demo: open one of the saved results below.</span>}
        </div>
        <label htmlFor="blast-input" className="sr-only">{MODES.find((m) => m.id === mode)?.label}</label>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          {mode === "diff" ? (
            <textarea id="blast-input" value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder} rows={7} spellCheck={false}
                      className="w-full border-[1.5px] border-ink bg-paper p-3 font-mono text-[12.5px] text-ink outline-none placeholder:text-pencil focus-visible:border-signal focus-visible:outline-none" />
          ) : (
            <input id="blast-input" value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder} autoComplete="off" spellCheck={false}
                   className="min-h-11 w-full border-0 border-b-2 border-ink bg-transparent px-1 font-mono text-[15px] text-ink outline-none placeholder:text-pencil focus-visible:border-signal focus-visible:outline-none" />
          )}
          <Button type="submit" disabled={busy || !value.trim()} className="shrink-0">
            {busy ? "Tracing…" : "Trace the blast"}
          </Button>
        </div>
        {error && <p role="alert" className="text-small text-signal-ink">{error}</p>}
        {recent && recent.length > 0 && (
          <div className="border-t border-rule pt-3">
            <div className="mono-label mb-2">Recent results</div>
            <ul className="flex flex-wrap gap-x-5 gap-y-1.5">
              {recent.slice(0, 8).map((r) => (
                <li key={r.id}>
                  <button onClick={() => setParams({ result: r.id })} className={`group flex items-baseline gap-2 text-left text-small ${result?.id === r.id ? "text-ink" : "text-ink-2"}`}>
                    <span className={`font-mono text-[12px] font-semibold ${r.risk_label === "high" ? "text-signal-ink" : r.risk_label === "medium" ? "text-caution-ink" : "text-verified-ink"}`}>{r.risk_score ?? "?"}</span>
                    <span className={`max-w-[260px] truncate font-mono underline-offset-4 group-hover:underline ${result?.id === r.id ? "underline decoration-signal" : ""}`}>{r.title ?? (r.kind === "pr" ? r.ref.replace(/^https:\/\/github\.com\//, "") : r.ref.slice(0, 12))}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </form>

      {busy && !result && <Skeleton className="h-96" />}
      {!result && !busy && !error && (
        <EmptyState
          message="Paste a pull request link, a commit SHA or a diff. You'll get the files it reaches, why, and the tests to run."
          action={recent && recent.length > 0 ? (
            <Button variant="secondary" onClick={() => setParams({ result: recent[0]!.id })}>
              Or open a saved example: risk {recent[0]!.risk_score ?? "?"}, {recent[0]!.title ?? recent[0]!.ref.slice(0, 8)}
            </Button>
          ) : undefined}
        />
      )}

      {result && !result.impact && (
        <Card variant="ruled"><p className="text-ink-2">This is the repository&apos;s first commit: nothing existed before it, so nothing can break.</p></Card>
      )}

      {result && result.impact && (
        <>
          {/* the verdict, written as a sentence */}
          <section className="relative grid grid-cols-[minmax(0,1fr)] gap-8 border-t-2 border-ink pt-6 lg:grid-cols-[minmax(0,1fr)_260px]">
            <div>
              <div className="mono-label">
                {result.pr ? <>PR #{result.pr.number} by {result.pr.author}</> : result.input?.kind === "commit" ? <>Commit {String(result.input.ref).slice(0, 8)}</> : "Your diff"}
              </div>
              {result.pr && <p className="mt-1 font-display text-[19px] italic text-ink-2">{result.pr.title}</p>}
              <p className="mt-3 max-w-3xl font-display text-[clamp(26px,3vw,36px)] font-semibold leading-[1.12] tracking-[-0.025em] text-ink">
                It changes {result.change.files.length} file{result.change.files.length === 1 ? "" : "s"} and {changedFns} function{changedFns === 1 ? "" : "s"}, and reaches{" "}
                <span className="text-signal-ink underline decoration-signal decoration-2 underline-offset-[6px]">{beyond.length} more file{beyond.length === 1 ? "" : "s"}</span>
                {strong > 0 && strong < beyond.length ? <> ({strong} strongly)</> : null}.{" "}
                {result.tests && (result.tests.full_suite ? "Run the full test suite." : <>Run {result.tests.selected_count} of {result.tests.total} tests.</>)}
              </p>
              {result.risk && (
                <ul className="mt-5 grid gap-x-8 gap-y-1.5 text-[14.5px] text-ink-2 md:grid-cols-2">
                  {result.risk.top_factors.map((f) => <li key={f} className="flex gap-2"><span aria-hidden className="text-pencil">—</span>{f}</li>)}
                </ul>
              )}
            </div>
            {result.risk && (
              <div className="flex items-start justify-start lg:justify-center">
                <Stamp tone={riskTone(result.risk.label)} size={150} rotate={-9} land label={`Risk ${result.risk.score} of 100, ${result.risk.label}`}>
                  <span className="block text-[11px] tracking-[0.2em]">risk</span>
                  <span className="block font-display text-[46px] font-semibold leading-none tracking-[-0.02em] normal-case">{result.risk.score}</span>
                  <span className="block text-[11px] tracking-[0.2em]">{result.risk.label}</span>
                </Stamp>
              </div>
            )}
          </section>

          {result.risk && result.risk.missing_cochanges.length > 0 && (
            <Card variant="risk">
              <div className="mono-label text-signal-ink">Possibly forgotten</div>
              <ul className="mt-2 flex flex-col gap-1.5 text-[14.5px] text-ink-2">
                {result.risk.missing_cochanges.slice(0, 4).map((m) => (
                  <li key={m.file}><span className="font-mono text-ink">{m.file}</span> usually changes with <span className="font-mono">{m.partner_of.split("/").pop()}</span> ({Math.round(m.confidence * 100)}% of its commits), but isn&apos;t in this change.</li>
                ))}
              </ul>
            </Card>
          )}

          <Panel title="The ripple" description="Impact spreading out from the change, one hop at a time. Click a lit file to see why it is affected."
                 actions={<Button variant="arrow" size="sm" onClick={() => setReplay((k) => k + 1)}>Replay</Button>}>
            {graph ? <RippleMap graph={graph} result={result} highlight={pathOf(selected)} replayKey={replay} onPick={setSelected} />
                   : <Skeleton className="h-[460px]" />}
          </Panel>

          <div className="grid grid-cols-[minmax(0,1fr)] gap-x-12 gap-y-12 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            <Panel title="What it could break" description="Ranked by impact. Open one to read the chain of reasons."
                   actions={<Segmented label="List" value={tab} onChange={setTab} options={[{ id: "files", label: "Files" }, { id: "symbols", label: "Functions" }]} />}>
              <ol className="flex flex-col">
                {(tab === "files" ? result.impact.files : result.impact.symbols).slice(0, 40).map((it, n) => {
                  const key = "name" in it ? `${it.path}::${it.name}` : it.path;
                  const on = selected === it.path;
                  return (
                    <li key={key} className="border-b border-rule">
                      <button onClick={() => setSelected(on ? null : it.path)} aria-expanded={on}
                              className={`grid w-full grid-cols-[28px_minmax(0,1fr)_auto] items-start gap-3 px-1 py-2.5 text-left transition-colors hover:bg-paper-2 ${on ? "bg-hl-soft shadow-[inset_3px_0_0_var(--ink)] hover:bg-hl-soft" : ""}`}>
                        <span className="pt-0.5 font-mono text-[11px] text-pencil">{String(n + 1).padStart(2, "0")}</span>
                        <span className="min-w-0">
                          <span className="block truncate font-mono text-small text-ink">{"name" in it ? it.name : it.path}</span>
                          <span className="mt-0.5 block text-[12.5px] text-ink-2">{"name" in it ? `${it.path} · ` : ""}{it.reason}</span>
                        </span>
                        <span className="flex shrink-0 items-center gap-2.5">
                          {it.distance === 0 ? <Badge tone="danger">changed</Badge> : <Badge tone="accent">{it.distance} hop{it.distance > 1 ? "s" : ""}</Badge>}
                          <span className="hidden sm:block"><ScoreBar value={Math.round(it.score * 100)} /></span>
                        </span>
                      </button>
                      {on && (
                        <div className="mb-3 ml-9 mt-1 border-l-2 border-ink pl-4">
                          <ol className="flex flex-col gap-1 text-[13px] text-ink-2">
                            {it.why.map((st, i) => <li key={i} className="flex gap-2"><span className="font-mono text-pencil">{i === 0 ? "●" : "↳"}</span>{st.reason}</li>)}
                          </ol>
                          <Button variant="secondary" size="sm" className="mt-3" onClick={() => setViewer(it.path)}>Open the code</Button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
            </Panel>

            <div className="flex flex-col gap-12">
              {result.tests && (
                <Panel title="Tests to run" description={result.tests.full_suite ? undefined : result.tests.summary}>
                  {result.tests.full_suite && (
                    <Card variant="risk" className="mb-3 text-small">Run the full suite: {result.tests.full_suite_reasons.join("; ")}</Card>
                  )}
                  {result.tests.command && (
                    <div className="flex items-start gap-2">
                      <pre tabIndex={0} aria-label="Test command" className="min-w-0 flex-1 overflow-x-auto bg-table p-3 font-mono text-[12px] leading-relaxed text-table-ink">{result.tests.command}</pre>
                      <CopyButton text={result.tests.command} />
                    </div>
                  )}
                  <ul className="mt-3 flex max-h-72 flex-col overflow-y-auto">
                    {result.tests.new_tests.map((t) => (
                      <li key={`n-${t.file}-${t.name}`} className="flex items-center gap-2 border-b border-rule py-1.5 text-[12.5px]"><Badge tone="success">new</Badge><span className="truncate font-mono text-ink-2">{t.file}::{t.name}</span></li>
                    ))}
                    {result.tests.selected.slice(0, 60).map((t) => (
                      <li key={`${t.file}-${t.name}`} className="flex items-center gap-2 border-b border-rule py-1.5 text-[12.5px]" title={t.reason}>
                        <span className="w-10 shrink-0 font-mono text-pencil">{t.score.toFixed(2)}</span>
                        <span className="truncate font-mono text-ink-2">{t.file}::{t.name}</span>
                      </li>
                    ))}
                  </ul>
                </Panel>
              )}
              <Panel title="In this diff">
                <ul className="flex flex-col">
                  {result.change.files.slice(0, 30).map((f) => (
                    <li key={f.path} className="border-b border-rule py-2 text-small">
                      <span className="flex items-baseline gap-2">
                        {f.category !== "code" && <Badge>{f.category}</Badge>}
                        <span className="min-w-0 truncate font-mono text-ink">{f.path}</span>
                        <span className="ml-auto shrink-0 font-mono text-[11.5px]"><span className="text-verified-ink">+{f.added}</span> <span className="text-signal-ink">−{f.deleted}</span></span>
                      </span>
                      {f.symbols.length > 0 && <span className="mt-0.5 block text-[12.5px] text-pencil">{f.symbols.slice(0, 6).map((sy) => `${sy.change} ${sy.name}`).join(", ")}</span>}
                      {f.error && <span className="block text-[12px] text-signal-ink">{f.error}</span>}
                    </li>
                  ))}
                </ul>
              </Panel>
              {result.reviewers.length > 0 && (
                <Panel title="Who knows this code" description="Recent authors of the touched files.">
                  <ul className="flex flex-col gap-2 text-small">
                    {result.reviewers.map((v) => <li key={v.name}><span className="font-medium text-ink">{v.name}</span><span className="block text-pencil">{v.reason}</span></li>)}
                  </ul>
                </Panel>
              )}
            </div>
          </div>
        </>
      )}
      {error && !result && <ErrorState message={error} />}

      <Dialog open={viewer !== null} title="Code" onClose={() => setViewer(null)} wide>
        <div className="h-[60vh]">
          {viewer && (
            <Suspense fallback={<Skeleton className="h-full w-full" />}>
              <CodeViewer repoId={repoId} target={{ path: viewer, start: 1, end: 1 }} onClose={() => setViewer(null)} />
            </Suspense>
          )}
        </div>
      </Dialog>
    </div>
  );
}
