import type { ReactNode } from "react";

/** A labelled value, for inline metric summaries. */
export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col" title={hint}>
      <span className="text-small text-muted">{label}</span>
      <span className="font-semibold text-text">{value}</span>
    </div>
  );
}
