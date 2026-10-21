import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost";

// primary: cyan fill. Hover lifts 1px and shows a 4px cyan ring at 18% opacity. 44px minimum touch target.
const variants: Record<Variant, string> = {
  primary:
    "bg-cyan text-cyan-ink border-cyan font-bold hover:-translate-y-px hover:shadow-[0_0_0_4px_rgb(34_211_238/0.18)]",
  secondary: "bg-surface text-text border-border font-semibold hover:border-border-strong hover:bg-surface-2",
  ghost: "bg-transparent text-text-3 border-transparent font-semibold hover:bg-surface-2 hover:text-text",
};

export function Button({
  variant = "primary",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type={type}
      className={`inline-flex min-h-11 items-center justify-center gap-gap rounded-ui border px-5 py-gap text-body transition-[transform,box-shadow,background-color,border-color] duration-150 ease-atlas disabled:translate-y-0 disabled:opacity-50 disabled:shadow-none motion-reduce:transition-none motion-reduce:hover:translate-y-0 ${variants[variant]} ${className}`}
      {...props}
    />
  );
}
