import type { ReactNode } from "react";

/**
 * A note written in the margin: soft italic serif, a little rotated, with an optional hand-drawn arrow pointing at the
 * thing it talks about. Always says something true about the data next to it.
 */
export function MarginNote({ children, arrow, className = "", tone = "pencil", rotate = -3 }: {
  children: ReactNode;
  arrow?: "down-right" | "down-left" | "right" | "left" | "up-right" | "up-left";
  className?: string;
  /** pencil on paper; highlighter on the dark table */
  tone?: "pencil" | "hl" | "signal";
  rotate?: number;
}) {
  const color = { pencil: "text-pencil", hl: "text-hl", signal: "text-signal-ink" }[tone];
  const paths: Record<NonNullable<typeof arrow>, string> = {
    "down-right": "M4 4c18 2 32 10 44 26m0 0-1.5-9m1.5 9-8.5-3",
    "down-left": "M52 4C34 6 20 14 8 30m0 0 1.5-9M8 30l8.5-3",
    right: "M2 14c14-6 30-6 46 0m0 0-8-5m8 5-8 4",
    left: "M54 14C40 8 24 8 8 14m0 0 8-5m-8 5 8 4",
    "up-right": "M4 30C20 26 34 18 46 4m0 0-8 2m8-2-1 8",
    "up-left": "M52 30C36 26 22 18 10 4m0 0 8 2m-8-2 1 8",
  };
  const svg = arrow && (
    <svg aria-hidden width="56" height="34" viewBox="0 0 56 34" className={`block ${arrow.startsWith("up") ? "mb-1" : "mt-1"}`} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d={paths[arrow]} />
    </svg>
  );
  return (
    <span className={`text-wonk inline-block text-[17px] leading-tight ${color} ${className}`} style={{ transform: `rotate(${rotate}deg)` }}>
      {arrow?.startsWith("up") && svg}
      {children}
      {arrow && !arrow.startsWith("up") && svg}
    </span>
  );
}
