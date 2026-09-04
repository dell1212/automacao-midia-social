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

export function AuditLogList({ entries }: { entries: AuditLogEntry[] }) {
  if (entries.length === 0) {
    return <p>Nenhum evento registrado.</p>;
  }

  return (
    <table>
      <thead>
        <tr>
          <th>Data</th>
          <th>Ação</th>
          <th>Entidade</th>
          <th>Ator</th>
          <th>Detalhes</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => (
          <tr key={entry.id}>
            <td>{new Date(entry.created_at).toLocaleString()}</td>
            <td>{entry.action}</td>
            <td>
              {entry.entity_type} #{entry.entity_id}
            </td>
            <td>{entry.actor}</td>
            {/* Events recorded before the 5c history feature (approve/reject
                from 5a, all of 5b's config CRUD) have details === null. */}
            <td>{formatAuditDetails(entry.details)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
