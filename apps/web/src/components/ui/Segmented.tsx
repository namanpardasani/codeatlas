import type { ReactNode } from "react";

/**
 * A choice between two to four views, written like a printed option list: "FILES / FOLDERS", the chosen one in ink
 * with a red underline. Replaces the stock pill segmented control. Each option is a toggle button (aria-pressed).
 */
export function Segmented<T extends string>({ value, options, onChange, label, className = "" }: {
  value: T;
  options: { id: T; label: ReactNode }[];
  onChange: (v: T) => void;
  label: string;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label} className={`inline-flex flex-wrap items-center gap-x-1 font-mono text-[12px] uppercase tracking-[0.1em] ${className}`}>
      {options.map((o, i) => (
        <span key={o.id} className="inline-flex items-center gap-1">
          {i > 0 && <span aria-hidden className="text-faint">/</span>}
          <button
            type="button"
            aria-pressed={value === o.id}
            onClick={() => onChange(o.id)}
            className={`min-h-8 px-1.5 underline-offset-[7px] transition-colors ${value === o.id ? "text-ink underline decoration-signal decoration-2" : "text-pencil hover:text-ink"}`}
          >
            {o.label}
          </button>
        </span>
      ))}
    </div>
  );
}
