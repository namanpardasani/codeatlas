import { useEffect, useRef, useState } from "react";
import { getRepoFile } from "../api";
import { Button, Panel } from "../components/ui";

export interface ViewerTarget {
  path: string;
  start: number;
  end: number;
}

const MAX_LINES = 1500;

/** Shows an indexed file with line numbers and the cited range highlighted; scrolls to it. */
export function CodeViewer({ repoId, target, onClose }: { repoId: string; target: ViewerTarget; onClose: () => void }) {
  const [lines, setLines] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const startRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setLines(null);
    setError(null);
    getRepoFile(repoId, target.path)
      .then((f) => setLines(f.content.replace(/\n$/, "").split("\n")))
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load file"));
  }, [repoId, target.path]);

  useEffect(() => {
    startRef.current?.scrollIntoView({ block: "center" });
  }, [lines, target.start]);

  // very long files: show a window around the highlighted range
  const from = lines && lines.length > MAX_LINES ? Math.max(1, target.start - 200) : 1;
  const to = lines ? (lines.length > MAX_LINES ? Math.min(lines.length, from + MAX_LINES - 1) : lines.length) : 0;

  return (
    <Panel
      title={`${target.path}  (lines ${target.start}–${target.end})`}
      actions={<Button variant="secondary" onClick={onClose}>Close</Button>}
    >
      {error && <p className="text-danger">{error}</p>}
      {!lines && !error && <p className="text-muted">Loading…</p>}
      {lines && (
        <pre className="max-h-canvas overflow-auto rounded-ui border border-border bg-bg py-gap font-mono text-small">
          {lines.slice(from - 1, to).map((text, i) => {
            const n = from + i;
            const inRange = n >= target.start && n <= target.end;
            return (
              <div
                key={n}
                ref={n === target.start ? startRef : undefined}
                className={`flex gap-gutter px-gap ${inRange ? "bg-subtle font-semibold" : ""}`}
              >
                <span className="w-12 shrink-0 select-none text-right text-muted">{n}</span>
                <span className="whitespace-pre">{text || " "}</span>
              </div>
            );
          })}
        </pre>
      )}
    </Panel>
  );
}
