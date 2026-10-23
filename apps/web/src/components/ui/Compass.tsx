import { useEffect, useRef } from "react";
import { useMotionOff } from "../../hooks/useMotionOff";

/**
 * The compass from the logo. Three behaviours, each with a reason:
 *   track  the needle follows the pointer (landing only: a small easter egg that says "this thing is alive")
 *   hunt   the needle hunts for north while a repository is being analysed (progress you can feel)
 *   still  points north (everywhere else)
 * Tracking writes the transform straight to the DOM (no React re-render per pointer move) and is off with reduced motion.
 */
export function Compass({ size = 30, mode = "still", className = "", title }: {
  size?: number;
  mode?: "still" | "track" | "hunt";
  className?: string;
  title?: string;
}) {
  const needle = useRef<SVGGElement | null>(null);
  const off = useMotionOff();

  useEffect(() => {
    if (mode !== "track" || off) return;
    const el = needle.current;
    const svg = el?.ownerSVGElement;
    if (!el || !svg) return;
    let raf = 0;
    const move = (e: PointerEvent) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const r = svg.getBoundingClientRect();
        const a = (Math.atan2(e.clientY - (r.top + r.height / 2), e.clientX - (r.left + r.width / 2)) * 180) / Math.PI + 90;
        el.style.transform = `rotate(${a}deg)`;
      });
    };
    window.addEventListener("pointermove", move, { passive: true });
    return () => { window.removeEventListener("pointermove", move); cancelAnimationFrame(raf); };
  }, [mode, off]);

  return (
    <svg width={size} height={size} viewBox="0 0 40 40" className={`shrink-0 ${className}`} role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <circle cx="20" cy="20" r="17.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="20" cy="20" r="13.5" fill="none" stroke="currentColor" strokeWidth="0.75" strokeDasharray="1 2.2" opacity="0.7" />
      <path d="M20 1.5v4M20 34.5v4M1.5 20h4M34.5 20h4" stroke="currentColor" strokeWidth="1.5" />
      <g
        ref={needle}
        className={mode === "hunt" && !off ? "anim-hunt" : ""}
        style={{ transformOrigin: "20px 20px", transition: mode === "track" ? "transform 0.5s cubic-bezier(.3,1.5,.5,1)" : undefined }}
      >
        <path d="M20 6.5 23.6 20h-7.2Z" fill="var(--signal)" />
        <path d="M20 33.5 16.4 20h7.2Z" fill="currentColor" />
        <circle cx="20" cy="20" r="1.6" fill="var(--table)" stroke="currentColor" strokeWidth="1" />
      </g>
    </svg>
  );
}
