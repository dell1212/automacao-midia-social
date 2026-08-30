import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Campaign, GenerationTemplate } from "../../lib/types";

export function GenerationTemplates() {
  const queryClient = useQueryClient();
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [type, setType] = useState<"video" | "image" | "audio">("image");
  const [generationPrompt, setGenerationPrompt] = useState("");
  const [aspectRatio, setAspectRatio] = useState("9:16");

  const campaigns = useQuery({
    queryKey: ["config", "campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const templates = useQuery({
    queryKey: ["config", "templates", campaignId],
    queryFn: () =>
      apiClient.get<GenerationTemplate[]>(`/content/ui/config/campaigns/${campaignId}/templates`),
    enabled: campaignId !== null,
  });

  const create = useMutation({
    mutationFn: () =>
      apiClient.post<GenerationTemplate>(
        `/content/ui/config/campaigns/${campaignId}/templates`,
        {
          campaign_id: campaignId,
          type,
          generation_prompt: generationPrompt,
          is_synthetic_media: false,
          aspect_ratio: aspectRatio,
        }
      ),
    onSuccess: () => {
      setGenerationPrompt("");
      queryClient.invalidateQueries({ queryKey: ["config", "templates", campaignId] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete<GenerationTemplate>(`/content/ui/config/templates/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "templates", campaignId] }),
  });

  return (
    <div>
      <h1>Generation Templates</h1>

      <select
        value={campaignId ?? ""}
        onChange={(event) => setCampaignId(Number(event.target.value) || null)}
      >
        <option value="">Selecione uma campanha</option>
        {campaigns.data?.map((campaign) => (
          <option key={campaign.id} value={campaign.id}>
            {campaign.name}
          </option>
        ))}
      </select>

      {templates.isLoading && <p>Carregando...</p>}
      {templates.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {templates.data?.map((template) => (
          <li key={template.id}>
            {template.type} — {template.generation_prompt ?? "(sem prompt)"}{" "}
            {!template.is_active && "(inativo)"}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={!template.is_active || deactivate.isPending}
                onClick={() => deactivate.mutate(template.id)}
              >
                Desativar
              </button>
            </RequireRole>
          </li>
        ))}
      </ul>

      <RequireRole role="admin">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (campaignId !== null) create.mutate();
          }}
        >
          <select value={type} onChange={(event) => setType(event.target.value as typeof type)}>
            <option value="image">Imagem</option>
            <option value="video">Vídeo</option>
            <option value="audio">Áudio</option>
          </select>
          <input
            value={generationPrompt}
            onChange={(event) => setGenerationPrompt(event.target.value)}
            placeholder="Prompt de geração"
          />
          <input
            value={aspectRatio}
            onChange={(event) => setAspectRatio(event.target.value)}
            placeholder="Aspect ratio (ex: 9:16)"
          />
          <button type="submit" disabled={create.isPending || campaignId === null}>
            Criar template
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
