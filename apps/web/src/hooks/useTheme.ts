import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "codeatlas.theme";

const current = (): Theme => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");

/**
 * Light / dark theme. The initial value is set before first paint by public/theme-init.js (saved choice, else the OS
 * setting). Toggling saves the choice; until the user picks one, the page follows OS changes live.
 */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(current);

  const apply = useCallback((t: Theme) => {
    const html = document.documentElement;
    html.classList.add("theme-switching"); // no colour transitions during the swap
    html.dataset.theme = t;
    setThemeState(t);
    requestAnimationFrame(() => requestAnimationFrame(() => html.classList.remove("theme-switching")));
    window.dispatchEvent(new CustomEvent("codeatlas:theme", { detail: t }));
  }, []);

  const setTheme = useCallback((t: Theme) => {
    try {
      localStorage.setItem(KEY, t);
    } catch {
      /* private mode: still switches for this visit */
    }
    apply(t);
  }, [apply]);

  useEffect(() => {
    const sync = (e: Event) => setThemeState((e as CustomEvent<Theme>).detail);
    window.addEventListener("codeatlas:theme", sync);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = (e: MediaQueryListEvent) => {
      let saved: string | null = null;
      try {
        saved = localStorage.getItem(KEY);
      } catch {
        /* ignore */
      }
      if (saved !== "light" && saved !== "dark") apply(e.matches ? "dark" : "light");
    };
    mq.addEventListener("change", follow);
    return () => {
      window.removeEventListener("codeatlas:theme", sync);
      mq.removeEventListener("change", follow);
    };
  }, [apply]);

  return { theme, setTheme, toggle: () => setTheme(theme === "dark" ? "light" : "dark") };
}
