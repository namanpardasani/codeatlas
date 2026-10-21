import type { ReactNode } from "react";
import { Card } from "./Card";

/** Overview tile: 12px muted label over a 32px display value. `risk` turns it amber (e.g. cycles > 0). */
export function StatCard({ label, value, hint, risk = false }: { label: string; value: ReactNode; hint?: string; risk?: boolean }) {
  return (
    <Card variant={risk ? "risk" : "default"} className="flex h-full flex-col gap-1">
      <span className="text-[12px] text-muted">{label}</span>
      <span className={`font-display text-[32px] font-bold leading-none tracking-tight ${risk ? "text-amber-soft" : "text-text"}`}>{value}</span>
      {hint && <span className="text-[12px] text-dim">{hint}</span>}
    </Card>
  );
}
