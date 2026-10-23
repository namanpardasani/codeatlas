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

// central = solid ink, hotspot = red ink with an ink edge, other = paper with an ink edge (like a printed map symbol)
const FILL = { central: "bg-ink border-ink", hotspot: "bg-signal border-ink", plain: "bg-paper border-ink" } as const;

/** Custom node: a circle sized by dependents plus a mono label. Memoised; hover dimming comes from context, not from new props. */
export const AtlasNode = memo(function AtlasNode({ id, data }: NodeProps) {
  const d = data as AtlasNodeData;
  const { hoverId, selectedId, isNear, select } = useContext(MapCtx);
  const active = hoverId ?? selectedId;
  const dim = active !== null && !isNear(id);
  const selected = selectedId === id;
  const size = d.r * 2;
  const ring = d.kind === "hotspot" ? "border-signal" : "border-ink";
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
          className={`absolute inset-0 rounded-full border-[1.5px] ${FILL[d.kind]} ${selected ? "ring-2 ring-signal ring-offset-2 ring-offset-paper" : ""}`}
        />
        <Handle type="target" position={Position.Top} isConnectable={false} style={{ left: d.r, top: d.r, opacity: 0, width: 1, height: 1, minWidth: 0, minHeight: 0, border: 0 }} />
        <Handle type="source" position={Position.Bottom} isConnectable={false} style={{ left: d.r, top: d.r, right: "auto", bottom: "auto", opacity: 0, width: 1, height: 1, minWidth: 0, minHeight: 0, border: 0 }} />
      </span>
      <span className={`atlas-label map-halo whitespace-nowrap font-mono text-[11px] leading-none ${selected ? "font-semibold text-signal-ink" : "text-ink"}`}>
        {d.label}
        {d.sub && <span className="ml-1.5 text-pencil">{d.sub}</span>}
      </span>
    </div>
  );
});

export interface RegionData extends Record<string, unknown> {
  label: string;
  w: number;
  h: number;
}
/** Folder region: a dashed survey boundary around its files, lettered in mono caps. Test/docs folders get a faint wash. Never intercepts the pointer. */
export const RegionNode = memo(function RegionNode({ data }: NodeProps) {
  const d = data as RegionData;
  const aux = /(^|\/)(tests?|__tests__|specs?|docs?|examples?)(\/|$)/i.test(d.label.replace(/ \/ /g, "/"));
  return (
    <div aria-hidden className="pointer-events-none relative" style={{ width: d.w, height: d.h }}>
      {/* border and corner counter-scale with zoom (like the label) so the region outline stays visible on a zoomed-out map */}
      <div className={`absolute -inset-3 border-dashed ${aux ? "border-rule-strong bg-paper-3/40" : "border-pencil/70"}`} style={{ borderWidth: "calc(1.2px * var(--label-scale, 1))", borderRadius: "calc(18px * var(--label-scale, 1))" }} />
      <span className={`absolute -top-3 left-1 origin-top-left bg-paper px-1.5 font-mono text-[11px] font-medium uppercase tracking-[0.14em] ${aux ? "text-pencil" : "text-ink-2"}`} style={{ transform: "scale(var(--label-scale, 1))" }}>{d.label}</span>
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

// imports are thin ink lines; cycles are red dashed; the selected file's imports are heavy ink, flowing along the import
const STROKE = { plain: "color-mix(in srgb, var(--ink) 38%, transparent)", cycle: "var(--signal)", selected: "var(--ink)" } as const;

/** Custom curved edge. Thin neutral by default; cycle edges red dashed; the selected file's edges accent dashed, flowing along the import. */
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
        style={{ stroke: STROKE[d.kind], strokeWidth: d.kind === "plain" ? 1.1 : 2, strokeDasharray: dashed ? "6 5" : undefined }}
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
