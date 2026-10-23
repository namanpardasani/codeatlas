import { useEffect, useState } from "react";
import { getFileMetrics, type FileMetrics, type FunctionMetric } from "../api";
import { Badge, Panel, Stat, Table, type Column, type Tone } from "../components/ui";

const tone: Record<string, Tone> = { high: "danger", medium: "warning", low: "neutral" };
const dash = (v: unknown) => (v === null || v === undefined ? "–" : String(v));

const fnColumns: Column<FunctionMetric>[] = [
  { header: "Function", render: (f) => <span className="font-mono">{f.parent_name ? `${f.parent_name}.` : ""}{f.name}</span> },
  { header: "Complexity", render: (f) => f.complexity },
  { header: "Nesting", render: (f) => f.max_nesting },
  { header: "Length", render: (f) => `${f.length} lines` },
  { header: "Params", render: (f) => f.param_count },
  { header: "Lines", render: (f) => `${f.start_line}–${f.end_line}` },
];

export function FileMetricsPanel({ fileId }: { fileId: string }) {
  const [m, setM] = useState<FileMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setM(null);
    setError(null);
    getFileMetrics(fileId).then(setM).catch((e) => setError(e instanceof Error ? e.message : "Could not load metrics"));
  }, [fileId]);

  if (error) return <Panel title="Metrics"><p className="text-signal-ink">{error}</p></Panel>;
  if (!m) return null;
  const f = m.file;
  const pct = (v: number | null) => (v === null ? "–" : `${Math.round(v * 100)}%`);
  return (
    <Panel title={`Metrics: ${f.path}`} actions={f.hotspot_score !== null ? <Badge tone={f.hotspot_score > 70 ? "danger" : f.hotspot_score > 40 ? "warning" : "neutral"}>score {f.hotspot_score.toFixed(1)}</Badge> : undefined}>
      {f.hotspot_reasons.length > 0 && (
        <div className="mb-4">
          <h3 className="mb-2 font-display text-[17px] font-semibold">Why this file is a hotspot</h3>
          <ul className="flex flex-col gap-2">
            {f.hotspot_reasons.map((r) => (
              <li key={r.factor} className="flex items-start gap-2">
                <Badge tone={tone[r.severity]}>{r.severity}</Badge>
                <span>{r.text} <span className="text-pencil">({r.points.toFixed(1)} pts)</span></span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mb-8 grid grid-cols-2 gap-x-4 gap-y-5 md:grid-cols-4">
        <Stat label="Lines" value={`${dash(f.lines)} (${dash(f.code_lines)} code)`} />
        <Stat label="Comment ratio" value={pct(f.comment_ratio)} hint="comment-only lines / non-blank lines" />
        <Stat label="Complexity max / total" value={`${dash(f.max_complexity)} / ${dash(f.total_complexity)}`} hint="cyclomatic" />
        <Stat label="Max nesting" value={dash(f.max_nesting)} />
        <Stat label="Functions" value={dash(f.function_count)} />
        <Stat label="Longest function" value={f.longest_function === null ? "–" : `${f.longest_function} lines`} />
        <Stat label="Churn (window)" value={dash(f.churn)} hint="commits touching the file in the analysis window" />
        <Stat label="Commits (all fetched)" value={dash(f.commits_total)} />
        <Stat label="Authors" value={dash(f.authors)} />
        <Stat label="Last modified" value={f.last_modified ? f.last_modified.slice(0, 10) : "–"} />
        <Stat label="Duplicated" value={pct(f.dup_ratio)} hint="share of lines inside duplicated blocks" />
        <Stat label="Test file" value={f.has_test ? <span className="font-mono text-small">{f.test_file}</span> : f.has_test === false ? "none found" : "–"} />
      </div>

      <h3 className="mb-2 font-display text-[17px] font-semibold">Functions by complexity</h3>
      <Table columns={fnColumns} rows={m.functions} rowKey={(x) => `${x.parent_name}.${x.name}.${x.start_line}`} empty="No functions." />

      <h3 className="mb-2 mt-8 font-display text-[17px] font-semibold">Duplicated blocks ({m.duplicates.length})</h3>
      {m.duplicates.length === 0 ? (
        <p className="text-pencil">None found.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {m.duplicates.map((d) => (
            <li key={`${d.group_id}-${d.start_line}`}>
              <span className="font-mono">lines {d.start_line}–{d.end_line}</span> also appear in{" "}
              {(d.others ?? []).map((o) => `${o.path}:${o.start_line}–${o.end_line}`).join(", ") || "this file"}
            </li>
          ))}
        </ul>
      )}

      <h3 className="mb-2 mt-8 font-display text-[17px] font-semibold">Changes together with</h3>
      {m.cochange.length === 0 ? (
        <p className="text-pencil">No file shares 2+ commits with this one.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {m.cochange.map((c) => (
            <li key={c.path}>
              <span className="font-mono">{c.path}</span>{" "}
              <span className="text-pencil">{c.count} shared commits, coupling {Math.round(c.coupling * 100)}%</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
