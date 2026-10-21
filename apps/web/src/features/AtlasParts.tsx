import { BaseEdge, getBezierPath, Handle, Position, type EdgeProps, type NodeProps } from "@xyflow/react";
import { createContext, memo, useContext } from "react";

export interface MapCtxValue {
  hoverId: string | null;
  selectedId: string | null;
  /** is this node connected to the hovered (or else selected) node? */
  isNear: (id: string) => boolean;
  select: (id: string) => void;
}
export const MapCtx = createContext<MapCtxValue>({ hoverId: null, selectedId: null, isNear: () => true, select: () => {} });

export interface AtlasNodeData extends Record<string, unknown> {
  label: string;
  sub?: string;
  kind: "central" | "hotspot" | "plain";
  r: number;
  pulse: boolean;
  delay: number;
  folder?: boolean;
}

const FILL = { central: "bg-cyan border-cyan", hotspot: "bg-amber border-amber", plain: "bg-bg border-muted" } as const;

/** Custom node: a circle sized by dependents plus a mono label. Memoised; hover dimming comes from context, not from new props. */
export const AtlasNode = memo(function AtlasNode({ id, data }: NodeProps) {
  const d = data as AtlasNodeData;
  const { hoverId, selectedId, isNear, select } = useContext(MapCtx);
  const active = hoverId ?? selectedId;
  const dim = active !== null && !isNear(id);
  const selected = selectedId === id;
  const size = d.r * 2;
  const ring = d.kind === "hotspot" ? "border-amber" : "border-cyan";
  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={`${d.label}${d.sub ? `, ${d.sub}` : ""}${d.kind === "central" ? ", central file" : d.kind === "hotspot" ? ", hotspot" : ""}`}
      onClick={() => select(id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          select(id);
        }
      }}
      className="atlas-node flex cursor-pointer items-center gap-2 rounded-full outline-offset-4 transition-opacity duration-[250ms]"
      style={{ opacity: dim ? 0.35 : 1, animationDelay: `${d.delay}s` }}
    >
      <span className="relative shrink-0" style={{ width: size, height: size }}>
        {d.pulse && <span aria-hidden className={`anim-pulse-ring absolute inset-0 rounded-full border-[1.5px] ${ring}`} />}
        <span
          aria-hidden
          className={`absolute inset-0 rounded-full border-[1.5px] ${FILL[d.kind]} ${selected ? "ring-2 ring-cyan ring-offset-2 ring-offset-bg" : ""}`}
        />
        <Handle type="target" position={Position.Top} isConnectable={false} style={{ left: d.r, top: d.r, opacity: 0, width: 1, height: 1, minWidth: 0, minHeight: 0, border: 0 }} />
        <Handle type="source" position={Position.Bottom} isConnectable={false} style={{ left: d.r, top: d.r, right: "auto", bottom: "auto", opacity: 0, width: 1, height: 1, minWidth: 0, minHeight: 0, border: 0 }} />
      </span>
      <span className={`atlas-label whitespace-nowrap font-mono text-[11px] leading-none ${selected ? "text-text" : "text-text-3"}`}>
        {d.label}
        {d.sub && <span className="ml-1.5 text-dim">{d.sub}</span>}
      </span>
    </div>
  );
});

export interface RegionData extends Record<string, unknown> {
  label: string;
  w: number;
  h: number;
}
/** Folder region: soft rounded dashed outline behind its nodes, with a dim mono caption. Never intercepts the pointer. */
export const RegionNode = memo(function RegionNode({ data }: NodeProps) {
  const d = data as RegionData;
  return (
    <div aria-hidden className="pointer-events-none relative rounded-[26px] border-[3px] border-dashed border-border-strong bg-surface/30" style={{ width: d.w, height: d.h }}>
      <span className="absolute left-5 top-3 font-mono text-[15px] font-medium uppercase tracking-[0.14em] text-dim">{d.label}</span>
    </div>
  );
});

export interface AtlasEdgeData extends Record<string, unknown> {
  kind: "plain" | "cycle" | "selected";
  /** dash flow is only on cycle and selected edges, and at most ~60 of them */
  animated: boolean;
  a: string;
  b: string;
  delay: number;
  count?: number;
}

const STROKE = { plain: "var(--color-faint)", cycle: "var(--color-amber)", selected: "var(--color-cyan)" } as const;

/** Custom curved edge. Gray by default; cycle edges amber dashed; the selected file's edges cyan dashed, flowing along the import. */
export const AtlasEdge = memo(function AtlasEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd }: EdgeProps) {
  const d = data as AtlasEdgeData;
  const { hoverId, selectedId } = useContext(MapCtx);
  const active = hoverId ?? selectedId;
  const dim = active !== null && d.a !== active && d.b !== active;
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, curvature: 0.35 });
  const dashed = d.kind !== "plain";
  return (
    <g className="atlas-edge" data-kind={d.kind} style={{ opacity: dim ? 0.35 : 1, transition: "opacity 250ms", animationDelay: `${d.delay}s` }}>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={{ stroke: STROKE[d.kind], strokeWidth: d.kind === "plain" ? 1.1 : 1.6, strokeDasharray: dashed ? "6 6" : undefined }}
        className={dashed && d.animated ? "anim-dash" : ""}
      />
    </g>
  );
});

/** Arrow markers for the three edge kinds (colour + shape: arrowheads show direction even without colour). */
export function MapDefs() {
  const m = (id: string, color: string) => (
    <marker key={id} id={id} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 L8 4 L0 8 Z" fill={color} />
    </marker>
  );
  return (
    <svg width="0" height="0" aria-hidden className="absolute">
      <defs>{[m("ah-plain", STROKE.plain), m("ah-cycle", STROKE.cycle), m("ah-selected", STROKE.selected)]}</defs>
    </svg>
  );
}
