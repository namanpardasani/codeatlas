import { useEffect, useMemo, useState } from "react";
import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  getFileGraph, getFileGraphOverview, getFolderGraph,
  type FileGraphDetail, type FileGraphNode, type FolderGraphNode, type GraphResponse,
} from "../api";
import { Badge, Button, Panel, token } from "../components/ui";
import { layout } from "./graphLayout";
import { GraphNode, type GraphNodeData } from "./GraphNode";

const nodeTypes = { graph: GraphNode };
type Mode = "files" | "folders";

export function GraphPanel({ repoId }: { repoId: string }) {
  const [mode, setMode] = useState<Mode>("folders");
  const [files, setFiles] = useState<GraphResponse<FileGraphNode> | null>(null);
  const [folders, setFolders] = useState<GraphResponse<FolderGraphNode> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<FileGraphDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSelected(null);
    setDetail(null);
    setError(null);
    const load = mode === "files" ? getFileGraphOverview(repoId).then(setFiles) : getFolderGraph(repoId).then(setFolders);
    load.catch((e) => setError(e instanceof Error ? e.message : "Could not load graph"));
  }, [repoId, mode]);

  useEffect(() => {
    if (mode !== "files" || !selected) return setDetail(null);
    getFileGraph(selected).then(setDetail).catch(() => setDetail(null));
  }, [mode, selected]);

  const { nodes, edges } = useMemo(() => build(mode, files, folders, selected), [mode, files, folders, selected]);
  const data = mode === "files" ? files : folders;
  const cycleCount = files?.cycles.length ?? 0;

  return (
    <Panel
      title="Dependency graph"
      actions={
        <span className="flex gap-gap">
          <Button variant={mode === "folders" ? "primary" : "secondary"} onClick={() => setMode("folders")}>
            Folders
          </Button>
          <Button variant={mode === "files" ? "primary" : "secondary"} onClick={() => setMode("files")}>
            Files
          </Button>
        </span>
      }
    >
      {error && <p className="text-danger">{error}</p>}
      {data && (
        <p className="mb-gap text-muted">
          {data.nodes.length} of {data.total_nodes} {mode === "files" ? "files" : "folders"}
          {data.truncated && " (capped: cycle members and most central files shown first; switch to Folders for the whole repo)"}
          {mode === "files" && cycleCount > 0 && <> · <Badge tone="danger">{cycleCount} cycle group(s)</Badge></>}
        </p>
      )}
      <div className="flex gap-gutter">
        <div className="h-canvas flex-1 rounded-ui border border-border">
          <ReactFlow
            key={mode}
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            minZoom={0.1}
            nodesDraggable={false}
            nodesConnectable={false}
            onNodeClick={(_, n) => mode === "files" && setSelected(n.id)}
            onPaneClick={() => setSelected(null)}
          >
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        {mode === "files" && detail && <Details detail={detail} onSelect={setSelected} />}
      </div>
    </Panel>
  );
}

function Details({ detail, onSelect }: { detail: FileGraphDetail; onSelect: (id: string) => void }) {
  const list = (title: string, items: { id: string; path: string }[]) => (
    <div className="mb-gutter">
      <h3 className="mb-gap font-semibold">{title} ({items.length})</h3>
      {items.length === 0 ? (
        <p className="text-muted">None</p>
      ) : (
        <ul className="flex flex-col gap-gap">
          {items.map((i) => (
            <li key={i.id}>
              <button className="text-left font-mono text-small text-info" onClick={() => onSelect(i.id)}>
                {i.path}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
  return (
    <aside className="w-72 shrink-0 overflow-y-auto">
      <p className="mb-gutter break-all font-mono font-semibold">{detail.file.path}</p>
      <p className="mb-gutter text-muted">
        fan-in {detail.file.fan_in} · fan-out {detail.file.fan_out} · pagerank {Number(detail.file.pagerank).toFixed(4)}
      </p>
      {list("Imports (depends on)", detail.imports)}
      {list("Imported by (dependents)", detail.imported_by)}
      {detail.cycle.length > 0 && list("Circular dependency group", detail.cycle)}
    </aside>
  );
}

function build(
  mode: Mode,
  files: GraphResponse<FileGraphNode> | null,
  folders: GraphResponse<FolderGraphNode> | null,
  selected: string | null,
): { nodes: Node[]; edges: Edge[] } {
  const muted = token("muted");
  const danger = token("danger");
  const arrow = (color: string) => ({ type: MarkerType.ArrowClosed, color });

  if (mode === "files" && files) {
    const cycleOf = new Map(files.nodes.map((n) => [n.id, n.cycle_idx]));
    const pos = layout(files.nodes.map((n) => n.id), files.edges);
    return {
      nodes: files.nodes.map((n) => ({
        id: n.id, type: "graph", position: pos[n.id]!,
        data: {
          label: n.path.split("/").pop() ?? n.path, sub: n.module,
          inCycle: n.cycle_idx !== null, selected: n.id === selected,
        } satisfies GraphNodeData,
      })),
      edges: files.edges.map((e) => {
        const cyc = cycleOf.get(e.source) !== null && cycleOf.get(e.source) === cycleOf.get(e.target);
        const color = cyc ? danger : muted;
        return { id: `${e.source}-${e.target}`, source: e.source, target: e.target,
                 style: { stroke: color }, markerEnd: arrow(color) };
      }),
    };
  }
  if (mode === "folders" && folders) {
    const pos = layout(folders.nodes.map((n) => n.id), folders.edges);
    return {
      nodes: folders.nodes.map((n) => ({
        id: n.id, type: "graph", position: pos[n.id]!,
        data: {
          label: n.id, sub: `${n.files} files${n.files_in_cycles ? ` · ${n.files_in_cycles} in cycles` : ""}`,
          inCycle: n.files_in_cycles > 0, selected: false,
        } satisfies GraphNodeData,
      })),
      edges: folders.edges.map((e) => ({
        id: `${e.source}-${e.target}`, source: e.source, target: e.target, label: String(e.count),
        style: { stroke: muted }, markerEnd: arrow(muted),
      })),
    };
  }
  return { nodes: [], edges: [] };
}
