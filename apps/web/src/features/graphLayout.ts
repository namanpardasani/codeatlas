import dagre from "@dagrejs/dagre";

export const NODE_WIDTH = 220;
export const NODE_HEIGHT = 44;

/** Left-to-right layered layout: importers on the left, the files they import to the right. */
export function layout(ids: string[], edges: { source: string; target: string }[]): Record<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 16, ranksep: 70 });
  g.setDefaultEdgeLabel(() => ({}));
  ids.forEach((id) => g.setNode(id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  const out: Record<string, { x: number; y: number }> = {};
  ids.forEach((id) => {
    const n = g.node(id);
    out[id] = { x: n.x - NODE_WIDTH / 2, y: n.y - NODE_HEIGHT / 2 };
  });
  return out;
}
