import { useEffect, useMemo, useRef, useState } from "react";
import type { FileRow } from "../api";
import { Dialog } from "./Dialog";

/** Jump to file (⌘K / Ctrl+K): filter by path, arrow keys + Enter, Esc closes. */
export function JumpToFile({ open, files, onPick, onClose }: { open: boolean; files: FileRow[]; onPick: (f: FileRow) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement | null>(null);
  const hits = useMemo(() => {
    const t = q.trim().toLowerCase();
    const list = t ? files.filter((f) => f.path.toLowerCase().includes(t)) : files;
    return list.slice(0, 12);
  }, [q, files]);
  useEffect(() => {
    if (open) {
      setQ("");
      setI(0);
      setTimeout(() => input.current?.focus(), 30);
    }
  }, [open]);
  useEffect(() => {
    setI(0);
  }, [q]);
  return (
    <Dialog open={open} title="Jump to file" onClose={onClose}>
      <label htmlFor="jump" className="sr-only">Search files by path</label>
      <input
        id="jump"
        ref={input}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Jump to file…"
        autoComplete="off"
        spellCheck={false}
        role="combobox"
        aria-expanded
        aria-controls="jump-list"
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") (e.preventDefault(), setI((v) => Math.min(hits.length - 1, v + 1)));
          if (e.key === "ArrowUp") (e.preventDefault(), setI((v) => Math.max(0, v - 1)));
          if (e.key === "Enter" && hits[i]) onPick(hits[i]!);
        }}
        className="w-full rounded-shell border border-border-strong bg-bg px-4 py-3 font-mono text-body text-text outline-none placeholder:text-dim focus-visible:border-cyan"
      />
      <ul id="jump-list" role="listbox" className="mt-3 max-h-80 overflow-y-auto">
        {hits.map((f, idx) => (
          <li key={f.id} role="option" aria-selected={idx === i}>
            <button
              onClick={() => onPick(f)}
              onMouseEnter={() => setI(idx)}
              className={`flex w-full items-center justify-between rounded-ui px-3 py-2 text-left font-mono text-small ${idx === i ? "bg-cyan-bg text-text" : "text-text-3"}`}
            >
              <span className="truncate">{f.path}</span>
              <span className="ml-3 shrink-0 text-dim">{f.lines} lines</span>
            </button>
          </li>
        ))}
        {hits.length === 0 && <li className="px-3 py-2 text-small text-muted">No file matches “{q}”.</li>}
      </ul>
    </Dialog>
  );
}
