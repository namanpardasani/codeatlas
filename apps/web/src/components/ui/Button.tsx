import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary";

const variants: Record<Variant, string> = {
  primary: "bg-primary text-primary-fg border-primary",
  secondary: "bg-surface text-fg border-border",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={`rounded-ui border px-gutter py-gap text-body disabled:opacity-50 ${variants[variant]} ${className}`}
      {...props}
    />
  );
}
