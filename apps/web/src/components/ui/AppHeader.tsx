import { LayoutGroup, motion } from "framer-motion";
import type { ReactNode } from "react";
import { dur, ease } from "../../ui/motion";
import { Button } from "./Button";
import { Logo } from "./Logo";

export interface HeaderTab {
  id: string;
  label: string;
}

/**
 * Repo header: logo / repo path / commit badge, actions on the right, then tabs with a 2px cyan underline that SLIDES
 * between tabs (shared layout animation). The underline is the only animated element, so it always has a job:
 * showing where you came from and where you are.
 */
export function AppHeader({
  repo,
  badge,
  tabs,
  active,
  onTab,
  onReanalyze,
  onConnect,
  right,
}: {
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
    <header className="border-b border-line bg-bg-raised">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-3 px-6 py-3">
        <a href="/" className="rounded-ui" aria-label="CodeAtlas home">
          <Logo />
        </a>
        {repo && (
          <>
            <span aria-hidden className="text-ghost">
              /
            </span>
            <span className="font-mono text-small text-text-2">{repo}</span>
          </>
        )}
        {badge && <span className="rounded-md bg-cyan-bg px-2 py-0.5 font-mono text-micro text-cyan-soft">{badge}</span>}
        <div className="ml-auto flex flex-wrap items-center gap-3">
          {right}
          {onReanalyze && (
            <Button variant="secondary" onClick={onReanalyze}>
              Re-analyze
            </Button>
          )}
          {onConnect && <Button onClick={onConnect}>Connect MCP</Button>}
        </div>
      </div>
      {tabs && (
        <nav className="mx-auto max-w-7xl overflow-x-auto px-6" aria-label="Sections">
          <LayoutGroup id="app-tabs">
            <div role="tablist" className="flex min-w-max gap-1">
              {tabs.map((t) => {
                const on = t.id === active;
                return (
                  <button
                    key={t.id}
                    role="tab"
                    aria-selected={on}
                    onClick={() => onTab?.(t.id)}
                    className={`relative min-h-11 px-4 text-body font-medium transition-colors duration-150 ${on ? "text-text" : "text-muted hover:text-text-2"}`}
                  >
                    {t.label}
                    {on && (
                      <motion.span
                        layoutId="tab-underline"
                        className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-cyan"
                        transition={{ duration: dur.base, ease: ease.out }}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          </LayoutGroup>
        </nav>
      )}
    </header>
  );
}
