import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Avatar, Campaign, GenerationTemplate } from "../../lib/types";

const ASPECT_RATIO_PRESETS = ["9:16", "16:9", "1:1", "4:5"];

export function GenerationTemplates() {
  const queryClient = useQueryClient();
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [type, setType] = useState<"video" | "image" | "audio">("image");
  const [generationPrompt, setGenerationPrompt] = useState("");
  const [aspectRatio, setAspectRatio] = useState("9:16");
  const [customAspectRatio, setCustomAspectRatio] = useState("");
  const [avatarId, setAvatarId] = useState<number | null>(null);
  const [voiceId, setVoiceId] = useState("");

  const effectiveAspectRatio = aspectRatio === "custom" ? customAspectRatio : aspectRatio;

  const campaigns = useQuery({
    queryKey: ["config", "campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const selectedCampaign = campaigns.data?.find((campaign) => campaign.id === campaignId);

  const avatars = useQuery({
    queryKey: ["config", "avatars", selectedCampaign?.client_id],
    queryFn: () =>
      apiClient.get<Avatar[]>(`/content/ui/config/clients/${selectedCampaign?.client_id}/avatars`),
    enabled: selectedCampaign !== undefined,
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
          aspect_ratio: effectiveAspectRatio,
          avatar_id: avatarId,
          voice_id: voiceId || null,
        }
      ),
    onSuccess: () => {
      setGenerationPrompt("");
      setAvatarId(null);
      setVoiceId("");
      setAspectRatio("9:16");
      setCustomAspectRatio("");
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
            if (campaignId !== null && generationPrompt.trim() && effectiveAspectRatio.trim()) {
              create.mutate();
            }
          }}
        >
          <label>
            Tipo
            <select value={type} onChange={(event) => setType(event.target.value as typeof type)}>
              <option value="image">Imagem</option>
              <option value="video">Vídeo</option>
              <option value="audio">Áudio</option>
            </select>
          </label>
          <label>
            Prompt de geração
            <input
              value={generationPrompt}
              onChange={(event) => setGenerationPrompt(event.target.value)}
              placeholder="Prompt de geração"
              required
            />
          </label>
          <label>
            Aspect ratio
            <select
              value={aspectRatio}
              onChange={(event) => setAspectRatio(event.target.value)}
            >
              {ASPECT_RATIO_PRESETS.map((preset) => (
                <option key={preset} value={preset}>
                  {preset}
                </option>
              ))}
              <option value="custom">Custom…</option>
            </select>
          </label>
          {aspectRatio === "custom" && (
            <label>
              Aspect ratio customizado
              <input
                value={customAspectRatio}
                onChange={(event) => setCustomAspectRatio(event.target.value)}
                placeholder="ex: 21:9"
                required
              />
            </label>
          )}
          <label>
            Avatar
            <select
              value={avatarId ?? ""}
              onChange={(event) => setAvatarId(Number(event.target.value) || null)}
            >
              <option value="">Sem avatar</option>
              {avatars.data?.map((avatar) => (
                <option key={avatar.id} value={avatar.id}>
                  {avatar.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Voice ID (opcional)
            <input
              value={voiceId}
              onChange={(event) => setVoiceId(event.target.value)}
              placeholder="ID da voz no provider, para narração em áudio/vídeo"
            />
          </label>
          <button
            type="submit"
            disabled={
              create.isPending ||
              campaignId === null ||
              !generationPrompt.trim() ||
              !effectiveAspectRatio.trim()
            }
          >
            Criar template
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
