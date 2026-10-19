import { useEffect, useState } from "react";
import { docsExportUrl, getDocPage, getDocsStatus, getDocsTree, type DocNode, type DocPage, type DocsStatus } from "../api";
import { Badge, Panel, Markdown } from "../components/ui";

type Sel = { type: "repo" | "folder" | "file"; path: string };

function Tree({ nodes, sel, open, toggle, pick, depth = 0 }: {
  nodes: DocNode[];
  sel: Sel;
  open: Set<string>;
  toggle: (p: string) => void;
  pick: (s: Sel) => void;
  depth?: number;
}) {
  return (
    <ul className="flex flex-col">
      {nodes.map((n) => {
        const isOpen = open.has(n.path);
        const selected = sel.type === n.type && sel.path === n.path;
        return (
          <li key={`${n.type}:${n.path}`}>
            <div className={`flex items-center gap-gap rounded-ui px-gap ${selected ? "bg-subtle font-semibold" : ""}`} style={{ paddingLeft: `${0.5 + depth}rem` }}>
              {n.type === "folder" ? (
                <button className="w-4 text-muted" onClick={() => toggle(n.path)} aria-label={isOpen ? "collapse" : "expand"}>{isOpen ? "▾" : "▸"}</button>
              ) : <span className="w-4" />}
              <button className="flex-1 truncate py-0.5 text-left font-mono text-small" title={n.summary}
                      onClick={() => { pick({ type: n.type, path: n.path }); if (n.type === "folder" && !isOpen) toggle(n.path); }}>
                {n.name}{n.type === "folder" ? "/" : ""}
              </button>
              {n.source === "extractive" && <span className="text-small text-muted" title="assembled without an LLM">·</span>}
            </div>
            {n.type === "folder" && isOpen && n.children && (
              <Tree nodes={n.children} sel={sel} open={open} toggle={toggle} pick={pick} depth={depth + 1} />
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function DocsPanel({ repoId, refreshKey }: { repoId: string; refreshKey: number }) {
  const [status, setStatus] = useState<DocsStatus | null>(null);
  const [tree, setTree] = useState<DocNode[]>([]);
  const [sel, setSel] = useState<Sel>({ type: "repo", path: "" });
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [page, setPage] = useState<DocPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  // docs are generated after the analysis finishes: poll while they are still being written
  useEffect(() => {
    let stop = false;
    const load = () =>
      getDocsStatus(repoId).then((s) => {
        if (stop) return;
        setStatus(s);
        if (s.targets > 0) getDocsTree(repoId).then((t) => !stop && setTree(t.tree)).catch(() => {});
        if (s.docs_status === "running") setTimeout(load, 4000);
      }).catch(() => {});
    load();
    return () => { stop = true; };
  }, [repoId, refreshKey]);

  useEffect(() => {
    setError(null);
    setPage(null);
    if (!status || status.targets === 0) return;
    getDocPage(repoId, sel.type, sel.path).then(setPage).catch((e) => setError(e instanceof Error ? e.message : "Could not load"));
  }, [repoId, sel, status?.targets, status?.docs_generated_at]);

  const toggle = (p: string) => setOpen((o) => { const n = new Set(o); n.has(p) ? n.delete(p) : n.add(p); return n; });
  const navigate = (type: Sel["type"], path: string) => {
    setSel({ type, path });
    // make sure the node is visible in the tree
    const parts = path.split("/").slice(0, type === "file" ? -1 : undefined);
    setOpen((o) => { const n = new Set(o); parts.forEach((_, i) => n.add(parts.slice(0, i + 1).join("/"))); return n; });
  };

  return (
    <Panel
      title="Documentation"
      actions={status && status.targets > 0 ? <a className="text-info" href={docsExportUrl(repoId)} download>Download Markdown</a> : undefined}
    >
      {status?.docs_status === "running" && <p className="mb-gap text-muted"><Badge tone="info">generating</Badge> Summaries are being written; pages update as they finish.</p>}
      {status?.docs_status === "failed" && <p className="mb-gap text-danger">Documentation generation failed.</p>}
      {status && status.targets === 0 && status.docs_status !== "running" && (
        <p className="text-muted">Documentation has not been generated for this repo yet.</p>
      )}
      {status && status.targets > 0 && (
        <>
          <p className="mb-gutter text-small text-muted">
            {status.llm} written by a model and checked against the code{status.extractive > 0 ? `, ${status.extractive} assembled from names and docstrings (marked ·)` : ""}.
          </p>
          <div className="flex gap-gutter">
            <nav className="max-h-canvas w-64 shrink-0 overflow-y-auto border-r border-border pr-gap">
              <button className={`mb-gap w-full rounded-ui px-gap py-0.5 text-left font-semibold ${sel.type === "repo" ? "bg-subtle" : ""}`}
                      onClick={() => setSel({ type: "repo", path: "" })}>Overview</button>
              <Tree nodes={tree} sel={sel} open={open} toggle={toggle} pick={setSel} />
            </nav>
            <article className="min-w-0 flex-1">
              {error && <p className="text-danger">{error}</p>}
              {page && <Markdown onNavigate={navigate}>{page.markdown}</Markdown>}
            </article>
          </div>
        </>
      )}
    </Panel>
  );
}
