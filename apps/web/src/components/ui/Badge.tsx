import type { ReactNode } from "react";

/** cyan = structure/verified, amber = risk, error = errors only. Legacy tones map onto these. */
export type Tone = "neutral" | "cyan" | "amber" | "error" | "success" | "danger" | "warning" | "info";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-text-3 border-border",
  cyan: "bg-cyan-bg text-cyan-soft border-cyan-bg",
  amber: "bg-amber-bg text-amber-soft border-amber-border",
  error: "bg-surface-2 text-error border-border",
  success: "bg-cyan-bg text-cyan-soft border-cyan-bg",
  info: "bg-cyan-bg text-cyan-soft border-cyan-bg",
  warning: "bg-amber-bg text-amber-soft border-amber-border",
  danger: "bg-surface-2 text-error border-border",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-block rounded-md border px-2 py-0.5 font-mono text-micro tracking-wide ${tones[tone]}`}>{children}</span>
  );
}
