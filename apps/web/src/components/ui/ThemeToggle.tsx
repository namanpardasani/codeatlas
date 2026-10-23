import { useTheme } from "../../hooks/useTheme";

/** Day / night paper switch for the table. Written out in mono so it reads as a setting, not a mystery icon. */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const now = theme === "dark" ? "night" : "day";
  const next = theme === "dark" ? "day" : "night";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`${now} paper, switch to ${next}`}
      title={`Switch to ${next} paper`}
      className={`inline-flex min-h-9 items-center gap-2 rounded-ui px-2 font-mono text-[11px] uppercase tracking-[0.1em] text-table-muted transition-colors hover:text-table-ink ${className}`}
    >
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
        <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
        <path d={theme === "dark" ? "M7 1.5a5.5 5.5 0 0 1 0 11Z" : "M7 1.5a5.5 5.5 0 0 0 0 11Z"} fill="currentColor" />
      </svg>
      <span className="hidden sm:inline">{theme === "dark" ? "night" : "day"}</span>
    </button>
  );
}
