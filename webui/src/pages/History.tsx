import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { apiClient } from "../lib/apiClient";
import { AuditLogList, formatAuditDetails } from "../components/AuditLogList";
import { SettingsPage } from "../components/settings/SettingsPage";
import { Select } from "../components/settings/Controls";
import { Button } from "../components/ui/Button";
import { Card, MicroLabel } from "../components/ui/Card";
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

/** One filter of the toolbar: caption above, control below.
 *
 * MicroLabel rather than Field: Field's <label> wraps its control, which is
 * right for a form, but these two sit in a toolbar next to buttons and need
 * to line up with them on the same baseline. */
function Filter({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex min-w-48 flex-col gap-1.5">
      <MicroLabel>{label}</MicroLabel>
      <Select
        value={value}
        aria-label={label}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>
    </div>
  );
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

  const rows = feed.data;
  const empty = !rows?.length;

  return (
    <SettingsPage
      title="Histórico"
      description="Cada criação, edição, decisão e publicação registrada pelo módulo, da mais recente para a mais antiga."
    >
      <Card className="flex flex-wrap items-end gap-3 px-4 py-3">
        <Filter
          label="Entidade"
          value={entityType}
          options={ENTITY_TYPES}
          onChange={(value) => {
            setEntityType(value);
            setOffset(0);
          }}
        />
        <Filter
          label="Período"
          value={periodDays}
          options={PERIODS}
          onChange={(value) => {
            setPeriodDays(value);
            setOffset(0);
          }}
        />
        {/* Caption above the buttons, exactly like the two filters: the
            export pair used to carry its caveat underneath, which made the
            block taller and left the buttons sitting 28px above the selects
            they share a row with. */}
        <div className="ml-auto flex flex-col gap-1.5">
          <MicroLabel>Exportar página atual</MicroLabel>
          <div className="flex items-center gap-2">
            <Button disabled={empty} onClick={exportCsv}>
              <Download size={14} />
              CSV
            </Button>
            <Button disabled={empty} onClick={exportJson}>
              <Download size={14} />
              JSON
            </Button>
          </div>
        </div>
      </Card>

      <AuditLogList
        entries={rows}
        isLoading={feed.isLoading}
        isError={feed.isError}
        error={feed.error}
        emptyHint="Nenhum evento bate com os filtros escolhidos."
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-[12px] text-[var(--text)]">
          {rows
            ? `Exibindo ${rows.length === 0 ? 0 : offset + 1}–${offset + rows.length}`
            : ""}
        </span>
        <div className="flex items-center gap-2">
          <Button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Anterior
          </Button>
          <Button
            disabled={(rows?.length ?? 0) < PAGE_SIZE}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Próxima
          </Button>
        </div>
      </div>
    </SettingsPage>
  );
}
