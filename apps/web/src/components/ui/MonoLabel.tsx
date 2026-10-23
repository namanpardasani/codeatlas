import type { ReactNode } from "react";

/** Small uppercase caption above a group (legends, side panels). */
export function MonoLabel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mono-label ${className}`}>{children}</div>;
}
