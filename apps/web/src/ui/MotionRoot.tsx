import { MotionConfig } from "framer-motion";
import { useEffect, useState, type ReactNode } from "react";

const KEY = "codeatlas.motion";

/**
 * Wraps the app: Framer Motion honours prefers-reduced-motion ("user"), and a DEV-ONLY toggle can switch all motion off
 * (sets html[data-motion=off], which index.css uses to kill CSS loops) so screenshots and tests are stable.
 * The toggle is not rendered in production builds.
 */
export function MotionRoot({ children }: { children: ReactNode }) {
  const [off, setOff] = useState(() => {
    try {
      return import.meta.env.DEV && localStorage.getItem(KEY) === "off";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    document.documentElement.dataset.motion = off ? "off" : "on";
    try {
      localStorage.setItem(KEY, off ? "off" : "on");
    } catch {
      /* private mode: toggle still works for this page view */
    }
  }, [off]);
  return (
    <MotionConfig reducedMotion={off ? "always" : "user"}>
      {children}
      {import.meta.env.DEV && (
        <button
          onClick={() => setOff((v) => !v)}
          className="fixed bottom-3 left-3 z-50 rounded-ui border border-border bg-surface px-2 py-1 font-mono text-micro text-muted hover:text-text"
          aria-pressed={off}
          title="Dev only: disable all motion (stable screenshots)"
        >
          motion: {off ? "off" : "on"}
        </button>
      )}
    </MotionConfig>
  );
}
