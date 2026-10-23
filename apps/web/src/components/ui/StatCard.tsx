import type { ReactNode } from "react";

/**
 * A figure: a big serif number with a mono caption under it, no box. `risk` writes the number in red ink and
 * underlines it (colour is never the only signal).
 */
export function Figure({ label, value, hint, risk = false, className = "" }: { label: string; value: ReactNode; hint?: string; risk?: boolean; className?: string }) {
  return (
    <div className={`flex flex-col ${className}`}>
      <span className={`font-display text-[44px] font-semibold leading-none tracking-[-0.04em] tabular-nums [font-variation-settings:'SOFT'_30] ${risk ? "text-signal-ink underline decoration-signal decoration-2 underline-offset-[6px]" : "text-ink"}`}>{value}</span>
      <span className="mono-label mt-2">{label}</span>
      {hint && <span className="mt-0.5 text-[12.5px] leading-snug text-pencil">{hint}</span>}
    </div>
  );
}

/** Older name: kept so existing imports work. */
export function StatCard(props: { label: string; value: ReactNode; hint?: string; risk?: boolean; icon?: string }) {
  return <Figure label={props.label} value={props.value} hint={props.hint} risk={props.risk} />;
}
