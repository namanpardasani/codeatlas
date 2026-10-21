import { motion } from "framer-motion";
import { lazy, Suspense, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, MonoLabel, Panel, ScoreBar, Skeleton, StatCard, Table, type Column } from "../components/ui";
import type { HotspotItem } from "../api";
import { Dialog } from "../features/Dialog";
import { basename, useRepo } from "../hooks/RepoData";
import { rise } from "../ui/motion";

const CodeViewer = lazy(() => import("../features/CodeViewer"));

const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2]! : (s[s.length / 2 - 1]! + s[s.length / 2]!) / 2;
};

export default function Overview() {
  const { repoId, files, hotspots, graph, error } = useRepo();
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
  const shades = ["bg-text-3", "bg-muted", "bg-dim", "bg-faint", "bg-border-strong", "bg-ghost"];
  const question = central[0] ? `How does ${basename(central[0].path)} work, and what depends on it?` : "Where is the main entry point?";

  const cols: Column<HotspotItem>[] = [
    { header: "File", render: (r) => <span className="font-mono text-small text-text-2" title={r.path}>{r.path}</span> },
    { header: "Score", render: (r) => (r.hotspot_score === null ? "—" : <ScoreBar value={r.hotspot_score} delay={0.15} />) },
    { header: "Why", render: (r) => (r.hotspot_reasons[0] ? <Badge tone={(r.hotspot_score ?? 0) > 70 ? "amber" : "neutral"}>{r.hotspot_reasons[0].factor.replace(/_/g, " ")}</Badge> : "—") },
    { header: "Commits", className: "text-right font-mono tabular-nums", render: (r) => r.commits_total ?? "—" },
  ];

  if (error) return <ErrorState message={error} />;
  const fmt = (v: number | null | undefined, suffix = "") => (v === null || v === undefined ? "—" : `${Number.isInteger(v) ? v.toLocaleString() : v.toFixed(1)}${suffix}`);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <MonoLabel>PLATE 01 ——— OVERVIEW</MonoLabel>
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {!stats
          ? Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-24 rounded-card" />)
          : [
              { label: "Files", value: fmt(stats.files) },
              { label: "Symbols", value: fmt(stats.symbols) },
              { label: "Import edges", value: stats.edges === null ? "—" : `${stats.edges.toLocaleString()}${stats.edgesCapped ? "+" : ""}`, hint: "between source files" },
              { label: "Import cycles", value: fmt(stats.cycles), risk: (stats.cycles ?? 0) > 0, hint: "groups of files that import each other" },
              { label: "Median complexity", value: fmt(stats.complexity), hint: "worst function per file" },
            ].map((s, i) => (
              <motion.div key={s.label} {...rise(i)} className="h-full">
                <StatCard {...s} />
              </motion.div>
            ))}
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
        <Panel title="Top hotspots" label="PLATE 02" actions={<Link className="text-small text-cyan underline" to={`/repo/${repoId}/hotspots`}>All hotspots</Link>}>
          {!hotspots ? (
            <div className="flex flex-col gap-3"><Skeleton className="h-8" /><Skeleton className="h-8" /><Skeleton className="h-8" /></div>
          ) : top.length === 0 ? (
            <EmptyState message="No scored files: this repository has no analysable code with history yet." />
          ) : (
            <motion.div {...rise(0, 8)}>
              <Table columns={cols} rows={top} rowKey={(r) => r.id} onRowClick={(r) => setViewer({ path: r.path, start: 1, end: Math.min(r.lines, 40) })} />
            </motion.div>
          )}
        </Panel>

        <div className="flex flex-col gap-6">
          <Panel title="Languages" label="PLATE 03">
            {languages.length === 0 ? (
              <p className="text-small text-muted">—</p>
            ) : (
              <>
                <div className="flex h-2.5 overflow-hidden rounded-full bg-line" role="img" aria-label={languages.map((l) => `${l.name} ${l.pct.toFixed(0)}%`).join(", ")}>
                  {languages.map((l, i) => (
                    <motion.span key={l.name} className={shades[i % shades.length]} initial={{ width: 0 }} animate={{ width: `${l.pct}%` }} transition={{ duration: 0.9, delay: 0.1 + i * 0.06, ease: [0.2, 0.7, 0.2, 1] }} />
                  ))}
                </div>
                <ul className="mt-4 flex flex-col gap-1.5">
                  {languages.map((l, i) => (
                    <li key={l.name} className="flex items-center justify-between text-small">
                      <span className="flex items-center gap-2 text-text-3"><span aria-hidden className={`size-2 rounded-full ${shades[i % shades.length]}`} />{l.name}</span>
                      <span className="font-mono text-muted">{l.pct.toFixed(0)}%</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Panel>

          <Panel title="Most central files" label="PLATE 04">
            {central.length === 0 ? (
              <p className="text-small text-muted">—</p>
            ) : (
              <ul className="flex flex-col gap-2.5">
                {central.map((n) => (
                  <li key={n.id} className="flex items-center justify-between gap-3">
                    <span className="min-w-0 truncate font-mono text-small text-text-2" title={n.path}>{n.path}</span>
                    <span className="shrink-0 font-mono text-small text-cyan-soft">{n.fan_in} dependents</span>
                  </li>
                ))}
              </ul>
            )}
            <Link className="mt-4 inline-block text-small text-cyan underline" to={`/repo/${repoId}/map`}>Open the map →</Link>
          </Panel>

          <Card variant="tint">
            <MonoLabel>ASK THIS REPO</MonoLabel>
            <p className="mt-2 text-body text-cyan-soft">“{question}”</p>
            <Link className="mt-3 inline-block text-small text-cyan underline" to={`/repo/${repoId}/ask?q=${encodeURIComponent(question)}`}>Ask this question →</Link>
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
