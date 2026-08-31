import type { AuditLogEntry } from "../lib/types";

// Shared by the CSV export in HistoryPage, so the on-screen "Detalhes"
// column and the exported file describe a change the same way.
export function formatAuditDetails(details: AuditLogEntry["details"]): string {
  if (!details) return "";
  return Object.entries(details)
    .map(([field, change]) => `${field}: ${String(change.before)} → ${String(change.after)}`)
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
