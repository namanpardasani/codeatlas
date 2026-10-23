import { useEffect, useMemo, useRef, useState } from "react";
import { getRepoFile } from "../api";
import { Skeleton } from "../components/ui";
import { highlightLines } from "./highlight";

export interface ViewerTarget {
  path: string;
  start: number;
  end: number;
  /** bump to re-run the flash when the same range is clicked again */
  nonce?: number;
}

const MAX_LINES = 1500;

/**
 * Code viewer: dark, line numbers, syntax highlighting from our tokens. When `target` changes it smooth-scrolls to the range
 * and swipes a highlighter across it (lands bright, settles, with an amber bar in the gutter): the link between a claim and its evidence.
 */
export default function CodeViewer({ repoId, target, onClose }: { repoId: string; target: ViewerTarget; onClose?: () => void }) {
  const [code, setCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState(true);
  const startRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setCode(null);
    setError(null);
    getRepoFile(repoId, target.path)
      .then((f) => setCode(f.content.replace(/\n$/, "")))
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load file"));
  }, [repoId, target.path]);

  const lines = useMemo(() => (code === null ? null : highlightLines(code, target.path)), [code, target.path]);

  useEffect(() => {
    if (!lines) return;
    setFlash(true);
    startRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    const t = setTimeout(() => setFlash(false), 950);
    return () => clearTimeout(t);
  }, [lines, target.start, target.end, target.nonce]);

  const total = lines?.length ?? 0;
  const from = total > MAX_LINES ? Math.max(1, target.start - 200) : 1;
  const to = total > MAX_LINES ? Math.min(total, from + MAX_LINES - 1) : total;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-sm border border-rule bg-paper-2">
      <div className="flex items-center justify-between gap-3 border-b-2 border-ink bg-paper px-4 py-2.5">
        <span className="min-w-0 truncate font-mono text-small text-ink" title={target.path}>
          {target.path} <span className="text-pencil">:{target.start}–{target.end}</span>
        </span>
        {onClose && (
          <button onClick={onClose} aria-label="Close code viewer" className="rounded-ui px-2 py-1 font-mono text-[11px] uppercase tracking-[0.1em] text-pencil hover:text-ink">
            Close
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto py-2 font-mono text-[13px] leading-6" role="region" aria-label={`Source of ${target.path}`} tabIndex={0}>
        {error && <p className="px-4 text-danger-text">{error}</p>}
        {!lines && !error && (
          <div className="flex flex-col gap-2 px-4">
            <Skeleton className="h-4 w-2/3" /> <Skeleton className="h-4 w-1/2" /> <Skeleton className="h-4 w-3/4" />
          </div>
        )}
        {lines &&
          lines.slice(from - 1, to).map((spans, i) => {
            const n = from + i;
            const hit = n >= target.start && n <= target.end;
            return (
              <div
                key={n}
                ref={n === target.start ? startRef : undefined}
                className={`flex gap-4 px-4 ${hit ? `isolate ${flash ? "line-hit" : "line-hit-settled"}` : ""}`}
              >
                <span aria-hidden className="w-12 shrink-0 select-none border-r border-rule pr-3 text-right text-pencil">{n}</span>
                <span className="whitespace-pre">
                  {spans.length === 0 ? " " : spans.map((s, j) => (s.type ? <span key={j} className={`tok-${s.type}`}>{s.text}</span> : s.text))}
                </span>
              </div>
            );
          })}
      </div>
    </div>
  );
}
