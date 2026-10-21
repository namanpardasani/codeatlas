import type { KeyboardEvent, ReactNode } from "react";

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

/** Data-driven table so pages never hand-style cells. Clickable rows are keyboard operable (Enter / Space). */
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
  const key = (row: T) => (e: KeyboardEvent) => {
    if (onRowClick && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      onRowClick(row);
    }
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-line text-[12px] text-muted">
            {columns.map((c) => (
              <th key={c.header} className={`px-3 py-2 font-medium ${c.className ?? ""}`} aria-sort={sort && sort.key === c.sortKey ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}>
                {c.sortKey && onSort ? (
                  <button className="font-medium hover:text-text" onClick={() => onSort(c.sortKey!)}>
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
              onKeyDown={onRowClick ? key(row) : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              className={`border-b border-line transition-colors duration-150 hover:bg-surface-2 ${onRowClick ? "cursor-pointer" : ""} ${
                isSelected?.(row) ? "bg-surface-2" : ""
              }`}
            >
              {columns.map((c) => (
                <td key={c.header} className={`px-3 py-3 align-middle ${c.className ?? ""}`}>
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
