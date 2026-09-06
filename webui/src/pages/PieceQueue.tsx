import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiClient } from "../lib/apiClient";
import { SettingsPage } from "../components/settings/SettingsPage";
import { DataTable, type Column } from "../components/settings/DataTable";
import { ScopeBar } from "../components/settings/ScopeBar";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/Feedback";
import { StatusChip } from "../components/ui/StatusChip";
import { PIECE_TYPE_LABELS } from "../lib/types";
import type { Campaign, ContentPieceStatus, ContentPieceSummary } from "../lib/types";

const TABS: { label: string; value: ContentPieceStatus }[] = [
  { label: "Aguardando revisão", value: "pending_approval" },
  { label: "Aprovadas", value: "approved" },
  { label: "Rejeitadas", value: "rejected" },
  { label: "Publicadas", value: "posted" },
  { label: "Falhas", value: "failed" },
];

const EMPTY_HINTS: Record<ContentPieceStatus, string> = {
  draft: "Nada em rascunho nesta campanha.",
  generating: "Nenhuma peça sendo gerada agora.",
  pending_approval: "Nada aguardando revisão — a fila está limpa.",
  approved: "Nenhuma peça aprovada ainda nesta campanha.",
  rejected: "Nenhuma peça foi rejeitada nesta campanha.",
  posted: "Nada publicado ainda nesta campanha.",
  failed: "Nenhuma falha de publicação nesta campanha.",
};

function formatSchedule(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function PieceQueue() {
  const [status, setStatus] = useState<ContentPieceStatus>("pending_approval");
  const [campaignId, setCampaignId] = useState<number | null>(null);

  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const activeCampaignId = campaignId ?? campaigns.data?.[0]?.id ?? null;

  const pieces = useQuery({
    queryKey: ["pieces", activeCampaignId, status],
    queryFn: () =>
      apiClient.get<ContentPieceSummary[]>(
        `/content/ui/pieces?campaign_id=${activeCampaignId}&status=${status}`
      ),
    enabled: activeCampaignId !== null,
  });

  const columns: Array<Column<ContentPieceSummary>> = [
    {
      key: "piece",
      header: "Peça",
      render: (piece) => (
        <Link
          to={`/pieces/${piece.id}`}
          className="block max-w-[38rem] truncate text-[var(--text-h)] no-underline hover:underline"
        >
          <span className="font-mono text-[12px] text-[var(--text)]">#{piece.id}</span>{" "}
          <span className="font-medium">
            {piece.generation_prompt ?? "(sem prompt)"}
          </span>
        </Link>
      ),
    },
    {
      key: "type",
      header: "Tipo",
      width: "7rem",
      render: (piece) => PIECE_TYPE_LABELS[piece.type] ?? piece.type,
    },
    {
      key: "status",
      header: "Status",
      width: "11rem",
      render: (piece) => <StatusChip status={piece.status} />,
    },
    {
      key: "scheduled_for",
      header: "Agendada",
      width: "9rem",
      align: "right",
      render: (piece) => (
        <span className="whitespace-nowrap font-mono text-[12px]">
          {formatSchedule(piece.scheduled_for)}
        </span>
      ),
    },
  ];

  // Without a campaign the pieces query stays disabled, so neither its loading
  // nor its error state ever renders — these two cases would otherwise be an
  // empty screen with no explanation.
  if (campaigns.isError || campaigns.data?.length === 0) {
    return (
      <SettingsPage title="Fila de peças">
        <Card>
          {campaigns.isError ? (
            <EmptyState
              title="Não foi possível carregar as campanhas"
              hint="Verifique a conexão com o servidor e recarregue a página."
            />
          ) : (
            <EmptyState
              title="Nenhuma campanha cadastrada"
              hint="Crie uma campanha em Configurações para que as peças tenham onde aparecer."
            />
          )}
        </Card>
      </SettingsPage>
    );
  }

  return (
    <SettingsPage
      title="Fila de peças"
      description="Tudo que a campanha gerou, agrupado pelo ponto em que está no fluxo de revisão."
    >
      <ScopeBar
        label="Campanha"
        options={campaigns.data?.map((campaign) => ({
          id: campaign.id,
          label: campaign.name,
        }))}
        value={activeCampaignId}
        // The placeholder is a no-op here: a campaign is always selected (the
        // first one, until someone picks another), because the pieces query
        // cannot run without one.
        onChange={(id) => id !== null && setCampaignId(id)}
        placeholder="Selecione a campanha"
        isLoading={campaigns.isLoading}
      />

      <div className="flex flex-wrap items-center gap-1.5">
        {TABS.map((tab) => (
          <Button
            key={tab.value}
            variant={status === tab.value ? "primary" : "ghost"}
            aria-current={status === tab.value}
            onClick={() => setStatus(tab.value)}
          >
            {tab.label}
          </Button>
        ))}
      </div>

      <DataTable
        columns={columns}
        rows={pieces.data}
        rowKey={(piece) => piece.id}
        isLoading={pieces.isLoading}
        isError={pieces.isError}
        error={pieces.error}
        emptyTitle="Nenhuma peça neste status"
        emptyHint={EMPTY_HINTS[status]}
      />
    </SettingsPage>
  );
}
