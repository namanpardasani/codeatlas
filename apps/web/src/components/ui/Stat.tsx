import type { ReactNode } from "react";

/** A labelled value for dense metric lists: mono caption over the value. */
export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col border-l border-rule pl-3" title={hint}>
      <span className="mono-label">{label}</span>
      <span className="mt-0.5 font-medium text-ink">{value}</span>
    </div>
  );
}
