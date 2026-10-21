/** Shimmering placeholder for content that is loading (never a spinner for content). */
export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div aria-hidden className={`skeleton ${className}`} />;
}
