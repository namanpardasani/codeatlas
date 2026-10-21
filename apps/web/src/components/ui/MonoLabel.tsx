import type { ReactNode } from "react";

/** Uppercase mono caption: "PLATE 01", stage labels, legends. */
export function MonoLabel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mono-label ${className}`}>{children}</div>;
}
