import type { AnchorHTMLAttributes, ButtonHTMLAttributes } from "react";
import { Link, type LinkProps } from "react-router-dom";

/**
 * Buttons are physical: a 2px ink edge and a hard 3px shadow, and pressing pushes the button down onto it.
 *   primary   red ink block: the one action that matters on a screen
 *   secondary paper block with the same edge
 *   ghost     no block, underline on hover: low-emphasis actions inside paper
 *   arrow     mono caps with an arrow that steps forward on hover; inherits colour, so it works on the table and on paper
 *   danger    paper block with red text (destructive / risky)
 */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "arrow" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const physical = "border-2 border-press shadow-press active:translate-y-[2px] active:shadow-press-sm disabled:shadow-none disabled:translate-y-[2px]";
const variants: Record<ButtonVariant, string> = {
  primary: `${physical} bg-signal-btn text-[#fff8ee] hover:bg-[var(--signal-btn-hover)] font-semibold disabled:bg-paper-3 disabled:text-pencil disabled:border-rule-strong disabled:opacity-100`,
  secondary: `${physical} bg-paper text-ink hover:bg-paper-2 font-semibold`,
  danger: `${physical} bg-paper text-signal-ink hover:bg-signal-soft font-semibold`,
  ghost: "border-2 border-transparent text-ink-2 underline-offset-4 decoration-1 hover:text-ink hover:underline font-medium",
  arrow: "group border-[1.5px] border-current/35 hover:border-current font-mono uppercase tracking-[0.08em] font-medium",
};
const sizes: Record<ButtonSize, string> = {
  sm: "min-h-8 px-3 text-small gap-1.5",
  md: "min-h-10 px-4 text-[14px] gap-2",
  lg: "min-h-12 px-6 text-[15.5px] gap-2",
};
const arrowSizes: Record<ButtonSize, string> = {
  sm: "min-h-8 px-2.5 text-[11px] gap-2",
  md: "min-h-10 px-3.5 text-[12px] gap-2.5",
  lg: "min-h-12 px-5 text-[13px] gap-3",
};

/** Class string for anything that should look like a button (buttons, router links, anchors). */
export const buttonClass = (variant: ButtonVariant = "primary", size: ButtonSize = "md", extra = "") =>
  `inline-flex items-center justify-center whitespace-nowrap rounded-ui transition-[transform,box-shadow,background-color,border-color,color] duration-100 disabled:pointer-events-none disabled:opacity-55 ${variants[variant]} ${variant === "arrow" ? arrowSizes[size] : sizes[size]} ${extra}`;

/** The arrow that moves on hover; put it last inside an `arrow` button. */
export function Arrow({ dir = "right" }: { dir?: "right" | "left" | "down" }) {
  const rot = dir === "left" ? "rotate-180" : dir === "down" ? "rotate-90" : "";
  return (
    <span aria-hidden className={`inline-block transition-transform duration-200 ${dir === "left" ? "group-hover:-translate-x-1" : dir === "down" ? "group-hover:translate-y-0.5" : "group-hover:translate-x-1"}`}>
      <svg width="14" height="10" viewBox="0 0 14 10" className={rot} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="square"><path d="M0.5 5h12M8.5 1l4 4-4 4" /></svg>
    </span>
  );
}

export function Button({ variant = "primary", size = "md", className = "", type = "button", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return <button type={type} className={buttonClass(variant, size, className)} {...props} />;
}

export function ButtonLink({ variant = "primary", size = "md", className = "", ...props }: LinkProps & { variant?: ButtonVariant; size?: ButtonSize }) {
  return <Link className={buttonClass(variant, size, className)} {...props} />;
}

export function ButtonAnchor({ variant = "primary", size = "md", className = "", ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return <a className={buttonClass(variant, size, className)} {...props} />;
}
