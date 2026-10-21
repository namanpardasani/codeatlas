import { animate, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

/** Smoothly count from the previous value to `target` (400 ms). Instant when reduced motion is on. */
export function useCountUp(target: number | null | undefined, duration = 0.4): number | null {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState<number | null>(target ?? null);
  const from = useRef(0);
  useEffect(() => {
    if (target === null || target === undefined) return setShown(null);
    if (reduce) {
      from.current = target;
      return setShown(target);
    }
    const controls = animate(from.current, target, {
      duration,
      ease: [0.2, 0.7, 0.2, 1],
      onUpdate: (v) => setShown(Math.round(v)),
      onComplete: () => (from.current = target),
    });
    return () => controls.stop();
  }, [target, duration, reduce]);
  return shown;
}
