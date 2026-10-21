/** Three connected nodes (two cyan, one amber) + wordmark. The amber node is the one to look at. */
export function Logo({ size = 28, wordmark = true }: { size?: number; wordmark?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="CodeAtlas logo" className="shrink-0">
        <path d="M8 23 L16 8 L25 23 Z" fill="none" stroke="var(--color-border-strong)" strokeWidth="1.5" strokeLinejoin="round" />
        <circle cx="16" cy="8" r="4" fill="var(--color-cyan)" />
        <circle cx="8" cy="23" r="3.5" fill="var(--color-cyan)" />
        <circle cx="25" cy="23" r="3.5" fill="var(--color-amber)" />
      </svg>
      {wordmark && <span className="font-display text-[19px] font-bold tracking-tight text-text">CodeAtlas</span>}
    </span>
  );
}
