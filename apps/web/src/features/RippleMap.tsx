import { useEffect, useMemo, useRef, useState } from "react";
import type { BlastResult, FileGraphNode, GraphResponse } from "../api";
import { useMotionOff } from "../hooks/useMotionOff";
import { atlasLayout, radiusFor } from "./atlasLayout";

/**
 * The ripple: impact travelling outward from the change, hop by hop. Changed files (distance 0) light up first in the
 * danger colour with expanding rings; impacted files follow in order of distance; colour intensity = impact score.
 * The animation has one job, showing how impact travels, so with reduced motion everything is shown at once.
 * Clicking a result elsewhere highlights its explanation path here.
 */
const HOP_DELAY = 0.7;   // seconds per hop

export function RippleMap({ graph, result, highlight, replayKey, onPick }: {
  graph: GraphResponse<FileGraphNode>;
  result: BlastResult;
  highlight: string[];               // file paths on the selected explanation path
  replayKey: number;
  onPick?: (path: string) => void;
}) {
  const off = useMotionOff();
  const svg = useRef<SVGSVGElement | null>(null);
  const [view, setView] = useState<{ x: number; y: number; k: number } | null>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);

  const impactByPath = useMemo(() => {
    const m = new Map<string, { score: number; distance: number }>();
    for (const f of result.impact?.files ?? []) m.set(f.path, { score: f.score, distance: f.distance });
    for (const f of result.change.files) if (!m.has(f.path) && f.status !== "deleted") m.set(f.path, { score: 1, distance: 0 });
    return m;
  }, [result]);

  const layout = useMemo(() => {
    const nodes = graph.nodes.map((n) => ({ id: n.id, cluster: n.module || "(root)", r: radiusFor(n.fan_in) * 0.8,
                                            label: n.path.split("/").pop() ?? n.path }));
    return atlasLayout(nodes, graph.edges);
  }, [graph]);

  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);
  const hl = useMemo(() => new Set(highlight), [highlight]);
  const maxDist = Math.max(1, ...[...impactByPath.values()].map((v) => v.distance));
  const pad = 40;
  const W = layout.size.w + pad * 2, H = layout.size.h + pad * 2;
  const vb = view ?? { x: -pad, y: -pad, k: 1 };

  useEffect(() => setView(null), [graph]);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const k = Math.min(4, Math.max(0.5, vb.k * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
    setView({ ...vb, k });
  };

  return (
    <div className="bg-graticule relative h-[460px] overflow-hidden border-[1.5px] border-ink bg-paper" aria-label="Ripple map">
      <svg
        ref={svg}
        role="img"
        aria-label={`Ripple map: ${impactByPath.size} affected files, spreading up to ${maxDist} hops from the change`}
        viewBox={`${vb.x} ${vb.y} ${W / vb.k} ${H / vb.k}`}
        className="h-full w-full cursor-grab touch-none select-none active:cursor-grabbing"
        onWheel={onWheel}
        onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY }; (e.target as Element).setPointerCapture?.(e.pointerId); }}
        onPointerMove={(e) => {
          if (!drag.current || !svg.current) return;
          const rect = svg.current.getBoundingClientRect();
          const sx = (W / vb.k) / rect.width, sy = (H / vb.k) / rect.height;
          setView({ ...vb, x: vb.x - (e.clientX - drag.current.x) * sx, y: vb.y - (e.clientY - drag.current.y) * sy });
          drag.current = { x: e.clientX, y: e.clientY };
        }}
        onPointerUp={() => (drag.current = null)}
      >
        {layout.regions.map((r) => (
          <g key={r.cluster}>
            <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={18} fill="none"
                  stroke="var(--pencil)" strokeOpacity={0.6} strokeDasharray="3 4" />
            <text x={r.x + 10} y={r.y + 18} fontSize={10.5} fontFamily="var(--font-mono)" letterSpacing="1.5" fill="var(--pencil)">{r.cluster.toUpperCase()}</text>
          </g>
        ))}
        {graph.edges.map((e, i) => {
          const a = layout.pos[e.source], b = layout.pos[e.target];
          if (!a || !b) return null;
          const pa = byId.get(e.source)?.path ?? "", pb = byId.get(e.target)?.path ?? "";
          const on = hl.has(pa) && hl.has(pb);
          return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--ink)"
                       strokeOpacity={on ? 1 : 0.22} strokeWidth={on ? 2.5 : 0.9} />;
        })}
        {graph.nodes.map((n) => {
          const p = layout.pos[n.id];
          if (!p) return null;
          const hit = impactByPath.get(n.path);
          const r = radiusFor(n.fan_in) * 0.8;
          const delay = hit ? hit.distance * HOP_DELAY : 0;
          const changed = hit?.distance === 0;
          // changed = solid red ink; impacted = red ring, filled more strongly the stronger the impact; untouched = paper
          const fill = !hit ? "var(--paper)" : "var(--signal)";
          const opacity = !hit ? 1 : changed ? 1 : 0.15 + 0.6 * Math.min(1, hit.score / 0.6);
          return (
            <g key={`${n.id}-${replayKey}`} onClick={() => hit && onPick?.(n.path)} className={hit ? "cursor-pointer" : ""}>
              {changed && !off && [0, 1].map((k) => (
                <circle key={k} cx={p.x} cy={p.y} r={r} fill="none" stroke="var(--signal)" strokeWidth={1.5}
                        className="anim-pulse-ring" style={{ animationDelay: `${k * 1.2}s` }} />
              ))}
              {hl.has(n.path) && <circle cx={p.x} cy={p.y} r={r + 6} fill="none" stroke="var(--ink)" strokeWidth={2.2} />}
              <circle cx={p.x} cy={p.y} r={r} fill={fill} fillOpacity={opacity}
                      stroke={hit ? "var(--signal)" : "var(--ink)"} strokeOpacity={hit ? 1 : 0.5} strokeWidth={hit && !changed ? 1.8 : 1.1}
                      className={hit && !off ? "ripple-in" : ""} style={hit && !off ? { animationDelay: `${delay}s` } : undefined}>
                <title>{n.path}{hit ? ` · ${changed ? "changed" : `impact ${hit.score.toFixed(2)}, ${hit.distance} hop(s)`}` : ""}</title>
              </circle>
              {(hit || hl.has(n.path)) && (
                <text x={p.x + r + 4} y={p.y + 4} fontSize={11} fontFamily="var(--font-mono)" fill={changed ? "var(--signal-ink)" : "var(--ink)"} fontWeight={changed ? 600 : 400}
                      className={`map-halo ${hit && !off ? "ripple-in" : ""}`} style={hit && !off ? { animationDelay: `${delay}s` } : undefined}>
                  {n.path.split("/").pop()}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-[1.5px] border-ink bg-paper px-3 py-2 font-mono text-[11px] text-ink-2">
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-signal" /> changed</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full border-[1.5px] border-signal bg-signal/40" /> reached (fuller = stronger)</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full border border-ink/50 bg-paper" /> untouched</span>
      </div>
      {graph.truncated && (
        <p className="absolute right-3 top-3 border border-rule-strong bg-paper px-2 py-1 font-mono text-[11px] text-pencil">showing the {graph.nodes.length} most central files</p>
      )}
    </div>
  );
}
