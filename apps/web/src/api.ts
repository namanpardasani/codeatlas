export interface JobEvent {
  id?: string | number;
  status: "queued" | "running" | "done" | "failed";
  stage: string;
  progress: number;
  error?: string | null;
}

export interface FileRow {
  id: string;
  path: string;
  language: string | null;
  lines: number;
  is_test: boolean;
  parse_status: "ok" | "partial" | "failed" | "skipped" | null;
  symbol_count: number;
  import_count: number;
}

export interface SymbolRow {
  name: string;
  kind: string;
  start_line: number;
  end_line: number;
  params: string[];
  parent_name: string | null;
  is_exported: boolean;
  is_default_export: boolean;
  has_doc: boolean;
  signature: string;
}

export interface ImportRow {
  specifier: string;
  kind: string;
  names: string[];
  level: number;
  line: number;
  is_type_only: boolean;
  resolution: "internal" | "external" | "unresolved" | null;
  targets: string[];
  package: string | null;
  reason: string | null;
}

export interface FileDetail {
  file: {
    id: string;
    path: string;
    language: string | null;
    parse_status: FileRow["parse_status"];
    parse_error: string | null;
    exports: string[];
  };
  symbols: SymbolRow[];
  imports: ImportRow[];
}

export interface FileGraphNode {
  id: string;
  path: string;
  module: string;
  fan_in: number;
  fan_out: number;
  pagerank: number;
  cycle_idx: number | null;
}
export interface FolderGraphNode {
  id: string;
  files: number;
  files_in_cycles: number;
  pagerank: number | null;
  internal_edges: number;
}
export interface GraphEdge {
  source: string;
  target: string;
  kinds?: string[];
  count?: number;
}
export interface GraphResponse<N> {
  mode: "files" | "folders";
  truncated: boolean;
  total_nodes: number;
  nodes: N[];
  edges: GraphEdge[];
  cycles: { id: number; size: number; file_ids: string[] }[];
}
export interface FileGraphDetail {
  file: FileGraphNode & { repo_id: string };
  imports: { id: string; path: string; kinds: string[] }[];
  imported_by: { id: string; path: string; kinds: string[] }[];
  cycle: { id: string; path: string }[];
}

export interface HotspotReason {
  factor: string;
  points: number;
  severity: "high" | "medium" | "low";
  text: string;
}
export interface HotspotItem {
  id: string;
  path: string;
  language: string | null;
  lines: number;
  code_lines: number | null;
  comment_ratio: number | null;
  hotspot_score: number | null;
  hotspot_reasons: HotspotReason[];
  max_complexity: number | null;
  total_complexity: number | null;
  max_nesting: number | null;
  longest_function: number | null;
  function_count: number | null;
  churn: number | null;
  commits_total: number | null;
  authors: number | null;
  last_modified: string | null;
  fan_in: number | null;
  cycle_idx: number | null;
  cycle_size: number | null;
  has_test: boolean | null;
  test_file: string | null;
  dup_ratio: number | null;
}
export interface HotspotsResponse {
  scored: boolean;
  sort: string;
  dir: "asc" | "desc";
  total: number;
  history: { available: boolean; commits: number; window_days: number | null; truncated: boolean };
  items: HotspotItem[];
}
export interface FunctionMetric {
  name: string;
  kind: string;
  parent_name: string | null;
  start_line: number;
  end_line: number;
  length: number;
  complexity: number;
  max_nesting: number;
  param_count: number;
}
export interface FileMetrics {
  file: HotspotItem & {
    comment_lines: number | null;
    dup_lines: number | null;
    fan_out: number | null;
    pagerank: number | null;
    hotspot_detail: { contributions: Record<string, number>; normalized: Record<string, number> } | null;
  };
  functions: FunctionMetric[];
  duplicates: {
    group_id: number;
    start_line: number;
    end_line: number;
    lines: number;
    total_locations: number;
    others: { path: string; start_line: number; end_line: number }[] | null;
  }[];
  cochange: { path: string; count: number; coupling: number }[];
}

export type SearchMode = "vector" | "keyword" | "hybrid";
export type Chunking = "ast" | "fixed";
export interface SearchHit {
  chunk_id: number;
  path: string;
  language: string | null;
  kind: string;
  symbol: string | null;
  parent: string | null;
  start_line: number;
  end_line: number;
  header: string;
  content: string;
  score: number;
  vector_rank: number | null;
  vector_similarity: number | null;
  keyword_rank: number | null;
  keyword_score: number | null;
}
export interface SearchResponse {
  hits: SearchHit[];
  terms: string[];
  mode: SearchMode;
  chunking: Chunking;
  warnings: string[];
  timings_ms: Record<string, number>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  const body = await res.json();
  if (!res.ok) throw new Error(body.error ?? `Request failed (${res.status})`);
  return body as T;
}

