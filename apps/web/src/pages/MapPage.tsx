import {
  Background, BackgroundVariant, ReactFlow, ReactFlowProvider, useReactFlow, useViewport, type Edge, type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getFileGraph, getFolderGraph, type FileGraphDetail, type FolderGraphNode, type GraphResponse } from "../api";
import { Button, Card, ErrorState, Legend, MonoLabel, NorthMark, ScaleBar, Skeleton } from "../components/ui";
import { atlasLayout, radiusFor, shortestLoop } from "../features/atlasLayout";
import {
  AtlasEdge, AtlasNode, MapCtx, MapDefs, RegionNode,
  type AtlasEdgeData, type AtlasNodeData, type MapCtxValue, type RegionData,
} from "../features/AtlasParts";
import { basename, useRepo } from "../hooks/RepoData";

const nodeTypes = { atlas: AtlasNode, region: RegionNode };
const edgeTypes = { atlas: AtlasEdge };
const FOLDER_THRESHOLD = 150; // above this many files the Folders view is the default
const MAX_ANIMATED = 60;      // flowing dashes only on cycle / selected edges, capped

type View = "files" | "folders";

/** A, B, C… across the top and 1, 2, 3… down the left, computed from the pan/zoom so they stay on the map's own grid. */
function MapGridLetters({ cell = 320 }: { cell?: number }) {
  const { x, y, zoom } = useViewport();
  const step = cell * zoom;
  if (step < 40) return null;
  const el = document.querySelector(".react-flow") as HTMLElement | null;
  const W = el?.clientWidth ?? 1200, H = el?.clientHeight ?? 700;
  const cols = Array.from({ length: Math.ceil(W / step) + 2 }, (_, i) => Math.floor(-x / step) + i);
  const rows = Array.from({ length: Math.ceil(H / step) + 2 }, (_, i) => Math.floor(-y / step) + i);
  const letter = (i: number) => String.fromCharCode(65 + ((i % 26) + 26) % 26);
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 z-10 select-none overflow-hidden font-mono text-micro text-dim">
      {cols.map((c) => {
        const px = x + (c + 0.5) * step;
        return c >= 0 && px > 24 && px < W - 8 ? <span key={`c${c}`} className="absolute top-1.5" style={{ left: px }}>{letter(c)}</span> : null;
      })}
      {rows.map((r) => {
        const py = y + (r + 0.5) * step;
        return r >= 0 && py > 24 && py < H - 8 ? <span key={`r${r}`} className="absolute left-2" style={{ top: py }}>{r + 1}</span> : null;
      })}
    </div>
  );
}

function Controls() {
  const rf = useReactFlow();
  const b = "flex size-9 items-center justify-center rounded-ui border border-border bg-surface text-text-2 hover:border-border-strong hover:text-text";
  return (
    <div className="absolute right-3 top-9 z-20 flex flex-col gap-1.5">
      <button className={b} aria-label="Zoom in" onClick={() => rf.zoomIn({ duration: 250 })}>+</button>
      <button className={b} aria-label="Zoom out" onClick={() => rf.zoomOut({ duration: 250 })}>−</button>
      <button className={b} aria-label="Fit map to screen" onClick={() => rf.fitView({ duration: 400, padding: 0.12 })}>
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M1 5V1h4M9 1h4v4M13 9v4H9M5 13H1V9" /></svg>
      </button>
    </div>
  );
}

/** Below this zoom the map is a overview: labels, arrowheads and pulse rings are not legible anyway and are the costly part. */
const LOD_ZOOM = 0.45;

function Canvas({ nodes, edges, onPane, flyTo }: { nodes: Node[]; edges: Edge[]; onPane: () => void; flyTo: string | null }) {
  const rf = useReactFlow();
  // level of detail via a data attribute on the canvas (CSS does the hiding), so panning never re-renders the nodes
  const setLod = (zoom: number) => {
    const el = document.querySelector("[aria-label='Map canvas']") as HTMLElement | null;
    if (el) el.dataset.lod = nodes.length > 250 && zoom < LOD_ZOOM ? "low" : "high";   // small maps always keep full detail
  };
  useEffect(() => {
    if (flyTo) rf.fitView({ nodes: [{ id: flyTo }], duration: 500, maxZoom: 1.1, padding: 0.8 });
  }, [flyTo, rf]);
  return (
    <>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.08}
        maxZoom={2}
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        onlyRenderVisibleElements={nodes.length > 250}
        proOptions={{ hideAttribution: true }}
        onPaneClick={onPane}
        onInit={(inst) => setLod(inst.getZoom())}
        onMove={(_, vp) => setLod(vp.zoom)}
        aria-label="Dependency map"
      >
        <Background variant={BackgroundVariant.Lines} gap={40} color="var(--color-line)" lineWidth={1} />
        <MapGridLetters />
        <Controls />
      </ReactFlow>
    </>
  );
}

