import { Badge, type Tone } from "../components/ui";
import type { FileRow } from "../api";

const tones: Record<string, Tone> = { ok: "success", partial: "warning", failed: "danger", skipped: "neutral" };

export function StatusBadge({ status }: { status: FileRow["parse_status"] }) {
  if (!status) return <span className="text-muted">–</span>;
  return <Badge tone={tones[status] ?? "neutral"}>{status}</Badge>;
}