export const submitRepo = (url: string) =>
  request<{ repoId: string; jobId: string }>("/repos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });

export const getFiles = (repoId: string) => request<FileRow[]>(`/repos/${repoId}/files`);
export const getFileDetail = (fileId: string) => request<FileDetail>(`/files/${fileId}/symbols`);

export function watchJob(jobId: string, onEvent: (e: JobEvent) => void): () => void {
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  es.onmessage = (m) => {
    const data = JSON.parse(m.data) as JobEvent;
    onEvent(data);
    if (data.status === "done" || data.status === "failed") es.close();
  };
  es.onerror = () => es.close();
  return () => es.close();
}

export const getFileGraphOverview = (repoId: string, limit = 300) =>
  request<GraphResponse<FileGraphNode>>(`/repos/${repoId}/graph?mode=files&limit=${limit}`);
export const getFolderGraph = (repoId: string) =>
  request<GraphResponse<FolderGraphNode>>(`/repos/${repoId}/graph?mode=folders`);
export const getFileGraph = (fileId: string) => request<FileGraphDetail>(`/files/${fileId}/graph`);

export const getHotspots = (repoId: string, sort: string, dir: "asc" | "desc") =>
  request<HotspotsResponse>(`/repos/${repoId}/hotspots?sort=${encodeURIComponent(sort)}&dir=${dir}&limit=100`);
export const getFileMetrics = (fileId: string) => request<FileMetrics>(`/files/${fileId}/metrics`);

export const searchRepo = (
  repoId: string,
  body: { query: string; mode: SearchMode; chunking: Chunking; language?: string; path_prefix?: string; limit?: number },
) =>
  request<SearchResponse>(`/repos/${repoId}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

// ---- Chat ------------------------------------------------------------------------------------------
export interface ChatCitation {
  label: string;
  chunk_id: number;
  path: string;
  start_line: number;
  end_line: number;
  symbol: string | null;
  kind: string | null;
  inferred?: boolean;   // matched automatically from identifiers, not cited by the model
}
export interface ChatChunkInfo {
  label: string;
  path: string;
  start_line: number;
  end_line: number;
  symbol: string | null;
  similarity: number | null;
}
export type ChatEvent =
  | { type: "session"; session_id: string }
  | { type: "status"; stage: string }
  | { type: "retrieval"; query: string; rewritten: boolean; evidence: { strong: boolean; best_similarity: number | null; reason: string }; chunks: ChatChunkInfo[]; warnings: string[] }
  | { type: "delta"; text: string }
  | {
      type: "final";
      status: "answered" | "partial" | "not_found";
      answer: string;
      citations: ChatCitation[];
      removed: string[];
      issues: string[];
      closest?: ChatChunkInfo[];
      model: string | null;
      llm_called: boolean;
    }
  | { type: "error"; kind: string; message: string; retry_after: number | null };

/** POST + parse the SSE response (EventSource cannot POST). Resolves when the stream ends. */
export async function streamChat(
  repoId: string,
  body: { question: string; session_id?: string },
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/repos/${repoId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error ?? `Chat failed (${res.status})`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const data = /^data: (.*)$/m.exec(block);
      if (data) onEvent(JSON.parse(data[1]!) as ChatEvent);
    }
  }
}

export const getRepoFile = (repoId: string, path: string) =>
  request<{ id: string; path: string; language: string | null; content: string }>(
    `/repos/${repoId}/file?path=${encodeURIComponent(path)}`,
  );

// ---- Re-analysis -------------------------------------------------------------------------------------
export interface AnalysisRun {
  id: string;
  status: string;
  mode: "full" | "incremental" | null;
  requested_mode: "auto" | "full";
  commit_sha: string | null;
  files_total: number | null;
  files_added: number | null;
  files_modified: number | null;
  files_deleted: number | null;
  files_renamed: number | null;
  files_reused: number | null;
  duration_ms: number | null;
  stage_timings: Record<string, number> | null;
  chunks_total: number | null;
  chunks_embedded: number | null;
  chunks_cached: number | null;
  created_at: string;
  finished_at: string | null;
}

export const reanalyze = (repoId: string, mode: "auto" | "full") =>
  request<{ repoId: string; jobId: string; alreadyRunning: boolean }>(`/repos/${repoId}/reanalyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
export const getAnalyses = (repoId: string) => request<AnalysisRun[]>(`/repos/${repoId}/analyses`);

// ---- Documentation -------------------------------------------------------------------------------------
export interface DocsStatus {
  docs_status: "running" | "ready" | "partial" | "failed" | null;
  docs_commit_sha: string | null;
  docs_model: string | null;
  docs_generated_at: string | null;
  targets: number;
  llm: number;
  extractive: number;
}
export interface DocNode {
  type: "folder" | "file";
  path: string;
  name: string;
  summary: string;
  source: "llm" | "extractive" | string;
  children?: DocNode[];
}
export interface DocPage {
  type: "repo" | "folder" | "file";
  path: string;
  markdown: string;
  source: string | null;
  model: string | null;
  commit: string | null;
  generated_at: string | null;
}
export const getDocsStatus = (repoId: string) => request<DocsStatus>(`/repos/${repoId}/docs/status`);
export const getDocsTree = (repoId: string) => request<{ name: string; summary: string; tree: DocNode[] }>(`/repos/${repoId}/docs/tree`);
export const getDocPage = (repoId: string, type: DocPage["type"], path: string) =>
  request<DocPage>(`/repos/${repoId}/docs/page?type=${type}&path=${encodeURIComponent(path)}`);
export const docsExportUrl = (repoId: string) => `/api/repos/${repoId}/docs/export.md`;
