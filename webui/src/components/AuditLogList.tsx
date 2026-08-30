import type { AuditLogEntry } from "../lib/types";

export function AuditLogList({ entries }: { entries: AuditLogEntry[] }) {
  if (entries.length === 0) {
    return <p>Nenhum evento registrado.</p>;
  }

  return (
    <ul>
      {entries.map((entry) => (
        <li key={entry.id}>
          <strong>{entry.action}</strong> por {entry.actor} em{" "}
          {new Date(entry.created_at).toLocaleString()}
          {/* Events recorded before the 5c history feature (approve/reject
              from 5a, all of 5b's config CRUD) have details === null — must
              render gracefully instead of reading .before/.after on null. */}
          {entry.details && (
            <ul>
              {Object.entries(entry.details).map(([field, change]) => (
                <li key={field}>
                  {field}: {String(change.before)} → {String(change.after)}
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}
