/** Overall progress: cyan fill with a moving shimmer while running; error colour when failed. */
export function ProgressBar({ value, failed = false, running = true }: { value: number; failed?: boolean; running?: boolean }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div
      className="relative h-2 overflow-hidden rounded-full bg-line"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
    >
      <div
        className={`relative h-full origin-left overflow-hidden rounded-full transition-[width] duration-700 ease-atlas ${failed ? "bg-error" : "bg-cyan"}`}
        style={{ width: `${pct}%` }}
      >
        {running && !failed && pct < 100 && (
          <span
            aria-hidden
            className="absolute inset-0"
            style={{ background: "linear-gradient(90deg, transparent, rgb(255 255 255 / 0.35), transparent)", animation: "atlas-shimmer 2s linear infinite" }}
          />
        )}
      </div>
    </div>
  );
}
