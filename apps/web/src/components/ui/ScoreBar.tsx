import { motion } from "framer-motion";
import { dur, ease } from "../../ui/motion";

/** Hotspot score 0-100: cyan, amber above 70. Grows from 0 on mount. The number is always shown (colour is not the only signal). */
export function ScoreBar({ value, max = 100, delay = 0 }: { value: number; max?: number; delay?: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const hot = pct > 70;
  return (
    <div className="flex items-center gap-3" role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={Math.round(value)} aria-label="score">
      <div className="h-1.5 w-28 overflow-hidden rounded-full bg-line">
        <motion.div
          className={`h-full rounded-full ${hot ? "bg-amber" : "bg-cyan"}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: dur.bar, ease: ease.out, delay }}
        />
      </div>
      <span className={`w-9 font-mono text-small leading-none tabular-nums ${hot ? "text-amber-soft" : "text-text-3"}`}>{Math.round(value)}</span>
    </div>
  );
}
