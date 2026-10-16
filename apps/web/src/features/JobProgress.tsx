import { Badge, Panel, ProgressBar } from "../components/ui";
import type { JobEvent } from "../api";

export function JobProgress({ job }: { job: JobEvent }) {
  const failed = job.status === "failed";
  const tone = failed ? "danger" : job.status === "done" ? "success" : "info";
  return (
    <Panel title="Analysis" actions={<Badge tone={tone}>{job.status}</Badge>}>
      <div className="mb-gap flex justify-between text-muted">
        <span className="capitalize">{job.stage}</span>
        <span>{job.progress}%</span>
      </div>
      <ProgressBar value={job.progress} failed={failed} />
      {failed && <p className="mt-gap text-danger">{job.error ?? "Analysis failed"}</p>}
    </Panel>
  );
}
