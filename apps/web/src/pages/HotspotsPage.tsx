import { useState } from "react";
import { HotspotsPanel } from "../features/HotspotsPanel";
import { FileMetricsPanel } from "../features/FileMetricsPanel";
import { MonoLabel } from "../components/ui";
import { useRepo } from "../hooks/RepoData";

export default function HotspotsPage() {
  const { repoId } = useRepo();
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-4">
      <MonoLabel>PLATE 03 ——— HOTSPOTS</MonoLabel>
      <HotspotsPanel repoId={repoId} selectedId={selected} onSelect={setSelected} />
      {selected && <FileMetricsPanel fileId={selected} />}
    </div>
  );
}
