import { Fragment } from "react";

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Monospace snippet on recessed paper with a ruled line-number gutter; `highlight` terms get a highlighter stroke. */
export function CodeBlock({ code, startLine = 1, highlight = [], maxLines = 14 }: { code: string; startLine?: number; highlight?: string[]; maxLines?: number }) {
  const lines = code.split("\n");
  const shown = lines.slice(0, maxLines);
  const re = highlight.length ? new RegExp(`(${highlight.map(escape).join("|")})`, "gi") : null;
  const renderLine = (line: string) =>
    re ? line.split(re).map((part, i) => (i % 2 === 1 ? <mark key={i} className="marker font-semibold">{part}</mark> : <Fragment key={i}>{part}</Fragment>)) : line;
  return (
    <pre className="overflow-x-auto rounded-sm bg-paper-2 py-3 font-mono text-[12.5px] leading-relaxed text-ink-2">
      {shown.map((line, i) => (
        <div key={i} className="flex">
          <span className="w-12 shrink-0 select-none border-r border-rule pr-3 text-right text-pencil">{startLine + i}</span>
          <span className="whitespace-pre pl-4 pr-3">{renderLine(line) || " "}</span>
        </div>
      ))}
      {lines.length > maxLines && <div className="pl-16 pt-1 text-pencil">… {lines.length - maxLines} more lines</div>}
    </pre>
  );
}
