import type { ReactNode } from "react";

/** A titled section: the standard container for page content (18px radius). */
export function Panel({
  title,
  actions,
  children,
  variant = "default",
  label,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
  variant?: "default" | "risk";
  /** optional mono caption above the title, e.g. "PLATE 02" */
  label?: string;
}) {
  const tone = variant === "risk" ? "border-amber-border bg-amber-bg" : "border-border bg-surface";
  return (
    <section className={`rounded-panel border p-6 ${tone}`}>
      <div className="mb-4 flex items-start justify-between gap-gap">
        <div>
          {label && <div className="mono-label mb-1">{label}</div>}
          <h2 className="text-section text-text">{title}</h2>
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}
