import type { ReactNode } from "react";
import { Card } from "./Card";

/** A titled section: the standard container for page content. */
export function Panel({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card>
      <div className="mb-gutter flex items-center justify-between gap-gap">
        <h2 className="text-title font-semibold">{title}</h2>
        {actions}
      </div>
      {children}
    </Card>
  );
}
