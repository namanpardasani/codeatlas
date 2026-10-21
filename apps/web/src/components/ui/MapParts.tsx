import type { ReactNode } from "react";

/** Legend: what the shapes on the map mean. Colour is never the only signal (shape and dash carry meaning too). */
export function Legend({ className = "" }: { className?: string }) {
  const Row = ({ children, label }: { children: ReactNode; label: string }) => (
    <li className="flex items-center gap-3">
      <svg width="30" height="14" viewBox="0 0 30 14" aria-hidden>
        {children}
      </svg>
      <span className="text-small text-text-3">{label}</span>
    </li>
  );
  return (
    <div className={className}>
      <div className="mono-label mb-3">LEGEND</div>
      <ul className="flex flex-col gap-2.5">
        <Row label="Central file">
          <circle cx="15" cy="7" r="5.5" fill="var(--color-cyan)" />
        </Row>
        <Row label="Hotspot">
          <circle cx="15" cy="7" r="5.5" fill="var(--color-amber)" />
        </Row>
        <Row label="Other file">
          <circle cx="15" cy="7" r="5" fill="none" stroke="var(--color-muted)" strokeWidth="1.5" />
        </Row>
        <Row label="Import">
          <path d="M2 7 H28" stroke="var(--color-faint)" strokeWidth="1.5" />
        </Row>
        <Row label="Import in a cycle">
          <path d="M2 7 H28" stroke="var(--color-amber)" strokeWidth="1.5" strokeDasharray="4 3" />
        </Row>
        <Row label="Selected file's imports">
          <path d="M2 7 H28" stroke="var(--color-cyan)" strokeWidth="1.5" strokeDasharray="4 3" />
        </Row>
      </ul>
    </div>
  );
}

/** Scale bar: the unit of distance on this map is one import hop (an atlas always has a scale). */
export function ScaleBar({ label = "1 import hop" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2" role="img" aria-label={`Scale: ${label}`}>
      <svg width="64" height="10" viewBox="0 0 64 10" aria-hidden>
        <path d="M1 3 V9 H63 V3" fill="none" stroke="var(--color-muted)" strokeWidth="1.25" />
        <path d="M32 9 V5" stroke="var(--color-muted)" strokeWidth="1.25" />
      </svg>
      <span className="mono-label">{label}</span>
    </div>
  );
}

/** North mark: purely an atlas flourish; marks the top of the map. */
export function NorthMark({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" role="img" aria-label="North">
      <circle cx="18" cy="20" r="11" fill="none" stroke="var(--color-border-strong)" strokeWidth="1" />
      <path d="M18 7 L22 20 L18 17.5 L14 20 Z" fill="var(--color-cyan)" />
      <text x="18" y="35" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="8" fill="var(--color-muted)" letterSpacing="1">
        N
      </text>
    </svg>
  );
}

/** Grid letters (A, B, C... along the top, 1, 2, 3... down the left). `offset` shifts them as the map pans. */
export function GridLetters({ cols = 5, rows = 4, offset = { x: 0, y: 0 } }: { cols?: number; rows?: number; offset?: { x: number; y: number } }) {
  const letters = Array.from({ length: cols }, (_, i) => String.fromCharCode(65 + i));
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 select-none font-mono text-micro text-dim">
      <div className="absolute inset-x-0 top-1 flex" style={{ transform: `translateX(${offset.x}px)` }}>
        {letters.map((l) => (
          <span key={l} className="flex-1 text-center">
            {l}
          </span>
        ))}
      </div>
      <div className="absolute inset-y-0 left-2 flex flex-col" style={{ transform: `translateY(${offset.y}px)` }}>
        {Array.from({ length: rows }, (_, i) => (
          <span key={i} className="flex flex-1 items-center">
            {i + 1}
          </span>
        ))}
      </div>
    </div>
  );
}
