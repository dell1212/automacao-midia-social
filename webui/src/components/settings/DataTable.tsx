import type { ReactNode } from "react";
import { Card } from "../ui/Card";
import { EmptyState, SkeletonRows } from "../ui/Feedback";
import { cn } from "../ui/cn";

export interface Column<T> {
  key: string;
  header: string;
  align?: "left" | "right";
  /** Any CSS width. Left undefined the column takes its share of the rest. */
  width?: string;
  render: (row: T) => ReactNode;
}

/** The list half of every settings screen.
 *
 * Loading, error and empty live in here rather than in each screen: the seven
 * screens each spelled those three states out by hand, in slightly different
 * words, and the empty case was a blank page with no explanation at all.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  isLoading,
  isError,
  emptyTitle,
  emptyHint,
}: {
  columns: Array<Column<T>>;
  rows: T[] | undefined;
  rowKey: (row: T) => string | number;
  isLoading?: boolean;
  isError?: boolean;
  emptyTitle: string;
  emptyHint?: string;
}) {
  if (isLoading) {
    return (
      <Card className="p-4">
        <SkeletonRows rows={5} />
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <EmptyState
          title="Não foi possível carregar"
          hint="Verifique a conexão com o servidor e tente novamente."
        />
      </Card>
    );
  }

  if (!rows || rows.length === 0) {
    return (
      <Card>
        <EmptyState title={emptyTitle} hint={emptyHint} />
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      {/* The wrapper scrolls, not the page: a five-column table must not make
          the whole layout scroll sideways on a narrow viewport. */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px] m-0">
          <thead>
            <tr className="border-b border-[var(--border)]">
              {columns.map((column) => (
                <th
                  key={column.key}
                  style={column.width ? { width: column.width } : undefined}
                  className={cn(
                    "px-4 py-2.5 font-mono text-[10px] font-medium uppercase tracking-[0.12em]",
                    "text-[var(--text)] whitespace-nowrap",
                    column.align === "right" ? "text-right" : "text-left",
                  )}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                className="border-b border-[var(--border)] hover:bg-[var(--code-bg)] transition-colors [&:last-child>td]:border-b-0"
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      "px-4 py-2.5 text-[var(--text-h)] align-middle",
                      column.align === "right" ? "text-right" : "text-left",
                    )}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
