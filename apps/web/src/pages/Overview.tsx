import { motion } from "motion/react";
import { lazy, Suspense, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Arrow, ButtonLink, Card, EmptyState, ErrorState, PageHead, Panel, ScoreBar, Skeleton, Table, type Column } from "../components/ui";
import type { HotspotItem } from "../api";
import { Dialog } from "../features/Dialog";
import { basename, useRepo } from "../hooks/RepoData";

const CodeViewer = lazy(() => import("../features/CodeViewer"));

const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2]! : (s[s.length / 2 - 1]! + s[s.length / 2]!) / 2;
};

/** A number set inside a sentence: heavier, ink, tabular. */
const Num = ({ children }: { children: React.ReactNode }) => <span className="font-semibold tabular-nums text-ink">{children}</span>;

export default function Overview() {
  const { repoId, files, hotspots, graph, error, name } = useRepo();
  const [viewer, setViewer] = useState<{ path: string; start: number; end: number } | null>(null);

  const stats = useMemo(() => {
    if (!files) return null;
    const items = hotspots?.items ?? [];
    const mc = median(items.map((i) => i.max_complexity).filter((v): v is number => v !== null));
    return {
      files: files.length,
      symbols: files.reduce((a, f) => a + f.symbol_count, 0),
      edges: graph ? graph.edges.length : null,
      edgesCapped: Boolean(graph?.truncated),
      cycles: graph ? graph.cycles.length : null,
      complexity: mc,
    };
  }, [files, hotspots, graph]);

  const languages = useMemo(() => {
    if (!files) return [];
    const by = new Map<string, number>();
    for (const f of files) if (f.language) by.set(f.language, (by.get(f.language) ?? 0) + f.lines);
    const all = [...by.entries()].sort((a, b) => b[1] - a[1]);
    const total = all.reduce((a, [, n]) => a + n, 0) || 1;
    const top = all.slice(0, 5);
    const rest = all.slice(5).reduce((a, [, n]) => a + n, 0);
    return [...top, ...(rest ? ([["other", rest]] as [string, number][]) : [])].map(([name, n]) => ({ name, n, pct: (n / total) * 100 }));
  }, [files]);

  const central = useMemo(() => (graph ? [...graph.nodes].sort((a, b) => Number(b.pagerank) - Number(a.pagerank)).slice(0, 5) : []), [graph]);
  const top = (hotspots?.items ?? []).slice(0, 8);
  // categorical chart tokens (labels always carry the name and percentage, colour is never the only signal)
  const shades = ["bg-chart-1", "bg-chart-2", "bg-chart-3", "bg-chart-4", "bg-chart-5", "bg-chart-6"];
  const question = central[0] ? `How does ${basename(central[0].path)} work, and what depends on it?` : "Where is the main entry point?";

  const cols: Column<HotspotItem>[] = [
    { header: "File", render: (r) => <span className="font-mono text-small text-ink" title={r.path}>{r.path}</span> },
    { header: "Score", render: (r) => (r.hotspot_score === null ? "—" : <ScoreBar value={r.hotspot_score} delay={0.15} />) },
    { header: "Why", className: "hidden md:table-cell", render: (r) => (r.hotspot_reasons[0] ? <span className="text-small text-ink-2" title={r.hotspot_reasons[0].text}>{r.hotspot_reasons[0].text.split(/[;(]/)[0]!.trim()}</span> : "—") },
    { header: "Commits", className: "hidden text-right font-mono tabular-nums sm:table-cell", render: (r) => r.commits_total ?? "—" },
  ];

  if (error) return <ErrorState message={error} />;
  const fmt = (v: number | null | undefined, suffix = "") => (v === null || v === undefined ? "—" : `${Number.isInteger(v) ? v.toLocaleString() : v.toFixed(1)}${suffix}`);

  return (
    <div className="flex flex-col gap-12">
      <PageHead sheet="Sheet 01 · Overview" title={<>The lay of the land</>}>
        Size, the files that would hurt most to change, and where to start reading.
      </PageHead>

      {/* the numbers, written as a sentence instead of a row of stat tiles */}
      <div className="border-y border-rule py-7">
        {!stats ? (
          <div className="flex flex-col gap-3"><Skeleton className="h-8 w-4/5" /><Skeleton className="h-8 w-3/5" /></div>
        ) : (
          <p className="max-w-5xl font-display text-[clamp(22px,2.6vw,32px)] font-normal leading-[1.3] tracking-[-0.015em] text-ink-2 [font-variation-settings:'SOFT'_60]">
            {name ?? "This repository"} has <Num>{fmt(stats.files)}</Num> files and <Num>{fmt(stats.symbols)}</Num> functions and classes,
            joined by <Num>{stats.edges === null ? "—" : `${stats.edges.toLocaleString()}${stats.edgesCapped ? "+" : ""}`}</Num> imports.{" "}
            {(stats.cycles ?? 0) > 0 ? (
              <><span className="font-semibold text-signal-ink underline decoration-signal decoration-2 underline-offset-[5px]">{stats.cycles} import cycle{stats.cycles === 1 ? "" : "s"}</span> tie{stats.cycles === 1 ? "s" : ""} files into knots.{" "}</>
            ) : <>No import cycles.{" "}</>}
            {stats.complexity !== null && <>In a typical file the most tangled function has a complexity of <Num>{fmt(stats.complexity)}</Num>.</>}
          </p>
        )}
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-x-12 gap-y-12 lg:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
        <Panel title="Where it would hurt to change something" description="The top hotspots. Click a row to read the file." actions={<ButtonLink variant="arrow" size="sm" to={`/repo/${repoId}/hotspots`}>All files <Arrow /></ButtonLink>}>
          {!hotspots ? (
            <div className="flex flex-col gap-3"><Skeleton className="h-8" /><Skeleton className="h-8" /><Skeleton className="h-8" /></div>
          ) : top.length === 0 ? (
            <EmptyState message="No scored files: this repository has no analysable code with history yet." />
          ) : (
            <Table columns={cols} rows={top} rowKey={(r) => r.id} onRowClick={(r) => setViewer({ path: r.path, start: 1, end: Math.min(r.lines, 40) })} />
          )}
        </Panel>

        <div className="flex flex-col gap-12">
          <Panel title="Languages" description="Share of lines.">
            {languages.length === 0 ? (
              <p className="text-small text-pencil">—</p>
            ) : (
              <>
                <div className="flex h-4 border border-ink" role="img" aria-label={languages.map((l) => `${l.name} ${l.pct.toFixed(0)}%`).join(", ")}>
                  {languages.map((l, i) => (
                    <motion.span key={l.name} className={`${shades[i % shades.length]} border-r border-paper last:border-r-0`} initial={{ width: 0 }} animate={{ width: `${l.pct}%` }} transition={{ duration: 0.9, delay: 0.1 + i * 0.06, ease: [0.2, 0.7, 0.2, 1] }} />
                  ))}
                </div>
                <ul className="mt-4 flex flex-col">
                  {languages.map((l, i) => (
                    <li key={l.name} className="flex items-baseline gap-2 py-1 text-small">
                      <span aria-hidden className={`size-2.5 shrink-0 translate-y-[1px] ${shades[i % shades.length]}`} />
                      <span className="text-ink-2">{l.name}</span>
                      <span aria-hidden className="flex-1 border-b border-dotted border-rule-strong" />
                      <span className="font-mono text-pencil">{l.pct < 1 ? "<1" : l.pct.toFixed(0)}%</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Panel>

          <Panel title="Start reading here" description="The files most others import.">
            {central.length === 0 ? (
              <p className="text-small text-pencil">—</p>
            ) : (
              <ol className="flex flex-col">
                {central.map((n, i) => (
                  <li key={n.id} className="flex items-baseline gap-2 py-1.5">
                    <span className="w-5 font-mono text-[11px] text-pencil">{i + 1}.</span>
                    <span className="min-w-0 truncate font-mono text-small text-ink" title={n.path}>{basename(n.path)}</span>
                    <span aria-hidden className="min-w-4 flex-1 border-b border-dotted border-rule-strong" />
                    <span className="shrink-0 text-small text-pencil"><span className="font-mono text-ink">{n.fan_in}</span> importer{Number(n.fan_in) === 1 ? "" : "s"}</span>
                  </li>
                ))}
              </ol>
            )}
            <ButtonLink variant="arrow" size="sm" className="mt-5" to={`/repo/${repoId}/map`}>Open the map <Arrow /></ButtonLink>
          </Panel>

          <Card variant="note" tilt={-1.2}>
            <div className="mono-label text-ink-2">Try asking</div>
            <p className="mt-2 font-display text-[19px] font-semibold leading-snug text-ink">“{question}”</p>
            <ButtonLink size="sm" className="mt-4" to={`/repo/${repoId}/ask?q=${encodeURIComponent(question)}`}>Ask this</ButtonLink>
          </Card>
        </div>
      </div>

      <Dialog open={viewer !== null} title="File viewer" onClose={() => setViewer(null)} wide>
        <div className="h-[60vh]">
          {viewer && (
            <Suspense fallback={<Skeleton className="h-full w-full" />}>
              <CodeViewer repoId={repoId} target={viewer} onClose={() => setViewer(null)} />
            </Suspense>
          )}
        </div>
      </Dialog>
    </div>
  );
}