export default function MapPage() {
  const { repoId, graph, hotspots, files } = useRepo();
  const [params, setParams] = useSearchParams();
  const [folders, setFolders] = useState<GraphResponse<FolderGraphNode> | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [selected, setSelected] = useState<string | null>(params.get("file"));
  const [hover, setHover] = useState<string | null>(null);
  const [detail, setDetail] = useState<FileGraphDetail | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 1023px)").matches);
  const [flyTo, setFlyTo] = useState<string | null>(params.get("file"));

  // a jump (Ctrl+K) while the map is already open changes ?file= without remounting: follow it
  const fileParam = params.get("file");
  useEffect(() => {
    if (!fileParam) return;
    setView("files");
    setSelected(fileParam);
    setFlyTo(fileParam);
  }, [fileParam]);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1023px)");
    const f = () => setNarrow(mq.matches);
    mq.addEventListener("change", f);
    return () => mq.removeEventListener("change", f);
  }, []);
  useEffect(() => {
    getFolderGraph(repoId).then(setFolders).catch(() => setFolders(null));
  }, [repoId]);

  // default view: Folders above the size threshold; a ?file= link forces Files
  const effectiveView: View = view ?? (params.get("file") ? "files" : graph && graph.total_nodes > FOLDER_THRESHOLD ? "folders" : "files");

  const file = useMemo(() => {
    const byPath = new Map((hotspots?.items ?? []).map((h) => [h.path, h]));
    return { byPath };
  }, [hotspots]);

  // ---- derived graph data -------------------------------------------------------------------------------------
  const built = useMemo(() => {
    if (effectiveView === "folders") {
      if (!folders) return null;
      const lnodes = folders.nodes.map((n) => ({ id: n.id, cluster: n.id, r: Math.max(8, Math.min(26, 6 + Math.sqrt(n.files) * 3.2)), label: n.id, sub: `${n.files} ${n.files === 1 ? "file" : "files"}` }));
      const lay = atlasLayout(lnodes, folders.edges);
      const rank = [...folders.nodes].sort((a, b) => Number(b.pagerank ?? 0) - Number(a.pagerank ?? 0)).slice(0, 3).map((n) => n.id);
      const center = { x: lay.size.w / 2, y: lay.size.h / 2 };
      const order = [...lnodes].sort((a, b) => Math.hypot(lay.pos[a.id]!.x - center.x, lay.pos[a.id]!.y - center.y) - Math.hypot(lay.pos[b.id]!.x - center.x, lay.pos[b.id]!.y - center.y));
      const delay = new Map(order.map((n, i) => [n.id, Math.min(0.6, (i / Math.max(1, order.length)) * 0.6)]));
      const nodes: Node[] = folders.nodes.map((n, i) => ({
        id: n.id, type: "atlas", position: lay.pos[n.id]!, draggable: false, zIndex: 1,
        data: { label: n.id, sub: `${n.files} files`, kind: n.files_in_cycles > 0 ? "hotspot" : rank.includes(n.id) ? "central" : "plain", r: lnodes[i]!.r, pulse: n.files_in_cycles > 0 || rank[0] === n.id, delay: delay.get(n.id) ?? 0, folder: true } satisfies AtlasNodeData,
      }));
      const edges: Edge[] = folders.edges.map((e, i) => ({
        id: `f${i}`, source: e.source, target: e.target, type: "atlas", markerEnd: "url(#ah-plain)",
        data: { kind: "plain", animated: false, a: e.source, b: e.target, delay: 0.5, count: e.count } satisfies AtlasEdgeData,
      }));
      return { nodes, edges, regions: [] as { cluster: string; label: string }[], cycleNodes: new Set<string>(), total: folders.total_nodes, shown: folders.nodes.length, truncated: false, lay };
    }
    if (!graph) return null;
    const topScore = new Map<string, number>();
    for (const n of graph.nodes) topScore.set(n.id, file.byPath.get(n.path)?.hotspot_score ?? 0);
    const pr = [...graph.nodes].sort((a, b) => Number(b.pagerank) - Number(a.pagerank));
    const central = new Set(pr.slice(0, Math.max(3, Math.ceil(graph.nodes.length * 0.05))).map((n) => n.id));
    const hot = new Set([...graph.nodes].filter((n) => (topScore.get(n.id) ?? 0) > 70).map((n) => n.id));
    const visible = graph.nodes.filter((n) => !hidden.has(n.module));
    const ids = new Set(visible.map((n) => n.id));
    const vEdges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    const lnodes = visible.map((n) => ({ id: n.id, cluster: n.module || "(root)", r: radiusFor(n.fan_in), label: basename(n.path) }));
    const lay = atlasLayout(lnodes, vEdges);
    const center = { x: lay.size.w / 2, y: lay.size.h / 2 };
    const order = [...lnodes].sort((a, b) => Math.hypot(lay.pos[a.id]!.x - center.x, lay.pos[a.id]!.y - center.y) - Math.hypot(lay.pos[b.id]!.x - center.x, lay.pos[b.id]!.y - center.y));
    const delay = new Map(order.map((n, i) => [n.id, Math.min(0.6, (i / Math.max(1, order.length)) * 0.6)]));
    const pulsing = new Set([...pr.slice(0, 3).map((n) => n.id), ...[...hot].slice(0, 3)]);
    const regionNodes: Node[] = lay.regions.map((r) => ({
      id: `region:${r.cluster}`, type: "region", position: { x: r.x, y: r.y }, selectable: false, draggable: false, focusable: false, zIndex: 0,
      data: { label: r.cluster === "(root)" ? "ROOT" : r.cluster.replace(/\//g, " / "), w: r.w, h: r.h } satisfies RegionData,
    }));
    const fileNodes: Node[] = visible.map((n, i) => ({
      id: n.id, type: "atlas", position: lay.pos[n.id]!, draggable: false, zIndex: 1,
      data: { label: basename(n.path), sub: undefined, kind: hot.has(n.id) ? "hotspot" : central.has(n.id) ? "central" : "plain", r: lnodes[i]!.r, pulse: pulsing.has(n.id), delay: delay.get(n.id) ?? 0 } satisfies AtlasNodeData,
    }));
    const cycleOf = new Map(graph.nodes.map((n) => [n.id, n.cycle_idx]));
    const edges: Edge[] = vEdges.map((e, i) => {
      const cyc = cycleOf.get(e.source) !== null && cycleOf.get(e.source) === cycleOf.get(e.target);
      return { id: `e${i}`, source: e.source, target: e.target, type: "atlas", markerEnd: cyc ? "url(#ah-cycle)" : "url(#ah-plain)",
        data: { kind: cyc ? "cycle" : "plain", animated: false, a: e.source, b: e.target, delay: 0.5 } satisfies AtlasEdgeData };
    });
    return {
      nodes: [...regionNodes, ...fileNodes], edges, regions: lay.regions.map((r) => ({ cluster: r.cluster, label: r.cluster })),
      cycleNodes: new Set(graph.nodes.filter((n) => n.cycle_idx !== null).map((n) => n.id)),
      total: graph.total_nodes, shown: visible.length, truncated: graph.truncated, lay,
    };
  }, [effectiveView, graph, folders, hidden, file]);

  // ---- selection, hover and the edges that depend on them ----------------------------------------------------------
  const neighbours = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const e of built?.edges ?? []) {
      const d = e.data as AtlasEdgeData;
      (m.get(d.a) ?? m.set(d.a, new Set()).get(d.a)!).add(d.b);
      (m.get(d.b) ?? m.set(d.b, new Set()).get(d.b)!).add(d.a);
    }
    return m;
  }, [built]);

  const activeId = hover ?? selected;
  const isNear = useCallback((id: string) => !activeId || id === activeId || (neighbours.get(activeId)?.has(id) ?? false), [activeId, neighbours]);

  const edges = useMemo(() => {
    if (!built) return [];
    let budget = MAX_ANIMATED;
    const out = built.edges.map((e) => {
      const d = e.data as AtlasEdgeData;
      const sel = selected !== null && (d.a === selected || d.b === selected);
      const kind = sel ? "selected" : d.kind === "selected" ? "plain" : d.kind;
      const animated = kind !== "plain" && budget-- > 0;
      return { ...e, markerEnd: kind === "selected" ? "url(#ah-selected)" : kind === "cycle" ? "url(#ah-cycle)" : "url(#ah-plain)", data: { ...d, kind, animated } };
    });
    return out;
  }, [built, selected]);

  const select = useCallback((id: string) => {
    if (effectiveView === "folders") return setSelected((s) => (s === id ? null : id));
    setSelected((s) => (s === id ? null : id));
  }, [effectiveView]);
  const ctx: MapCtxValue = useMemo(() => ({ hoverId: hover, selectedId: selected, isNear, select }), [hover, selected, isNear, select]);

  useEffect(() => {
    setDetail(null);
    if (effectiveView !== "files" || !selected) return;
    let stop = false;
    getFileGraph(selected).then((d) => !stop && setDetail(d)).catch(() => {});
    return () => { stop = true; };
  }, [selected, effectiveView]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && (setSelected(null), setParams({}, { replace: true }));
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setParams]);

  // ---- cycle panel: an actual loop through the biggest cycle group --------------------------------------------------
  const cycle = useMemo(() => {
    if (!graph || graph.cycles.length === 0) return null;
    const biggest = [...graph.cycles].sort((a, b) => b.size - a.size)[0]!;
    const loop = shortestLoop(biggest.file_ids.map(String), graph.edges);
    const path = (id: string) => graph.nodes.find((n) => n.id === id)?.path ?? id;
    return { groups: graph.cycles.length, size: biggest.size, loop: loop?.map((id) => ({ id, path: path(id) })) ?? null };
  }, [graph]);

  const nodeFor = (id: string) => graph?.nodes.find((n) => n.id === id);
  const sel = selected ? nodeFor(selected) : undefined;
  const selFolder = selected && effectiveView === "folders" ? folders?.nodes.find((n) => n.id === selected) : undefined;
  const hs = sel ? file.byPath.get(sel.path) : undefined;

  // every folder stays in the checklist even when hidden, so it can be switched back on
  const allRegions = useMemo(() => [...new Set((graph?.nodes ?? []).map((n) => n.module || "(root)"))].sort().map((cluster) => ({ cluster })), [graph]);
  const legendBlock = <Legend />;
  const regionsBlock = (
    <div>
      <MonoLabel className="mb-3">REGIONS</MonoLabel>
      {effectiveView === "folders" ? (
        <p className="text-small text-muted">Each circle is a folder. Switch to Files to see regions.</p>
      ) : (
        <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto pr-1">
          {allRegions.map((r) => (
            <li key={r.cluster}>
              <label className="flex min-h-8 cursor-pointer items-center gap-2 text-small text-text-3">
                <input
                  type="checkbox"
                  checked={!hidden.has(r.cluster)}
                  onChange={() => setHidden((h) => { const n = new Set(h); n.has(r.cluster) ? n.delete(r.cluster) : n.add(r.cluster); return n; })}
                  className="size-4 accent-cyan"
                />
                <span className="truncate font-mono">{r.cluster === "(root)" ? "root" : r.cluster}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  if (!graph && !folders) return <div className="grid gap-4 lg:grid-cols-[220px_1fr_280px]"><Skeleton className="h-96" /><Skeleton className="h-[70vh]" /><Skeleton className="h-96" /></div>;
  if (!built) return <ErrorState message="The dependency graph could not be loaded." action={<Button variant="secondary" onClick={() => location.reload()}>Try again</Button>} />;
  void files;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <MonoLabel>PLATE 02 ——— DEPENDENCY MAP</MonoLabel>
          <p className="mt-1 text-small text-muted">
            {built.shown} of {built.total} {effectiveView === "folders" ? "folders" : "files"}
            {built.truncated && effectiveView === "files" ? " (cycle members and most central files first; use Folders for everything)" : ""}
          </p>
        </div>
        <div className="flex gap-2" role="group" aria-label="View">
          <Button variant={effectiveView === "files" ? "primary" : "secondary"} onClick={() => setView("files")}>Files</Button>
          <Button variant={effectiveView === "folders" ? "primary" : "secondary"} onClick={() => setView("folders")}>Folders</Button>
        </div>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[220px_minmax(0,1fr)_290px]">
        <aside aria-label="Legend and regions" className="order-2 flex flex-col gap-5 rounded-card border border-border bg-surface p-4 lg:order-1">
          {narrow ? <details><summary className="mono-label cursor-pointer">Legend and regions</summary><div className="mt-4 flex flex-col gap-5">{legendBlock}{regionsBlock}</div></details> : <>{legendBlock}{regionsBlock}</>}
        </aside>

        <div className="relative order-1 h-[72vh] min-h-[420px] overflow-hidden rounded-panel border border-border bg-bg lg:order-2" aria-label="Map canvas">
          <MapDefs />
          <MapCtx.Provider value={ctx}>
            <div onPointerOver={(e) => { const el = (e.target as HTMLElement).closest("[data-id]") as HTMLElement | null; const id = el?.dataset.id ?? null; setHover(id && !id.startsWith("region:") ? id : null); }} onPointerLeave={() => setHover(null)} className="h-full w-full">
              <ReactFlowProvider key={`${effectiveView}-${hidden.size}`}>
                <Canvas nodes={built.nodes} edges={edges} onPane={() => setSelected(null)} flyTo={flyTo} />
                <div className="pointer-events-none absolute bottom-3 left-3 z-20"><ScaleBar /></div>
                <div className="pointer-events-none absolute bottom-3 right-3 z-20"><NorthMark /></div>
              </ReactFlowProvider>
            </div>
          </MapCtx.Provider>
        </div>

        <aside aria-label="Cycle and selected file" className="order-3 flex flex-col gap-4">
          {cycle && (
            <Card variant="risk">
              <MonoLabel className="text-amber-soft">IMPORT CYCLE</MonoLabel>
              <p className="mt-2 text-small text-amber-soft">
                {cycle.groups === 1 ? "1 group" : `${cycle.groups} groups`} of files import each other; the largest has {cycle.size} files.
              </p>
              {cycle.loop && (
                <ol className="mt-3 flex flex-col gap-1 font-mono text-[11.5px] text-text-2" aria-label="One loop through the cycle">
                  {cycle.loop.map((n, i) => (
                    <li key={i} className="flex items-center gap-2">
                      <span aria-hidden className="text-amber">{i === 0 ? "●" : "↳"}</span>
                      <button className="truncate text-left hover:text-text" title={n.path} onClick={() => { setSelected(n.id); setFlyTo(n.id); setView("files"); }}>{n.path}</button>
                    </li>
                  ))}
                </ol>
              )}
              <p className="mt-3 text-[12px] text-text-3">A change in any of these can ripple through all of them, and none can be tested or reused alone.</p>
            </Card>
          )}

          <Card>
            <MonoLabel>SELECTED</MonoLabel>
            {!sel && !selFolder && <p className="mt-2 text-small text-muted">Click a circle (or press Enter on it) to see what it depends on. Esc clears.</p>}
            {selFolder && (
              <div className="mt-2 flex flex-col gap-2 text-small">
                <p className="break-all font-mono text-text-2">{selFolder.id}</p>
                <p className="text-text-3">{selFolder.files} {selFolder.files === 1 ? "file" : "files"} · {selFolder.files_in_cycles} in cycles · {selFolder.internal_edges} internal imports</p>
                <Button variant="secondary" onClick={() => { setView("files"); setSelected(null); }}>Show its files</Button>
              </div>
            )}
            {sel && (
              <div className="mt-2 flex flex-col gap-3 text-small">
                <p className="break-all font-mono text-text-2">{sel.path}</p>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
                  <dt className="text-muted">Depends on</dt><dd className="text-right font-mono text-text-2">{detail ? detail.imports.length : sel.fan_out}</dd>
                  <dt className="text-muted">Used by</dt><dd className="text-right font-mono text-cyan-soft">{detail ? detail.imported_by.length : sel.fan_in}</dd>
                  <dt className="text-muted">Complexity</dt><dd className="text-right font-mono text-text-2">{hs?.max_complexity ?? "—"}</dd>
                  <dt className="text-muted">Hotspot score</dt><dd className={`text-right font-mono ${(hs?.hotspot_score ?? 0) > 70 ? "text-amber-soft" : "text-text-2"}`}>{hs?.hotspot_score === null || hs?.hotspot_score === undefined ? "—" : Math.round(hs.hotspot_score)}</dd>
                </dl>
                {detail && detail.imported_by.length > 0 && (
                  <div>
                    <div className="mono-label mb-1">USED BY</div>
                    <ul className="flex flex-col gap-0.5">
                      {detail.imported_by.slice(0, 6).map((n) => (
                        <li key={n.id}><button className="truncate text-left font-mono text-[11.5px] text-text-3 hover:text-text" onClick={() => { setSelected(n.id); setFlyTo(n.id); }}>{n.path}</button></li>
                      ))}
                    </ul>
                  </div>
                )}
                <Link className="inline-flex min-h-11 items-center justify-center rounded-ui border border-cyan-bg bg-cyan-tint px-4 font-semibold text-cyan-soft hover:border-cyan" to={`/repo/${repoId}/ask?q=${encodeURIComponent(`Explain ${sel.path}: what does it do and what depends on it?`)}`}>
                  Explain this file →
                </Link>
              </div>
            )}
          </Card>
        </aside>
      </div>
    </div>
  );
}
