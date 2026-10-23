import { motion } from "motion/react";
import { dur, ease } from "../../ui/motion";

/**
 * Hotspot score 0-100 on a small ruler: red ink above 70, ochre above 40, ink below. Square ends, tick marks every
 * quarter. Grows from 0 on mount (it shows the size of the number). The number is always written next to it.
 */
export function ScoreBar({ value, max = 100, delay = 0 }: { value: number; max?: number; delay?: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const level = pct > 70 ? "high" : pct > 40 ? "mid" : "low";
  const bar = { high: "bg-signal", mid: "bg-caution", low: "bg-ink-2/70" }[level];
  const num = { high: "text-signal-ink font-semibold", mid: "text-ink", low: "text-pencil" }[level];
  return (
    <div className="flex items-center gap-2.5" role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={Math.round(value)} aria-label="score">
      <div className="relative h-2 w-24 border border-rule-strong bg-paper">
        <motion.div className={`h-full ${bar}`} initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: dur.bar, ease: ease.out, delay }} />
        <span aria-hidden className="absolute inset-0" style={{ backgroundImage: "linear-gradient(90deg, transparent calc(25% - 1px), var(--rule-strong) calc(25% - 1px) 25%, transparent 25% calc(50% - 1px), var(--rule-strong) calc(50% - 1px) 50%, transparent 50% calc(75% - 1px), var(--rule-strong) calc(75% - 1px) 75%, transparent 75%)" }} />
      </div>
      <span className={`w-7 font-mono text-small leading-none tabular-nums ${num}`}>{Math.round(value)}</span>
    </div>
  );
}
