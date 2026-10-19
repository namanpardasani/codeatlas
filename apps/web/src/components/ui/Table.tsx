import type { ReactNode } from "react";

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
  /** Makes the header clickable; the value is what onSort receives (e.g. the API sort key). */
  sortKey?: string;
}

export interface SortState {
  key: string;
  dir: "asc" | "desc";
}

/** Data-driven table so pages never hand-style cells. */
export function Table<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  isSelected,
  sort,
  onSort,
  empty = "Nothing to show.",
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  isSelected?: (row: T) => boolean;
  sort?: SortState;
  onSort?: (key: string) => void;
  empty?: string;
}) {
  if (rows.length === 0) return <p className="text-muted">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-border text-small text-muted">
            {columns.map((c) => (
              <th key={c.header} className={`px-gap py-gap font-medium ${c.className ?? ""}`}>
                {c.sortKey && onSort ? (
                  <button className="font-medium" onClick={() => onSort(c.sortKey!)}>
                    {c.header}
                    {sort?.key === c.sortKey && (sort.dir === "asc" ? " ▲" : " ▼")}
                  </button>
                ) : (
                  c.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={`border-b border-border ${onRowClick ? "cursor-pointer" : ""} ${
                isSelected?.(row) ? "bg-subtle" : ""
              }`}
            >
              {columns.map((c) => (
                <td key={c.header} className={`px-gap py-gap align-top ${c.className ?? ""}`}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
