import { Panel, Table, type Column } from "../components/ui";
import type { FileRow } from "../api";
import { StatusBadge } from "./StatusBadge";

const columns: Column<FileRow>[] = [
  { header: "Path", render: (f) => <span className="font-mono">{f.path}</span> },
  { header: "Language", render: (f) => f.language ?? "–" },
  { header: "Lines", render: (f) => f.lines },
  { header: "Parse", render: (f) => <StatusBadge status={f.parse_status} /> },
  { header: "Symbols", render: (f) => f.symbol_count },
  { header: "Imports", render: (f) => f.import_count },
];

export function FilesPanel({
  files,
  selectedId,
  onSelect,
}: {
  files: FileRow[];
  selectedId: string | null;
  onSelect: (f: FileRow) => void;
}) {
  return (
    <Panel title={`Files (${files.length})`}>
      <Table
        columns={columns}
        rows={files}
        rowKey={(f) => f.id}
        onRowClick={onSelect}
        isSelected={(f) => f.id === selectedId}
      />
    </Panel>
  );
}
