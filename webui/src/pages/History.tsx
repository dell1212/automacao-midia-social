import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { AuditLogList } from "../components/AuditLogList";
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

const PAGE_SIZE = 50;

export function HistoryPage() {
  const [entityType, setEntityType] = useState("");
  const [offset, setOffset] = useState(0);

  const feed = useQuery({
    queryKey: ["audit-log", "feed", entityType, offset],
    queryFn: () =>
      apiClient.get<AuditLogEntry[]>(
        `/content/ui/audit-log?limit=${PAGE_SIZE}&offset=${offset}` +
          (entityType ? `&entity_type=${entityType}` : "")
      ),
  });

  return (
    <div>
      <h1>Histórico</h1>

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

      {feed.isLoading && <p>Carregando...</p>}
      {feed.isError && <p>Erro ao carregar. Tente novamente.</p>}
      {feed.data && <AuditLogList entries={feed.data} />}

      <div>
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
