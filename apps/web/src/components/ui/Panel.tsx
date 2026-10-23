import type { ReactNode } from "react";

/**
 * A titled section on paper. Not a box: a heavy ink rule, a serif title and the content under it, like a section of
 * a printed report. `risk` turns the rule red.
 */
export function Panel({ title, actions, children, variant = "default", label, description, className = "" }: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
  variant?: "default" | "risk";
  /** optional small caption above the title */
  label?: string;
  description?: string;
  className?: string;
}) {
  return (
    <section className={`border-t-2 pt-3 ${variant === "risk" ? "border-signal" : "border-ink"} ${className}`}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          {label && <div className="mono-label mb-1">{label}</div>}
          <h2 className="text-section text-ink">{title}</h2>
          {description && <p className="mt-1 text-small text-pencil">{description}</p>}
        </div>
        {actions && <div className="shrink-0">{actions}</div>}
      </div>
      {children}
    </section>
  );
}
