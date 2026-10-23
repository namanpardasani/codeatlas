import { Compass } from "./Compass";

/** CodeAtlas mark: the compass plus the wordmark in Fraunces. Inherits colour (table ink on the table, ink on paper). */
export function Logo({ size = 30, wordmark = true, needle = "still" }: { size?: number; wordmark?: boolean; needle?: "still" | "track" | "hunt" }) {
  return (
    <span className="inline-flex items-center gap-2.5" aria-label="CodeAtlas" role="img">
      <Compass size={size} mode={needle} />
      {wordmark && <span aria-hidden className="font-display text-[21px] font-semibold leading-none tracking-[-0.02em] [font-variation-settings:'SOFT'_50]">CodeAtlas</span>}
    </span>
  );
}
