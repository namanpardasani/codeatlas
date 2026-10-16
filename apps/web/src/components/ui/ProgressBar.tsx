export function ProgressBar({ value, failed = false }: { value: number; failed?: boolean }) {
  return (
    <div className="h-2 overflow-hidden rounded-ui bg-subtle" role="progressbar" aria-valuenow={value}>
      <div
        className={`h-full ${failed ? "bg-danger" : "bg-primary"}`}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}
