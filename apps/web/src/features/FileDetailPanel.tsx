import { Badge, Panel, Table, type Column } from "../components/ui";
import type { FileDetail, ImportRow, SymbolRow } from "../api";
import { StatusBadge } from "./StatusBadge";

const symbolColumns: Column<SymbolRow>[] = [
  {
    header: "Name",
    render: (s) => (
      <span className="font-mono">
        {s.parent_name ? `${s.parent_name}.` : ""}
        {s.name}
      </span>
    ),
  },
  { header: "Kind", render: (s) => <Badge>{s.kind}</Badge> },
  { header: "Lines", render: (s) => `${s.start_line}–${s.end_line}` },
  { header: "Params", render: (s) => <span className="font-mono">{s.params.join(", ") || "–"}</span> },
  {
    header: "Flags",
    render: (s) => (
      <span className="flex gap-gap">
        {s.is_exported && <Badge tone="info">{s.is_default_export ? "default" : "export"}</Badge>}
        {s.has_doc && <Badge tone="success">doc</Badge>}
      </span>
    ),
  },
];

const importColumns: Column<ImportRow>[] = [
  {
    header: "Specifier",
    render: (i) => (
      <span className="font-mono">
        {".".repeat(i.level)}
        {i.specifier}
      </span>
    ),
  },
  { header: "Kind", render: (i) => <Badge>{i.kind}</Badge> },
  { header: "Names", render: (i) => <span className="font-mono">{i.names.join(", ") || "–"}</span> },
  { header: "Line", render: (i) => i.line },
];

export function FileDetailPanel({ detail }: { detail: FileDetail }) {
  const { file, symbols, imports } = detail;
  return (
    <Panel title={file.path} actions={<StatusBadge status={file.parse_status} />}>
      {file.parse_error && <p className="mb-gutter text-warning">{file.parse_error}</p>}
      <h3 className="mb-gap font-semibold">Symbols ({symbols.length})</h3>
      <Table columns={symbolColumns} rows={symbols} rowKey={(s) => `${s.parent_name}.${s.name}.${s.start_line}`}
             empty="No symbols found." />
      <h3 className="mb-gap mt-section font-semibold">Imports ({imports.length})</h3>
      <Table columns={importColumns} rows={imports} rowKey={(i) => `${i.line}.${i.kind}.${i.specifier}`}
             empty="No imports found." />
      {file.exports.length > 0 && (
        <>
          <h3 className="mb-gap mt-section font-semibold">Exports</h3>
          <p className="font-mono">{file.exports.join(", ")}</p>
        </>
      )}
    </Panel>
  );
}
