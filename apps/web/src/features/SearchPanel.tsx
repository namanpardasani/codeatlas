import { useState } from "react";
import { searchRepo, type Chunking, type SearchMode, type SearchResponse } from "../api";
import { Badge, Button, CodeBlock, Panel } from "../components/ui";

const LANGUAGES = ["", "typescript", "javascript", "python", "markdown"];
const select = "rounded-ui border border-border bg-surface px-gap py-gap";

export function SearchPanel({ repoId }: { repoId: string }) {
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
    <Panel title="Search the code">
      <form onSubmit={run} className="flex flex-col gap-gap">
        <div className="flex gap-gap">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. where are requests retried?  or  prepare_body"
            className="flex-1 rounded-ui border border-border bg-surface px-gap py-gap"
          />
          <Button disabled={busy || !query.trim()}>{busy ? "Searching…" : "Search"}</Button>
        </div>
        <div className="flex flex-wrap gap-gap text-muted">
          <label className="flex items-center gap-gap">
            Mode
            <select className={select} value={mode} onChange={(e) => setMode(e.target.value as SearchMode)}>
              <option value="hybrid">hybrid (vector + keyword)</option>
              <option value="vector">vector only</option>
              <option value="keyword">keyword only</option>
            </select>
          </label>
          <label className="flex items-center gap-gap">
            Chunking
            <select className={select} value={chunking} onChange={(e) => setChunking(e.target.value as Chunking)}>
              <option value="ast">AST-aware</option>
              <option value="fixed">fixed-size baseline</option>
            </select>
          </label>
          <label className="flex items-center gap-gap">
            Language
            <select className={select} value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>{l || "any"}</option>
              ))}
            </select>
          </label>
        </div>
      </form>

      {error && <p className="mt-gutter text-danger">{error}</p>}
      {result && (
        <div className="mt-gutter flex flex-col gap-gutter">
          {result.warnings.map((w) => (
            <p key={w}><Badge tone="warning">note</Badge> <span className="text-muted">{w}</span></p>
          ))}
          <p className="text-muted">
            {result.hits.length} result(s) · {result.mode} · {result.chunking === "ast" ? "AST chunks" : "fixed chunks"}
            {Object.keys(result.timings_ms).length > 0 &&
              ` · ${Object.entries(result.timings_ms).map(([k, v]) => `${k} ${v}ms`).join(", ")}`}
          </p>
          {result.hits.map((h) => (
            <article key={h.chunk_id} className="flex flex-col gap-gap">
              <div className="flex flex-wrap items-center gap-gap">
                <span className="font-mono font-semibold">{h.path}:{h.start_line}–{h.end_line}</span>
                <Badge>{h.kind}</Badge>
                {h.symbol && <Badge tone="info">{h.symbol}</Badge>}
                <span className="text-small text-muted">
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
    </Panel>
  );
}
