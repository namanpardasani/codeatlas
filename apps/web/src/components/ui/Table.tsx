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

/**
 * A ledger: mono caps header over a heavy ink rule, thin rules between rows, a highlighter wash on the selected row
 * with an ink mark in the margin. Data-driven so pages never hand-style cells. Clickable rows are keyboard operable.
 */
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
  if (rows.length === 0) return <p className="text-wonk text-pencil">{empty}</p>;
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
          <tr className="border-b-2 border-ink">
            {columns.map((c) => (
              <th key={c.header} className={`mono-label px-3 py-2 font-medium ${c.className ?? ""}`} aria-sort={sort && sort.key === c.sortKey ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}>
                {c.sortKey && onSort ? (
                  <button className={`uppercase tracking-[inherit] hover:text-ink ${sort?.key === c.sortKey ? "text-ink" : ""}`} onClick={() => onSort(c.sortKey!)}>
                    {c.header}
                    {sort?.key === c.sortKey && <span aria-hidden>{sort.dir === "asc" ? " ↑" : " ↓"}</span>}
                  </button>
                ) : (
                  c.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const sel = isSelected?.(row) ?? false;
            return (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={onRowClick ? key(row) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                aria-selected={onRowClick ? sel : undefined}
                className={`border-b border-rule transition-colors duration-100 ${onRowClick ? "cursor-pointer hover:bg-paper-2" : ""} ${sel ? "bg-hl-soft shadow-[inset_3px_0_0_var(--ink)] hover:bg-hl-soft" : ""}`}
              >
                {columns.map((c) => (
                  <td key={c.header} className={`px-3 py-2.5 align-middle text-ink-2 ${c.className ?? ""}`}>
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
