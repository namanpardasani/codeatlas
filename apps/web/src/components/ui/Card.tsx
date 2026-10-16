import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-ui border border-border bg-surface p-gutter ${className}`}>{children}</div>;
}
