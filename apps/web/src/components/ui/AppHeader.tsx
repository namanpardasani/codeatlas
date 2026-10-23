import type { ReactNode } from "react";
import { Arrow, Button } from "./Button";
import { Logo } from "./Logo";
import { ThemeToggle } from "./ThemeToggle";

export interface HeaderTab {
  id: string;
  label: string;
}

/**
 * Repo header, on the table: logo / repo name / commit, actions on the right. Under it, folder tabs that stand on the
 * top edge of the page sheet; the open tab is cut from the same paper as the sheet, so "where am I" needs no underline.
 */
export function AppHeader({ repo, badge, tabs, active, onTab, onReanalyze, onConnect, right }: {
  repo?: string;
  badge?: string;
  tabs?: HeaderTab[];
  active?: string;
  onTab?: (id: string) => void;
  onReanalyze?: () => void;
  onConnect?: () => void;
  right?: ReactNode;
}) {
  return (
    <header className="bg-table text-table-ink">
      <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-x-4 gap-y-2 px-4 pb-3 pt-4 sm:px-6">
        <a href="/" className="rounded-ui" aria-label="CodeAtlas home">
          <Logo size={28} />
        </a>
        {repo && (
          <>
            <span aria-hidden className="text-table-muted">/</span>
            <span className="min-w-0 truncate font-display text-[19px] italic text-table-ink [font-variation-settings:'SOFT'_100]">{repo}</span>
          </>
        )}
        {badge && <span className="hidden font-mono text-[11.5px] text-table-muted sm:inline">{badge}</span>}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {right}
          {onReanalyze && (
            <Button variant="arrow" size="sm" onClick={onReanalyze} className="text-table-ink">
              Re-analyze
            </Button>
          )}
          {onConnect && (
            <Button variant="arrow" size="sm" onClick={onConnect} className="text-table-ink">
              Connect MCP <Arrow />
            </Button>
          )}
          <ThemeToggle />
        </div>
      </div>
      {tabs && (
        <nav className="mx-auto max-w-[1360px] overflow-x-auto px-4 sm:px-6 [scrollbar-width:none]" aria-label="Sections">
          <div role="tablist" className="flex min-w-max items-end gap-1 pl-2">
            {tabs.map((t, i) => {
              const on = t.id === active;
              return (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={on}
                  onClick={() => onTab?.(t.id)}
                  className={`relative flex items-baseline gap-2 rounded-t-[3px] px-4 text-[14px] transition-colors duration-100 ${
                    on ? "paper z-10 min-h-11 pt-3 font-semibold text-ink" : "min-h-10 bg-table-2 pt-2.5 text-table-muted hover:bg-table-3 hover:text-table-ink"
                  }`}
                >
                  <span className={`font-mono text-[10.5px] ${on ? "text-pencil" : "text-table-muted"}`}>{String(i + 1).padStart(2, "0")}</span>
                  {t.label}
                </button>
              );
            })}
          </div>
        </nav>
      )}
    </header>
  );
}
