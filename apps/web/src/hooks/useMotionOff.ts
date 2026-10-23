import { useReducedMotion } from "motion/react";

/** True when motion must be skipped: the OS asks for reduced motion, or the dev toggle froze motion for screenshots. */
export function useMotionOff(): boolean {
  const reduce = useReducedMotion();
  const devOff = typeof document !== "undefined" && document.documentElement.dataset.motion === "off";
  return Boolean(reduce) || devOff;
}
