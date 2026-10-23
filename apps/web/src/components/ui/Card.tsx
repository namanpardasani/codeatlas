import type { CSSProperties, ReactNode } from "react";

/**
 * Things ON PAPER. Deliberately not one card: each variant is a different object.
 *   default / box  a ruled box (1px rule border)
 *   ruled          no box, a heavy ink rule on top: an editorial block
 *   note           a sticky note: highlighter paper, slight lift and tilt
 *   inset          a recessed area (paper-2), for code, logs and forms
 *   risk           red ink bar on the left with a red wash: "this will break"
 *   verified       green ink bar on the left: checked
 *   tint           alias of note (older code)
 */
export type CardVariant = "default" | "box" | "ruled" | "note" | "inset" | "risk" | "verified" | "tint" | "paper";

const tones: Record<CardVariant, string> = {
  default: "border border-rule bg-paper p-5",
  box: "border border-rule bg-paper p-5",
  paper: "border border-rule bg-paper p-5",
  ruled: "border-t-2 border-ink pt-4",
  note: "bg-hl-soft p-5 shadow-lift tilt",
  tint: "bg-hl-soft p-5 shadow-lift tilt",
  inset: "bg-paper-2 p-4",
  risk: "border-l-[3px] border-signal bg-signal-soft/70 py-4 pl-4 pr-5",
  verified: "border-l-[3px] border-verified bg-verified-soft/60 py-4 pl-4 pr-5",
};

export function Card({ children, className = "", variant = "default", tilt }: { children: ReactNode; className?: string; variant?: CardVariant; tilt?: number }) {
  const style = (variant === "note" || variant === "tint") ? ({ "--tilt": `${tilt ?? -0.8}deg` } as CSSProperties) : undefined;
  return <div className={`relative rounded-card text-ink ${tones[variant]} ${className}`} style={style}>{children}</div>;
}
