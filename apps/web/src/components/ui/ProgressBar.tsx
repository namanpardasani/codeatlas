/** Overall progress drawn as a ruler being inked in: square, ticks every 10%, ink fill; red when the run failed. */
export function ProgressBar({ value, failed = false, label = "Progress" }: { value: number; failed?: boolean; running?: boolean; label?: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="relative h-3.5 border-[1.5px] border-ink bg-paper" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
      <div className={`h-full transition-[width] duration-700 ease-out ${failed ? "bg-signal" : "bg-ink"}`} style={{ width: `${pct}%` }} />
      <span aria-hidden className="pointer-events-none absolute inset-0" style={{ backgroundImage: "repeating-linear-gradient(90deg, transparent 0 calc(10% - 1px), var(--rule-strong) calc(10% - 1px) 10%)" }} />
    </div>
  );
}
