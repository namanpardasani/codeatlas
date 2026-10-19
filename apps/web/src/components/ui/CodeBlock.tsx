import { Fragment } from "react";

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Monospace snippet with a line-number gutter; `highlight` terms are wrapped in <mark> (case-insensitive). */
export function CodeBlock({ code, startLine = 1, highlight = [], maxLines = 14 }: {
  code: string;
  startLine?: number;
  highlight?: string[];
  maxLines?: number;
}) {
  const lines = code.split("\n");
  const shown = lines.slice(0, maxLines);
  const re = highlight.length ? new RegExp(`(${highlight.map(escape).join("|")})`, "gi") : null;
  const renderLine = (line: string) =>
    re
      ? line.split(re).map((part, i) =>
          i % 2 === 1 ? <mark key={i} className="rounded-ui bg-subtle font-semibold text-fg">{part}</mark> : <Fragment key={i}>{part}</Fragment>)
      : line;
  return (
    <pre className="overflow-x-auto rounded-ui border border-border bg-bg p-gap font-mono text-small">
      {shown.map((line, i) => (
        <div key={i} className="flex gap-gutter">
          <span className="w-10 shrink-0 select-none text-right text-muted">{startLine + i}</span>
          <span className="whitespace-pre">{renderLine(line) || " "}</span>
        </div>
      ))}
      {lines.length > maxLines && <div className="text-muted">… {lines.length - maxLines} more lines</div>}
    </pre>
  );
}
