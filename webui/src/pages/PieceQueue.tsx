import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiClient } from "../lib/apiClient";
import type { Campaign, ContentPieceStatus, ContentPieceSummary } from "../lib/types";

const TABS: { label: string; value: ContentPieceStatus }[] = [
  { label: "Aguardando revisão", value: "pending_approval" },
  { label: "Aprovadas", value: "approved" },
  { label: "Rejeitadas", value: "rejected" },
  { label: "Publicadas", value: "posted" },
  { label: "Falhas", value: "failed" },
];

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

  return (
    <div>
      <select
        value={activeCampaignId ?? ""}
        onChange={(event) => setCampaignId(Number(event.target.value))}
      >
        {campaigns.data?.map((campaign) => (
          <option key={campaign.id} value={campaign.id}>
            {campaign.name}
          </option>
        ))}
      </select>

      <nav>
        {TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setStatus(tab.value)}
            aria-current={status === tab.value}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {pieces.isLoading && <p>Carregando...</p>}
      {pieces.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {pieces.data?.map((piece) => (
          <li key={piece.id}>
            <Link to={`/pieces/${piece.id}`}>
              #{piece.id} — {piece.type} — {piece.generation_prompt ?? "(sem prompt)"}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
