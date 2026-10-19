import { Handle, Position, type NodeProps } from "@xyflow/react";
import { NODE_HEIGHT, NODE_WIDTH } from "./graphLayout";

export interface GraphNodeData extends Record<string, unknown> {
  label: string;
  sub: string;
  inCycle: boolean;
  selected: boolean;
}

/** One node renderer for both files and folders; only token classes. */
export function GraphNode({ data }: NodeProps) {
  const d = data as GraphNodeData;
  const border = d.inCycle ? "border-danger" : d.selected ? "border-primary" : "border-border";
  return (
    <div
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
      className={`flex flex-col justify-center overflow-hidden rounded-ui border bg-surface px-gap text-small ${border} ${
        d.selected ? "bg-subtle" : ""
      }`}
      title={d.label}
    >
      <Handle type="target" position={Position.Left} />
      <span className="truncate font-mono">{d.label}</span>
      <span className="truncate text-muted">{d.sub}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
