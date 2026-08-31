import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { AuditLogList, formatAuditDetails } from "../components/AuditLogList";
import type { AuditLogEntry } from "../lib/types";

const ENTITY_TYPES = [
  { value: "", label: "Todos" },
  { value: "content_piece", label: "Peças" },
  { value: "content_client", label: "Clientes" },
  { value: "content_campaign", label: "Campanhas" },
  { value: "content_avatar", label: "Avatares" },
  { value: "content_social_account", label: "Contas sociais" },
  { value: "content_approval_rule", label: "Regras de aprovação" },
  { value: "content_generation_template", label: "Templates" },
  { value: "content_generation_provider", label: "Provedores" },
];

// "Todo o período" omits `since` entirely rather than sending a huge day
// count, so the query stays correct if this list's oldest option changes.
const PERIODS = [
  { value: "", label: "Todo o período" },
  { value: "30", label: "Últimos 30 dias" },
  { value: "60", label: "Últimos 60 dias" },
  { value: "90", label: "Últimos 90 dias" },
  { value: "120", label: "Últimos 120 dias" },
];

const PAGE_SIZE = 50;

function sinceParamFor(periodDays: string): string {
  if (!periodDays) return "";
  const since = new Date(Date.now() - Number(periodDays) * 24 * 60 * 60 * 1000);
  return `&since=${encodeURIComponent(since.toISOString())}`;
}

function downloadTextFile(filename: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function toCsv(entries: AuditLogEntry[]): string {
  const header = ["id", "created_at", "action", "entity_type", "entity_id", "actor", "details"];
  const escape = (value: string) => `"${value.replace(/"/g, '""')}"`;
  const rows = entries.map((entry) =>
    [
      entry.id,
      entry.created_at,
      entry.action,
      entry.entity_type,
      entry.entity_id,
      entry.actor,
      formatAuditDetails(entry.details),
    ]
      .map((value) => escape(String(value)))
      .join(",")
  );
  return [header.join(","), ...rows].join("\n");
}

export function HistoryPage() {
  const [entityType, setEntityType] = useState("");
  const [periodDays, setPeriodDays] = useState("");
  const [offset, setOffset] = useState(0);

  const feed = useQuery({
    queryKey: ["audit-log", "feed", entityType, periodDays, offset],
    queryFn: () =>
      apiClient.get<AuditLogEntry[]>(
        `/content/ui/audit-log?limit=${PAGE_SIZE}&offset=${offset}` +
          (entityType ? `&entity_type=${entityType}` : "") +
          sinceParamFor(periodDays)
      ),
  });

  const exportJson = () => {
    if (!feed.data) return;
    downloadTextFile("historico.json", JSON.stringify(feed.data, null, 2), "application/json");
  };

  const exportCsv = () => {
    if (!feed.data) return;
    downloadTextFile("historico.csv", toCsv(feed.data), "text/csv");
  };

  return (
    <div>
      <h1>Histórico</h1>

      <div className="controls-row">
        <label>
          Entidade
          <select
            value={entityType}
            onChange={(event) => {
              setEntityType(event.target.value);
              setOffset(0);
            }}
          >
            {ENTITY_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          Período
          <select
            value={periodDays}
            onChange={(event) => {
              setPeriodDays(event.target.value);
              setOffset(0);
            }}
          >
            {PERIODS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <button type="button" disabled={!feed.data?.length} onClick={exportCsv}>
          Exportar CSV
        </button>
        <button type="button" disabled={!feed.data?.length} onClick={exportJson}>
          Exportar JSON
        </button>
      </div>
      <p>Exporta só a página atual (o que está listado abaixo).</p>

      {feed.isLoading && <p>Carregando...</p>}
      {feed.isError && <p>Erro ao carregar. Tente novamente.</p>}
      {feed.data && <AuditLogList entries={feed.data} />}

      <div className="controls-row">
        {feed.data && (
          <span>
            Exibindo {feed.data.length === 0 ? 0 : offset + 1}–{offset + feed.data.length}
          </span>
        )}
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          Anterior
        </button>
        <button
          disabled={(feed.data?.length ?? 0) < PAGE_SIZE}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Próxima
        </button>
      </div>
    </div>
  );
}
