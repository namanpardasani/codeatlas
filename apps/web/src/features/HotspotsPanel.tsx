import { useEffect, useState } from "react";
import { getHotspots, type HotspotItem, type HotspotsResponse } from "../api";
import { Badge, Panel, ScoreBar, Table, type Column, type SortState, type Tone } from "../components/ui";

const severityTone: Record<string, Tone> = { high: "amber", medium: "amber", low: "neutral" };
const FACTOR_LABEL: Record<string, string> = {
  complexity: "complex", churn: "churn", cycle: "cycle", fan_in: "fan-in", no_test: "no test", duplication: "duplicated",
};
const n = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v);

export function HotspotsPanel({
  repoId,
  selectedId,
  onSelect,
}: {
  repoId: string;
  selectedId: string | null;
  onSelect: (fileId: string) => void;
}) {
  const [sort, setSort] = useState<SortState>({ key: "score", dir: "desc" });
  const [data, setData] = useState<HotspotsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    getHotspots(repoId, sort.key, sort.dir)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load hotspots"));
  }, [repoId, sort]);

  const onSort = (key: string) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === "desc" ? "asc" : "desc" } : { key, dir: key === "path" ? "asc" : "desc" }));

  const columns: Column<HotspotItem>[] = [
    { header: "File", sortKey: "path", render: (f) => <span className="font-mono">{f.path}</span> },
    { header: "Score", sortKey: "score", render: (f) => (f.hotspot_score === null ? "–" : <ScoreBar value={f.hotspot_score} />) },
    { header: "Complexity", sortKey: "complexity", render: (f) => `${n(f.max_complexity)} / ${n(f.total_complexity)}` },
    { header: "Churn", sortKey: "churn", render: (f) => n(f.churn) },
    { header: "Authors", sortKey: "authors", render: (f) => n(f.authors) },
    { header: "Fan-in", sortKey: "fan_in", render: (f) => n(f.fan_in) },
    { header: "Dup", sortKey: "duplication", render: (f) => (f.dup_ratio ? `${Math.round(f.dup_ratio * 100)}%` : "–") },
    {
      header: "Signals",
      render: (f) => (
        <span className="flex flex-wrap gap-gap">
          {f.hotspot_reasons.length > 0
            ? f.hotspot_reasons.map((r) => (
                <span key={r.factor} title={r.text}>
                  <Badge tone={severityTone[r.severity]}>{FACTOR_LABEL[r.factor] ?? r.factor}</Badge>
                </span>
              ))
            : <>
                {f.cycle_idx !== null && <Badge tone="warning">cycle ({f.cycle_size})</Badge>}
                {f.has_test === false && <Badge>no test</Badge>}
              </>}
        </span>
      ),
    },
  ];

  const h = data?.history;
  return (
    <Panel title="Hotspots">
      {error && <p className="text-danger">{error}</p>}
      {data && (
        <div className="mb-gutter flex flex-col gap-gap text-muted">
          {!data.scored && (
            <p>
              <Badge tone="warning">no scoring formula yet</Badge> Score and reasons stay empty until the
              hotspot formula is implemented; the table is ordered by raw complexity meanwhile.
            </p>
          )}
          <p>
            {h?.available
              ? `Git history: ${h.commits} commits analysed, churn counts commits in the last ${h.window_days} days before the newest commit${h.truncated ? " (history was capped, so the window is shorter)" : ""}.`
              : "No usable git history: churn and authors are unknown."}
          </p>
        </div>
      )}
      <Table
        columns={columns}
        rows={data?.items ?? []}
        rowKey={(f) => f.id}
        sort={sort}
        onSort={onSort}
        onRowClick={(f) => onSelect(f.id)}
        isSelected={(f) => f.id === selectedId}
        empty="No analysed source files."
      />
    </Panel>
  );
}
