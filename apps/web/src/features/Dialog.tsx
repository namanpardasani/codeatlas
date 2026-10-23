import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, type ReactNode } from "react";
import { dur, ease } from "../ui/motion";

/** Accessible modal: a sheet laid on the table (it drops in, which says where it came from). role=dialog, labelled,
 *  focus moves in, Esc closes, focus returns to the opener. */
export function Dialog({ open, title, onClose, children, wide = false }: { open: boolean; title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center bg-[color-mix(in_srgb,var(--table)_78%,transparent)] px-4 pt-[10vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: dur.base }}
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          <motion.div
            ref={ref}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            tabIndex={-1}
            initial={{ opacity: 0, y: -10, rotate: -0.6 }}
            animate={{ opacity: 1, y: 0, rotate: 0 }}
            exit={{ opacity: 0, y: 6 }}
            transition={{ duration: dur.base, ease: ease.out }}
            className={`sheet w-full p-6 outline-none ${wide ? "max-w-5xl" : "max-w-xl"}`}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
