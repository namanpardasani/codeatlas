/**
 * Motion tokens: the only place durations and easings are defined.
 * Rules (see NOTES.md "Design system"): every animation has a job (direction, progress, claim -> evidence, risk).
 * CSS keyframes for loops, Framer Motion for enter/exit/layout. Transform and opacity only. Reduced motion = no loops, no enters.
 */
export const ease = {
  out: [0.2, 0.7, 0.2, 1] as [number, number, number, number],
};

/** seconds (Framer Motion units) */
export const dur = {
  fast: 0.15,
  base: 0.25,
  enter: 0.7,
  bar: 0.9,
};

export const stagger = 0.08;

/** loops live in CSS (index.css); these are their periods in seconds, documented here so they stay in 1.4-3.2 s */
export const loop = { pulse: 2.4, dash: 1.6, shimmer: 2.0, caret: 1.1 };

/** Standard enter: rise 14px and fade. Pass `i` for staggered lists. */
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
