import type { CSSProperties, ElementType, ReactNode } from "react";

/**
 * A sheet of paper lying on the table: grain, a deckle shadow, optionally a slight rotation, a strip of tape or a fold.
 * Use it for things that sit ON THE TABLE (page bodies, landing sheets, dialogs). Inside paper, use Card.
 * Rotation is decoration: keep it between -1.5 and 1.5 degrees and leave functional sheets (forms, tables) straight.
 */
export function Sheet({ children, className = "", tilt = 0, tape = false, tapeAt, fold = false, as: As = "div", style, ...rest }: {
  children: ReactNode;
  className?: string;
  tilt?: number;
  tape?: boolean;
  /** horizontal tape position, e.g. "20%" */
  tapeAt?: string;
  fold?: boolean;
  as?: ElementType;
  style?: CSSProperties;
} & Record<string, unknown>) {
  const s = { ...(tilt ? { "--tilt": `${tilt}deg` } : {}), ...(tapeAt ? { "--tape-x": tapeAt } : {}), ...style } as CSSProperties;
  return (
    <As className={`sheet relative ${tilt ? "tilt" : ""} ${tape ? "tape" : ""} ${fold ? "fold" : ""} ${className}`} style={s} {...rest}>
      {children}
    </As>
  );
}
