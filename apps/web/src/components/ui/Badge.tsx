import type { ReactNode } from "react";

export type Tone = "neutral" | "success" | "danger" | "warning" | "info";

const tones: Record<Tone, string> = {
  neutral: "bg-subtle text-muted",
  success: "bg-subtle text-success",
  danger: "bg-subtle text-danger",
  warning: "bg-subtle text-warning",
  info: "bg-subtle text-info",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-block rounded-ui px-gap py-0.5 text-small ${tones[tone]}`}>{children}</span>
  );
}
