import { DataTable, type Column } from "./settings/DataTable";
import type { AuditLogEntry } from "../lib/types";

// Shared by the CSV export in HistoryPage, so the on-screen "Detalhes"
// column and the exported file describe a change the same way.
//
// `details` is a free-form JSON column and only *edit* events use the
// {field: {before, after}} shape. Others record plain values — the scheduler
// writes scheduled_publish_all_rejected, publish_requested carries counts.
// Assuming the diff shape here threw on the first such row and took the whole
// history table down with it, so each value is now narrowed before use.
export function formatAuditDetails(details: AuditLogEntry["details"]): string {
  if (!details) return "";
  return Object.entries(details)
    .map(([field, value]) => {
      if (value && typeof value === "object" && "before" in value && "after" in value) {
        const change = value as { before: unknown; after: unknown };
        return `${field}: ${String(change.before)} → ${String(change.after)}`;
      }
      return `${field}: ${value === null ? "—" : String(value)}`;
    })
    .join("; ");
}

const COLUMNS: Array<Column<AuditLogEntry>> = [
  {
    key: "created_at",
    header: "Data",
    width: "11rem",
    render: (entry) => (
      <span className="whitespace-nowrap font-mono text-[12px]">
        {new Date(entry.created_at).toLocaleString()}
      </span>
    ),
  },
  {
    key: "action",
    header: "Ação",
    width: "12rem",
    render: (entry) => <span className="font-medium">{entry.action}</span>,
  },
  {
    key: "entity",
    header: "Entidade",
    width: "13rem",
    render: (entry) => (
      <span className="whitespace-nowrap">
        {entry.entity_type} <span className="text-[var(--text)]">#{entry.entity_id}</span>
      </span>
    ),
  },
  { key: "actor", header: "Ator", width: "10rem", render: (entry) => entry.actor },
  {
    key: "details",
    header: "Detalhes",
    // Events recorded before the 5c history feature (approve/reject from 5a,
    // all of 5b's config CRUD) have details === null.
    render: (entry) => (
      <span className="text-[var(--text)]">{formatAuditDetails(entry.details)}</span>
    ),
  },
];

/** The audit feed, as a table.
 *
 * Takes the query's own loading/error state rather than only its rows: both
 * callers (the Histórico page and a piece's detail) used to spell those two
 * states out as bare "Carregando..." paragraphs above the table, which made
 * the list collapse and shove the page around on every refetch. DataTable
 * owns all three states, so they now render the same here as everywhere else.
 */
export function AuditLogList({
  entries,
  isLoading,
  isError,
  error,
  emptyHint,
}: {
  entries: AuditLogEntry[] | undefined;
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
  emptyHint?: string;
}) {
  return (
    <DataTable
      columns={COLUMNS}
      rows={entries}
      rowKey={(entry) => entry.id}
      isLoading={isLoading}
      isError={isError}
      error={error}
      emptyTitle="Nenhum evento registrado"
      emptyHint={emptyHint}
    />
  );
}
