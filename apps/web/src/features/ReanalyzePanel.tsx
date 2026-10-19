import { useEffect, useState } from "react";
import { getAnalyses, reanalyze, type AnalysisRun } from "../api";
import { Badge, Button, Panel, Table, type Column } from "../components/ui";

const secs = (ms: number | null) => (ms === null ? "–" : `${(ms / 1000).toFixed(1)} s`);
const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

/** "Re-index time reduced by X%": mean incremental run vs mean full run, from the recorded durations. */
export function speedup(runs: AnalysisRun[]): { full: number; incremental: number; reduction: number } | null {
  const done = runs.filter((r) => r.status === "done" && r.duration_ms !== null);
  const full = avg(done.filter((r) => r.mode === "full").map((r) => r.duration_ms!));
  const inc = avg(done.filter((r) => r.mode === "incremental").map((r) => r.duration_ms!));
  return full && inc ? { full, incremental: inc, reduction: Math.round((1 - inc / full) * 100) } : null;
}

export function ReanalyzePanel({
  repoId,
  busy,
  refreshKey,
  onStart,
}: {
  repoId: string;
  busy: boolean;
  refreshKey: number;
  onStart: (jobId: string) => void;
}) {
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAnalyses(repoId).then(setRuns).catch(() => setRuns([]));
  }, [repoId, refreshKey]);

  async function start(mode: "auto" | "full") {
    setError(null);
    try {
      const r = await reanalyze(repoId, mode);
      onStart(r.jobId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start");
    }
  }

  const columns: Column<AnalysisRun>[] = [
    { header: "Mode", render: (r) => <Badge tone={r.mode === "incremental" ? "success" : "neutral"}>{r.mode ?? r.status}</Badge> },
    { header: "Files", render: (r) => r.files_total ?? "–" },
    {
      header: "Changed",
      render: (r) =>
        r.mode === "incremental"
          ? `${(r.files_added ?? 0) + (r.files_modified ?? 0) + (r.files_renamed ?? 0)} (${r.files_added ?? 0}+ ${r.files_modified ?? 0}~ ${r.files_renamed ?? 0}→ ${r.files_deleted ?? 0}−)`
          : "all",
    },
    { header: "Reused", render: (r) => r.files_reused ?? "–" },
    { header: "Vectors computed", render: (r) => `${r.chunks_embedded ?? "–"}${r.chunks_cached ? ` (+${r.chunks_cached} cached)` : ""}` },
    { header: "Time", render: (r) => secs(r.duration_ms) },
  ];
  const s = speedup(runs);

  return (
    <Panel
      title="Re-analysis"
      actions={
        <span className="flex gap-gap">
          <Button disabled={busy} onClick={() => start("auto")}>Re-analyse (changes only)</Button>
          <Button variant="secondary" disabled={busy} onClick={() => start("full")}>Full re-analysis</Button>
        </span>
      }
    >
      {error && <p className="text-danger">{error}</p>}
      {s && (
        <p className="mb-gutter">
          <Badge tone="success">−{s.reduction}%</Badge>{" "}
          <span className="text-muted">
            incremental runs average {secs(s.incremental)} versus {secs(s.full)} for full runs.
          </span>
        </p>
      )}
      <Table columns={columns} rows={runs.filter((r) => r.mode)} rowKey={(r) => r.id} empty="No completed analyses yet." />
    </Panel>
  );
}
