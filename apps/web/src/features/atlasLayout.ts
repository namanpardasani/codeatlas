import dagre from "@dagrejs/dagre";

export interface LayoutNode {
  id: string;
  cluster: string;
  /** circle radius; the layout box is the circle plus room for its label */
  r: number;
  /** label text, used to size the box (mono 11px is about 6.6 px per character) */
  label: string;
  sub?: string;
}
export interface Region {
  cluster: string;
  x: number;
  y: number;
  w: number;
  h: number;
}
export interface AtlasLayout {
  pos: Record<string, { x: number; y: number }>;
  regions: Region[];
  size: { w: number; h: number };
}

const PAD = 26;
const LABEL_H = 28; // room for the region label

const boxOf = (n: LayoutNode) => ({ width: n.r * 2 + 12 + (n.label.length + (n.sub ? n.sub.length + 1 : 0)) * 6.6, height: Math.max(26, n.r * 2 + 10) });

/**
 * Atlas layout in two passes: (1) inside every folder, a left-to-right layered layout of its files; (2) the folders
 * themselves as boxes, laid out by the imports between them. Each folder becomes a region (padded bounding box), so the
 * picture reads like a map of districts, with imports crossing the borders.
 */
export function atlasLayout(nodes: LayoutNode[], edges: { source: string; target: string }[]): AtlasLayout {
  const byCluster = new Map<string, LayoutNode[]>();
  for (const n of nodes) (byCluster.get(n.cluster) ?? byCluster.set(n.cluster, []).get(n.cluster)!).push(n);
  const clusterOf = new Map(nodes.map((n) => [n.id, n.cluster]));

  // pass 1: inside each cluster
  const inner = new Map<string, { pos: Record<string, { x: number; y: number }>; w: number; h: number }>();
  for (const [cluster, members] of byCluster) {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "TB", nodesep: 10, ranksep: 34, marginx: 0, marginy: 0 });
    g.setDefaultEdgeLabel(() => ({}));
    members.forEach((n) => g.setNode(n.id, boxOf(n)));
    edges.forEach((e) => clusterOf.get(e.source) === cluster && clusterOf.get(e.target) === cluster && g.setEdge(e.source, e.target));
    dagre.layout(g);
    const pos: Record<string, { x: number; y: number }> = {};
    let w = 0, h = 0;
    for (const n of members) {
      const d = g.node(n.id);
      const b = boxOf(n);
      pos[n.id] = { x: d.x - b.width / 2, y: d.y - b.height / 2 };
      w = Math.max(w, d.x + b.width / 2);
      h = Math.max(h, d.y + b.height / 2);
    }
    inner.set(cluster, { pos, w, h });
  }

  // pass 2: the folders as boxes, shelf-packed into rows so the sheet is roughly landscape (like an atlas plate), the
  // biggest folders first. Folders that import each other tend to be near because large ones come first and small ones fill in.
  const boxes = [...inner.entries()].map(([c, i]) => ({ c, i, w: i.w + PAD * 2, h: i.h + PAD * 2 + LABEL_H }));
  boxes.sort((a, b) => b.w * b.h - a.w * a.h);
  const area = boxes.reduce((t, b) => t + b.w * b.h, 0);
  const rowMax = Math.max(900, Math.sqrt(area * 2.2), ...boxes.map((b) => b.w));
  const GAP = 40;
  const pos: Record<string, { x: number; y: number }> = {};
  const regions: Region[] = [];
  let x = 0, y = 0, rowH = 0, maxX = 0;
  for (const bx of boxes) {
    if (x > 0 && x + bx.w > rowMax) {
      x = 0;
      y += rowH + GAP;
      rowH = 0;
    }
    regions.push({ cluster: bx.c, x, y, w: bx.w, h: bx.h });
    for (const [id, p] of Object.entries(bx.i.pos)) pos[id] = { x: x + PAD + p.x, y: y + PAD + LABEL_H + p.y };
    x += bx.w + GAP;
    rowH = Math.max(rowH, bx.h);
    maxX = Math.max(maxX, x - GAP);
  }
  const maxY = y + rowH;
  return { pos, regions, size: { w: maxX, h: maxY } };
}

/** Circle radius from the number of dependents (clamped). */
export const radiusFor = (dependents: number) => Math.max(6, Math.min(22, 6 + Math.sqrt(Math.max(0, dependents)) * 3));

/** Shortest import loop inside one cycle group, as an ordered list of ids that ends where it starts. */
export function shortestLoop(group: string[], edges: { source: string; target: string }[]): string[] | null {
  const inGroup = new Set(group);
  const adj = new Map<string, string[]>();
  for (const e of edges) if (inGroup.has(e.source) && inGroup.has(e.target)) (adj.get(e.source) ?? adj.set(e.source, []).get(e.source)!).push(e.target);
  let best: string[] | null = null;
  for (const start of group.slice(0, 40)) {
    const prev = new Map<string, string>();
    const q: string[] = [start];
    const seen = new Set<string>([start]);
    let found: string | null = null;
    while (q.length && !found) {
      const cur = q.shift()!;
      for (const nx of adj.get(cur) ?? []) {
        if (nx === start) { found = cur; break; }
        if (!seen.has(nx)) (seen.add(nx), prev.set(nx, cur), q.push(nx));
      }
    }
    if (found) {
      const path = [found];
      while (path[0] !== start) path.unshift(prev.get(path[0]!)!);
      const loop = [...path, start];
      if (!best || loop.length < best.length) best = loop;
    }
  }
  return best;
}
