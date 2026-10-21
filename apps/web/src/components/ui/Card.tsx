import type { ReactNode } from "react";

/** Surface with a 1px border (no shadow). `risk` = amber tint for cycles / hotspots; `tint` = cyan wash for prompts. */
export function Card({
  children,
  className = "",
  variant = "default",
}: {
  children: ReactNode;
  className?: string;
  variant?: "default" | "risk" | "tint";
}) {
  const tone = {
    default: "border-border bg-surface",
    risk: "border-amber-border bg-amber-bg",
    tint: "border-cyan-bg bg-cyan-tint",
  }[variant];
  return <div className={`rounded-card border p-5 ${tone} ${className}`}>{children}</div>;
}
