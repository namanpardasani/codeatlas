import type { ReactNode } from "react";

/**
 * The heading of a page sheet, set like a map's cartouche: sheet number and section in mono, the title in Fraunces,
 * one plain sentence under it, actions on the right. Every repo page uses it, so the numbering reads as one atlas.
 */
export function PageHead({ sheet, title, children, actions, className = "" }: {
  sheet: string;
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-wrap items-end justify-between gap-x-8 gap-y-4 ${className}`}>
      <div className="min-w-0 max-w-3xl">
        <div className="mono-label">{sheet}</div>
        <h1 className="text-title mt-2 text-ink">{title}</h1>
        {children && <div className="mt-3 max-w-2xl text-[15px] leading-relaxed text-ink-2">{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-3">{actions}</div>}
    </div>
  );
}
