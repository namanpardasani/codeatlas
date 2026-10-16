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
