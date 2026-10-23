import { useState } from "react";
import { HotspotsPanel } from "../features/HotspotsPanel";
import { FileMetricsPanel } from "../features/FileMetricsPanel";
import { useRepo } from "../hooks/RepoData";
import { PageHead } from "../components/ui";

export default function HotspotsPage() {
  const { repoId } = useRepo();
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-10">
      <PageHead sheet="Sheet 04 · Hotspots" title="Where the ground is soft">
        Every source file, ranked by how risky it is to change: complexity, how often it changes, how many files lean on it,
        duplication and missing tests. Click a row for the full breakdown.
      </PageHead>
      <HotspotsPanel repoId={repoId} selectedId={selected} onSelect={setSelected} />
      {selected && <FileMetricsPanel fileId={selected} />}
    </div>
  );
}
