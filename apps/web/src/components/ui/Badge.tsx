import type { ReactNode } from "react";

/**
 * A small tag written in mono: a thin square border, no pill, no dot. Red = risk, ochre = medium, green = checked.
 * (Several tone names exist because older code uses them; they collapse onto the four meanings.)
 */
export type Tone = "neutral" | "cyan" | "amber" | "error" | "success" | "danger" | "warning" | "info" | "accent";

const tones: Record<Tone, string> = {
  neutral: "border-rule-strong text-ink-2",
  info: "border-rule-strong text-ink-2",
  accent: "border-ink text-ink",
  cyan: "border-verified text-verified-ink",
  success: "border-verified text-verified-ink",
  amber: "border-caution text-caution-ink",
  warning: "border-caution text-caution-ink",
  danger: "border-signal text-signal-ink",
  error: "border-signal text-signal-ink",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded-sm border px-1.5 py-[3px] font-mono text-[11px] leading-none ${tones[tone]}`}>{children}</span>;
}
