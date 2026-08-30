import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { apiClient, ApiError } from "../lib/apiClient";
import { useSession } from "../context/SessionProvider";
import { RequireRole } from "../components/RequireRole";
import { AuditLogList } from "../components/AuditLogList";
import type {
  Avatar,
  AuditLogEntry,
  Campaign,
  PieceDetail as PieceDetailType,
  PieceUpdatePayload,
} from "../lib/types";

export function PieceDetail() {
  const { id } = useParams<{ id: string }>();
  const { canApprove } = useSession();
  const queryClient = useQueryClient();

  const [generationPrompt, setGenerationPrompt] = useState("");
  const [riskLevel, setRiskLevel] = useState("");
  const [contentCategory, setContentCategory] = useState("");
  const [avatarId, setAvatarId] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [scheduledFor, setScheduledFor] = useState("");
  const [assetFile, setAssetFile] = useState<File | null>(null);

  const detail = useQuery({
    queryKey: ["piece", id],
    queryFn: () => apiClient.get<PieceDetailType>(`/content/ui/pieces/${id}`),
  });

  const campaignId = detail.data?.campaign_id;
  const campaign = useQuery({
    queryKey: ["campaign", campaignId],
    queryFn: () => apiClient.get<Campaign>(`/content/ui/config/campaigns/${campaignId}`),
    enabled: campaignId !== undefined,
  });

  const clientId = campaign.data?.client_id;
  const avatars = useQuery({
    queryKey: ["config", "avatars", clientId],
    queryFn: () => apiClient.get<Avatar[]>(`/content/ui/config/clients/${clientId}/avatars`),
    enabled: clientId !== undefined,
  });

  const history = useQuery({
    queryKey: ["audit-log", "content_piece", id],
    queryFn: () =>
      apiClient.get<AuditLogEntry[]>(
        `/content/ui/audit-log?entity_type=content_piece&entity_id=${id}`
      ),
  });

  const decide = useMutation({
    mutationFn: (action: "approve" | "reject") =>
      apiClient.post(`/content/ui/pieces/${id}/${action}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["piece", id] });
      queryClient.invalidateQueries({ queryKey: ["pieces"] });
      queryClient.invalidateQueries({ queryKey: ["audit-log", "content_piece", id] });
      queryClient.invalidateQueries({ queryKey: ["audit-log", "feed"] });
    },
  });

  const edit = useMutation({
    mutationFn: (payload: PieceUpdatePayload) =>
      apiClient.patch(`/content/ui/pieces/${id}`, payload),
    onSuccess: () => {
      setGenerationPrompt("");
      setRiskLevel("");
      setContentCategory("");
      setAvatarId("");
      setVoiceId("");
      setScheduledFor("");
      queryClient.invalidateQueries({ queryKey: ["piece", id] });
      queryClient.invalidateQueries({ queryKey: ["pieces"] });
      queryClient.invalidateQueries({ queryKey: ["audit-log", "content_piece", id] });
      queryClient.invalidateQueries({ queryKey: ["audit-log", "feed"] });
    },
  });

  const replaceAsset = useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData();
      formData.append("type", piece!.type);
      formData.append("file", file);
      return apiClient.uploadFile(`/content/ui/pieces/${id}/asset`, formData);
    },
    onSuccess: () => {
      setAssetFile(null);
      queryClient.invalidateQueries({ queryKey: ["piece", id] });
      queryClient.invalidateQueries({ queryKey: ["pieces"] });
      queryClient.invalidateQueries({ queryKey: ["audit-log", "content_piece", id] });
      queryClient.invalidateQueries({ queryKey: ["audit-log", "feed"] });
    },
  });

  if (detail.isLoading) return <p>Carregando...</p>;
  if (detail.isError) return <p>Erro ao carregar esta peça.</p>;
  if (!detail.data) return null;

  const piece = detail.data;
  const canDecide = canApprove() && piece.status === "pending_approval";
  const canEdit = canApprove() && piece.status !== "posted";
  const conflict = decide.error instanceof ApiError && decide.error.status === 409;

  return (
    <div>
      <h1>Peça #{piece.id}</h1>
      <p>Status: {piece.status}</p>
      <p>Prompt: {piece.generation_prompt ?? "(sem prompt)"}</p>
      <p>Categoria: {piece.content_category ?? "—"} · Risco: {piece.risk_level}</p>
      <p>Mídia sintética: {piece.is_synthetic_media ? "sim" : "não"}</p>

      {piece.assets.map((asset) => {
        if (asset.type === "video") {
          return <video key={asset.signed_url} src={asset.signed_url} controls />;
        }
        if (asset.type === "audio") {
          return <audio key={asset.signed_url} src={asset.signed_url} controls />;
        }
        return <img key={asset.signed_url} src={asset.signed_url} alt={`asset-${piece.id}`} />;
      })}

      <div>
        <button
          disabled={!canDecide || decide.isPending}
          title={!canDecide ? "Você não tem permissão para decidir esta peça" : undefined}
          onClick={() => decide.mutate("approve")}
        >
          Aprovar
        </button>
        <button
          disabled={!canDecide || decide.isPending}
          title={!canDecide ? "Você não tem permissão para decidir esta peça" : undefined}
          onClick={() => decide.mutate("reject")}
        >
          Rejeitar
        </button>
        {conflict && <p>Esta peça já foi decidida por outra pessoa.</p>}
      </div>

      <RequireRole role="admin" fallback={null}>
        <h2>Editar</h2>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            edit.mutate({
              generation_prompt: generationPrompt || undefined,
              risk_level: riskLevel || undefined,
              content_category: contentCategory || undefined,
              avatar_id: avatarId ? Number(avatarId) : undefined,
              voice_id: voiceId || undefined,
              scheduled_for: scheduledFor ? new Date(scheduledFor).toISOString() : undefined,
            });
          }}
        >
          <input
            value={generationPrompt}
            onChange={(event) => setGenerationPrompt(event.target.value)}
            placeholder="Novo prompt de geração"
          />
          <select value={riskLevel} onChange={(event) => setRiskLevel(event.target.value)}>
            <option value="">Manter risco atual</option>
            <option value="none">Nenhum</option>
            <option value="low">Baixo</option>
            <option value="medium">Médio</option>
            <option value="high">Alto</option>
          </select>
          <select value={contentCategory} onChange={(event) => setContentCategory(event.target.value)}>
            <option value="">Manter categoria atual</option>
            <option value="medical">Médico</option>
            <option value="pharmaceutical">Farmacêutico</option>
            <option value="financial">Financeiro</option>
            <option value="insurance">Seguros</option>
            <option value="legal">Jurídico</option>
            <option value="alcohol">Álcool</option>
            <option value="gambling">Apostas</option>
            <option value="political">Político</option>
            <option value="regulated_product">Produto regulado</option>
          </select>
          <select value={avatarId} onChange={(event) => setAvatarId(event.target.value)}>
            <option value="">Manter avatar atual</option>
            {avatars.data?.map((avatar) => (
              <option key={avatar.id} value={avatar.id}>
                {avatar.name}
              </option>
            ))}
          </select>
          <input
            value={voiceId}
            onChange={(event) => setVoiceId(event.target.value)}
            placeholder="Novo voice_id (opcional)"
          />
          <input
            type="datetime-local"
            value={scheduledFor}
            onChange={(event) => setScheduledFor(event.target.value)}
          />
          <button type="submit" disabled={!canEdit || edit.isPending}>
            Salvar edição
          </button>
          {edit.isError && <p>Erro ao salvar edição.</p>}
        </form>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (assetFile) replaceAsset.mutate(assetFile);
          }}
        >
          <input
            type="file"
            onChange={(event) => setAssetFile(event.target.files?.[0] ?? null)}
          />
          <button type="submit" disabled={!canEdit || !assetFile || replaceAsset.isPending}>
            Substituir asset
          </button>
          {replaceAsset.isError && <p>Erro ao substituir asset.</p>}
        </form>
        {piece.status === "posted" && <p>Peça publicada — não pode mais ser editada.</p>}
      </RequireRole>

      <h2>Publicações</h2>
      <ul>
        {piece.publications.map((publication) => (
          <li key={publication.id}>
            {publication.platform}: {publication.status}
            {publication.error_message ? ` — ${publication.error_message}` : ""}
          </li>
        ))}
      </ul>

      <h2>Histórico</h2>
      {history.isLoading && <p>Carregando histórico...</p>}
      {history.isError && <p>Erro ao carregar histórico.</p>}
      {history.data && <AuditLogList entries={history.data} />}
    </div>
  );
}
