import { motion } from "motion/react";
import type { ReactNode } from "react";
import { useMotionOff } from "../../hooks/useMotionOff";

/**
 * A rubber stamp: double ring (round) or double frame (rect), mono caps, slightly rotated, slightly uneven ink.
 * It carries a verdict (risk label, "checked by hand", "fixed here"), so it is used sparingly.
 * `land` plays the stamp coming down once (the one moment it has a job: a verdict arriving).
 */
export function Stamp({ children, tone = "ink", shape = "round", rotate = -8, size = 104, land = false, backed = false, className = "", label }: {
  children: ReactNode;
  tone?: "ink" | "signal" | "verified" | "caution";
  shape?: "round" | "rect";
  rotate?: number;
  size?: number;
  land?: boolean;
  /** a paper patch behind the stamp, for stamps that hang over the edge of a sheet onto the table */
  backed?: boolean;
  className?: string;
  /** accessible text when the children are visual */
  label?: string;
}) {
  const off = useMotionOff();
  const color = { ink: "text-ink", signal: "text-signal-ink", verified: "text-verified-ink", caution: "text-caution-ink" }[tone];
  const round = shape === "round";
  return (
    <motion.div
      role={label ? "img" : undefined}
      aria-label={label}
      className={`pointer-events-none relative inline-grid select-none place-items-center text-center font-mono font-semibold uppercase leading-[1.2] tracking-[0.12em] ${color} ${className}`}
      style={round ? { width: size, height: size, fontSize: Math.max(9, size / 10) } : { fontSize: 12, padding: "8px 14px" }}
      initial={land && !off ? { scale: 1.7, rotate: rotate - 10, opacity: 0 } : { rotate }}
      whileInView={land && !off ? { scale: 1, rotate, opacity: 0.92 } : undefined}
      animate={land && !off ? undefined : { rotate, opacity: 0.92 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{ type: "spring", stiffness: 520, damping: 22 }}
    >
      <span aria-hidden className={`absolute inset-0 border-[2.5px] border-current ${round ? "rounded-full" : "rounded-[3px]"} ${backed ? "bg-paper" : ""}`} />
      <span aria-hidden className={`absolute border border-dashed border-current ${round ? "inset-[5px] rounded-full" : "inset-[3px] rounded-[2px]"}`} />
      <span className="relative px-2" aria-hidden={label ? true : undefined}>{children}</span>
    </motion.div>
  );
}
