import { useState } from "react";
import { searchRepo, type Chunking, type SearchMode, type SearchResponse } from "../api";
import { Badge, Button, CodeBlock } from "../components/ui";
import type { ViewerTarget } from "./CodeViewer";

const LANGUAGES = ["", "typescript", "javascript", "python", "markdown"];
const select = "min-h-9 rounded-sm border border-rule-strong bg-paper px-2 text-small text-ink";

export function SearchPanel({ repoId, onOpen }: { repoId: string; onOpen?: (t: ViewerTarget) => void }) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [chunking, setChunking] = useState<Chunking>("ast");
  const [language, setLanguage] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await searchRepo(repoId, { query, mode, chunking, language: language || undefined }));
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <form onSubmit={run} className="flex flex-col gap-2">
        <div className="flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. where are requests retried?  or  prepare_body"
            className="min-h-10 flex-1 border-0 border-b-2 border-ink bg-transparent px-1 text-body text-ink outline-none placeholder:text-pencil focus-visible:border-signal focus-visible:outline-none"
          />
          <Button type="submit" disabled={busy || !query.trim()}>{busy ? "Searching…" : "Search"}</Button>
        </div>
        <div className="mt-2 flex flex-wrap gap-3 text-small text-pencil">
          <label className="flex items-center gap-2">
            Mode
            <select className={select} value={mode} onChange={(e) => setMode(e.target.value as SearchMode)}>
              <option value="hybrid">hybrid (vector + keyword)</option>
              <option value="vector">vector only</option>
              <option value="keyword">keyword only</option>
            </select>
          </label>
          <label className="flex items-center gap-2">
            Chunking
            <select className={select} value={chunking} onChange={(e) => setChunking(e.target.value as Chunking)}>
              <option value="ast">AST-aware</option>
              <option value="fixed">fixed-size baseline</option>
            </select>
          </label>
          <label className="flex items-center gap-2">
            Language
            <select className={select} value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>{l || "any"}</option>
              ))}
            </select>
          </label>
        </div>
      </form>

      {error && <p className="mt-4 text-signal-ink">{error}</p>}
      {result && (
        <div className="mt-4 flex flex-col gap-4">
          {result.warnings.map((w) => (
            <p key={w}><Badge tone="warning">note</Badge> <span className="text-pencil">{w}</span></p>
          ))}
          <p className="text-pencil">
            {result.hits.length} result(s) · {result.mode} · {result.chunking === "ast" ? "AST chunks" : "fixed chunks"}
            {Object.keys(result.timings_ms).length > 0 &&
              ` · ${Object.entries(result.timings_ms).map(([k, v]) => `${k} ${v}ms`).join(", ")}`}
          </p>
          {result.hits.map((h) => (
            <article key={h.chunk_id} className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <button className="font-mono font-semibold text-ink underline decoration-signal underline-offset-4 hover:text-signal-ink"
                        onClick={() => onOpen?.({ path: h.path, start: h.start_line, end: h.end_line })}>
                  {h.path}:{h.start_line}–{h.end_line}
                </button>
                <Badge>{h.kind}</Badge>
                {h.symbol && <Badge tone="info">{h.symbol}</Badge>}
                <span className="text-small text-pencil">
                  score {h.score.toFixed(4)}
                  {h.vector_rank !== null && ` · vector #${h.vector_rank} (${h.vector_similarity?.toFixed(2)})`}
                  {h.keyword_rank !== null && ` · keyword #${h.keyword_rank}`}
                </span>
              </div>
              <CodeBlock code={h.content} startLine={h.start_line} highlight={result.terms} />
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
