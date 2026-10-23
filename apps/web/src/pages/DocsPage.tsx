import { lazy, Suspense, useEffect, useState } from "react";
import { docsExportUrl, getDocPage, getDocsStatus, getDocsTree, type DocNode, type DocPage, type DocsStatus } from "../api";
import { Arrow, Button, ButtonAnchor, EmptyState, ErrorState, PageHead, Skeleton } from "../components/ui";
import { Markdown } from "../components/ui/Markdown";
import { Dialog } from "../features/Dialog";
import { useRepo } from "../hooks/RepoData";

const CodeViewer = lazy(() => import("../features/CodeViewer"));
type Sel = { type: "repo" | "folder" | "file"; path: string };

function Chevron({ open }: { open: boolean }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden className="transition-transform duration-150" style={{ transform: open ? "rotate(90deg)" : "none" }}>
      <path d="M3 1.5 L7 5 L3 8.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Tree({ nodes, sel, open, toggle, pick, depth = 0 }: { nodes: DocNode[]; sel: Sel; open: Set<string>; toggle: (p: string) => void; pick: (s: Sel) => void; depth?: number }) {
  return (
    <ul className="flex flex-col" role={depth === 0 ? "tree" : "group"}>
      {nodes.map((n) => {
        const isOpen = open.has(n.path);
        const selected = sel.type === n.type && sel.path === n.path;
        return (
          <li key={`${n.type}:${n.path}`} role="treeitem" aria-expanded={n.type === "folder" ? isOpen : undefined} aria-selected={selected}>
            <div className={`flex items-center ${selected ? "bg-hl-soft text-ink shadow-[inset_3px_0_0_var(--ink)]" : "text-ink-2 hover:bg-paper-2"}`} style={{ paddingLeft: `${0.25 + depth * 0.9}rem` }}>
              {n.type === "folder" ? (
                <button className="flex size-7 items-center justify-center text-pencil hover:text-ink" onClick={() => toggle(n.path)} aria-label={`${isOpen ? "Collapse" : "Expand"} ${n.name}`}>
                  <Chevron open={isOpen} />
                </button>
              ) : <span className="size-7" />}
              <button
                className="min-h-8 flex-1 truncate py-1 pr-2 text-left font-mono text-small"
                title={n.summary}
                onClick={() => { pick({ type: n.type, path: n.path }); if (n.type === "folder" && !isOpen) toggle(n.path); }}
              >
                {n.name}{n.type === "folder" ? "/" : ""}
                {n.source === "extractive" && <span className="ml-1 text-pencil" title="assembled without a model">·</span>}
              </button>
            </div>
            {n.type === "folder" && isOpen && n.children && <Tree nodes={n.children} sel={sel} open={open} toggle={toggle} pick={pick} depth={depth + 1} />}
          </li>
        );
      })}
    </ul>
  );
}

export default function DocsPage() {
  const { repoId } = useRepo();
  const [status, setStatus] = useState<DocsStatus | null>(null);
  const [tree, setTree] = useState<DocNode[]>([]);
  const [sel, setSel] = useState<Sel>({ type: "repo", path: "" });
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [page, setPage] = useState<DocPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState(false);

  // docs are written after the analysis finishes: poll while they are still being generated
  useEffect(() => {
    let stop = false;
    const load = () =>
      getDocsStatus(repoId).then((s) => {
        if (stop) return;
        setStatus(s);
        if (s.targets > 0) getDocsTree(repoId).then((t) => !stop && setTree(t.tree)).catch(() => {});
        if (s.docs_status === "running") setTimeout(load, 4000);
      }).catch(() => !stop && setError("Could not load the documentation status."));
    load();
    return () => { stop = true; };
  }, [repoId]);

  useEffect(() => {
    setPage(null);
    if (!status || status.targets === 0) return;
    setError(null);
    getDocPage(repoId, sel.type, sel.path).then(setPage).catch((e) => setError(e instanceof Error ? e.message : "Could not load this page"));
  }, [repoId, sel, status?.targets, status?.docs_generated_at]);

  const toggle = (p: string) => setOpen((o) => { const n = new Set(o); n.has(p) ? n.delete(p) : n.add(p); return n; });
  const navigate = (type: Sel["type"], path: string) => {
    setSel({ type, path });
    const parts = path.split("/").slice(0, type === "file" ? -1 : undefined);
    setOpen((o) => { const n = new Set(o); parts.forEach((_, i) => n.add(parts.slice(0, i + 1).join("/"))); return n; });
  };

  if (error && !status) return <ErrorState message={error} />;
  if (!status) return <div className="grid gap-5 lg:grid-cols-[280px_1fr]"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>;
  if (status.targets === 0)
    return status.docs_status === "running"
      ? <EmptyState message="The documentation is being written. This page fills in as summaries finish." />
      : <EmptyState message="Documentation has not been generated for this repository yet." />;

  return (
    <div className="flex flex-col gap-10">
      <PageHead
        sheet="Sheet 06 · Docs"
        title="The guidebook"
        actions={<ButtonAnchor variant="arrow" size="sm" href={docsExportUrl(repoId)} download>Export Markdown <Arrow dir="down" /></ButtonAnchor>}
      >
        {status.llm > 0
          ? <>{status.llm} pages drafted by a model and checked against the code{status.extractive > 0 ? `, ${status.extractive} assembled from names and docstrings (marked ·)` : ""}.</>
          : <>{status.extractive} pages, all assembled from names, docstrings and the import graph. No model wrote any of it.</>}
        {status.docs_status === "running" && " More pages are still being written."}
      </PageHead>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-8 lg:grid-cols-[260px_minmax(0,1fr)]">
        <nav aria-label="Modules" className="max-h-[70vh] overflow-y-auto border-t-2 border-ink pt-2 lg:sticky lg:top-6">
          <div className="mono-label px-1 py-2">Contents</div>
          <button
            className={`mb-1 flex min-h-8 w-full items-center px-3 text-left font-display text-[16px] font-semibold ${sel.type === "repo" ? "bg-hl-soft text-ink shadow-[inset_3px_0_0_var(--ink)]" : "text-ink-2 hover:bg-paper-2"}`}
            onClick={() => setSel({ type: "repo", path: "" })}
          >
            The whole repository
          </button>
          <Tree nodes={tree} sel={sel} open={open} toggle={toggle} pick={setSel} />
        </nav>
        <article className="min-w-0 border-t-2 border-ink pt-6 lg:border-l lg:border-t-0 lg:border-l-rule lg:pl-10 lg:pt-1">
          {error && <ErrorState message={error} />}
          {!page && !error && <div className="flex flex-col gap-3"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-4" /><Skeleton className="h-4 w-5/6" /></div>}
          {page && (
            <>
              {sel.type === "file" && (
                <div className="mb-5"><Button variant="secondary" size="sm" onClick={() => setSource(true)}>View source</Button></div>
              )}
              <Markdown onNavigate={navigate}>{page.markdown}</Markdown>
            </>
          )}
        </article>
      </div>

      <Dialog open={source} title="Source" onClose={() => setSource(false)} wide>
        <div className="h-[65vh]">
          {source && sel.type === "file" && (
            <Suspense fallback={<Skeleton className="h-full w-full" />}>
              <CodeViewer repoId={repoId} target={{ path: sel.path, start: 1, end: 1 }} onClose={() => setSource(false)} />
            </Suspense>
          )}
        </div>
      </Dialog>
    </div>
  );
}
