import type { ReactNode } from "react";

/** Legend: what the shapes on the map mean. Colour is never the only signal (size, dash and arrowheads carry meaning too). */
export function Legend({ className = "" }: { className?: string }) {
  const Row = ({ children, label }: { children: ReactNode; label: string }) => (
    <li className="flex items-center gap-3">
      <svg width="28" height="14" viewBox="0 0 28 14" aria-hidden>{children}</svg>
      <span className="text-small text-ink-2">{label}</span>
    </li>
  );
  return (
    <div className={className}>
      <div className="mono-label mb-3">Legend</div>
      <ul className="flex flex-col gap-2">
        <Row label="Central file"><circle cx="14" cy="7" r="5.5" fill="var(--ink)" /></Row>
        <Row label="Hotspot"><circle cx="14" cy="7" r="5.5" fill="var(--signal)" stroke="var(--ink)" strokeWidth="1.2" /></Row>
        <Row label="Other file"><circle cx="14" cy="7" r="5" fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.3" /></Row>
        <Row label="Import"><path d="M2 7 H26" stroke="color-mix(in srgb, var(--ink) 45%, transparent)" strokeWidth="1.2" /></Row>
        <Row label="Import in a cycle"><path d="M2 7 H26" stroke="var(--signal)" strokeWidth="2" strokeDasharray="5 3" /></Row>
        <Row label="Selected file's imports"><path d="M2 7 H26" stroke="var(--ink)" strokeWidth="2.2" /></Row>
      </ul>
    </div>
  );
}
