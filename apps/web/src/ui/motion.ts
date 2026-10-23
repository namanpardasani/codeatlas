/**
 * Motion tokens. Rules: every animation has a job (direction, progress, claim -> evidence, risk, guiding attention).
 * CSS keyframes for small loops, motion (motion/react) for state-driven UI.
 * Transform and opacity only (plus stroke-dashoffset for SVG). Reduced motion = no loops, no parallax, no enters.
 */
export const ease = {
  out: [0.22, 1, 0.36, 1] as [number, number, number, number],
};

/** seconds */
export const dur = { fast: 0.15, base: 0.25, enter: 0.6, bar: 0.9 };

export const stagger = 0.06;

/** springs: `ui` is crisp; `soft` has a touch of overshoot for things that pop in */
export const springs = {
  ui: { type: "spring", stiffness: 400, damping: 30 } as const,
  soft: { type: "spring", stiffness: 180, damping: 18, mass: 0.9 } as const,
};

/** loops live in CSS (index.css); periods in seconds */
export const loop = { pulse: 2.4, dash: 1.6, shimmer: 2.0, caret: 1.1 };

/** Standard enter: rise and fade. Pass `i` for staggered lists. */
export const rise = (i = 0, distance = 14) => ({
  initial: { opacity: 0, y: distance },
  animate: { opacity: 1, y: 0 },
  transition: { duration: dur.enter, ease: ease.out, delay: i * stagger },
});

/** Page transition: fade + 8px rise, 250 ms. */
export const pageTransition = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 8 },
  transition: { duration: dur.base, ease: ease.out },
};
