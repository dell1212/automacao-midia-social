import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { apiClient, apiErrorStatus } from "../lib/apiClient";
import { useSession } from "../context/SessionProvider";
import { RequireRole } from "../components/RequireRole";
import { AuditLogList } from "../components/AuditLogList";
import { ErrorText } from "../components/ErrorText";
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
  const [narrationScript, setNarrationScript] = useState("");
  const [riskLevel, setRiskLevel] = useState("");
  const [contentCategory, setContentCategory] = useState("");
  const [avatarId, setAvatarId] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [scheduledFor, setScheduledFor] = useState("");
  const [assetFile, setAssetFile] = useState<File | null>(null);

  // A 409 here means someone else changed the piece's status first (posted
  // it, decided it) — the on-screen status/buttons are now stale, not just
  // the mutation. Refetch instead of leaving the user free to retry an
  // action that can no longer succeed.
  const invalidateOnConflict = (error: unknown) => {
    if (apiErrorStatus(error) !== 409) return;
    queryClient.invalidateQueries({ queryKey: ["piece", id] });
    queryClient.invalidateQueries({ queryKey: ["audit-log", "content_piece", id] });
  };

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
    onError: invalidateOnConflict,
  });

  const edit = useMutation({
    mutationFn: (payload: PieceUpdatePayload) =>
      apiClient.patch(`/content/ui/pieces/${id}`, payload),
    onSuccess: () => {
      setGenerationPrompt("");
      setNarrationScript("");
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
    onError: invalidateOnConflict,
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
    onError: invalidateOnConflict,
  });

  if (detail.isLoading) return <p>Carregando...</p>;
  if (detail.isError) return <p>Erro ao carregar esta peça.</p>;
  if (!detail.data) return null;

  const piece = detail.data;
  const canDecide = canApprove() && piece.status === "pending_approval";
  const canEdit = canApprove() && piece.status !== "posted";

  return (
    <div>
      <h1>Peça #{piece.id}</h1>
      <p>Status: {piece.status}</p>
      <p>Prompt: {piece.generation_prompt ?? "(sem prompt)"}</p>
      <p>Roteiro de narração: {piece.narration_script ?? "(usa o prompt de geração)"}</p>
      <p>Categoria: {piece.content_category ?? "—"} · Risco: {piece.risk_level}</p>
      <p>Mídia sintética: {piece.is_synthetic_media ? "sim" : "não"}</p>

      {piece.assets.map((asset, index) => {
        // Keyed by position, not by signed_url: an unsigned asset has none,
        // and two of them would collide on a null key.
        const key = `${asset.type}-${index}`;
        if (asset.signed_url === null) {
          return (
            <p key={key}>
              Asset ({asset.type}) não pôde ser carregado — decida somente após visualizá-lo.
            </p>
          );
        }
        if (asset.type === "video") {
          return <video key={key} src={asset.signed_url} controls />;
        }
        if (asset.type === "audio") {
          return <audio key={key} src={asset.signed_url} controls />;
        }
        return <img key={key} src={asset.signed_url} alt={`asset-${piece.id}`} />;
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
        <ErrorText
          error={decide.error}
          fallback="Erro ao decidir esta peça."
          conflict="Esta peça já foi decidida por outra pessoa."
        />
      </div>

      <RequireRole role="admin" fallback={null}>
        <h2>Editar</h2>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            edit.mutate({
              generation_prompt: generationPrompt || undefined,
              narration_script: narrationScript || undefined,
              risk_level: riskLevel || undefined,
              content_category: contentCategory || undefined,
              avatar_id: avatarId ? Number(avatarId) : undefined,
              voice_id: voiceId || undefined,
              scheduled_for: scheduledFor ? new Date(scheduledFor).toISOString() : undefined,
            });
          }}
        >
          <label>
            Prompt de geração
            <input
              value={generationPrompt}
              onChange={(event) => setGenerationPrompt(event.target.value)}
              placeholder="Novo prompt de geração"
            />
          </label>
          <label>
            Roteiro de narração
            <input
              value={narrationScript}
              onChange={(event) => setNarrationScript(event.target.value)}
              placeholder="Novo roteiro de narração (opcional — sem isso, usa o prompt de geração)"
            />
          </label>
          <label>
            Nível de risco
            <select value={riskLevel} onChange={(event) => setRiskLevel(event.target.value)}>
              <option value="">Manter risco atual</option>
              <option value="none">Nenhum</option>
              <option value="low">Baixo</option>
              <option value="medium">Médio</option>
              <option value="high">Alto</option>
            </select>
          </label>
          <label>
            Categoria de conteúdo
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
          </label>
          <label>
            Avatar
            <select value={avatarId} onChange={(event) => setAvatarId(event.target.value)}>
              <option value="">Manter avatar atual</option>
              {avatars.data?.map((avatar) => (
                <option key={avatar.id} value={avatar.id}>
                  {avatar.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Voice ID
            <input
              value={voiceId}
              onChange={(event) => setVoiceId(event.target.value)}
              placeholder="Novo voice_id (opcional)"
            />
          </label>
          <label>
            Agendar para
            <input
              type="datetime-local"
              value={scheduledFor}
              onChange={(event) => setScheduledFor(event.target.value)}
            />
          </label>
          <button type="submit" disabled={!canEdit || edit.isPending}>
            Salvar edição
          </button>
          <ErrorText
            error={edit.error}
            fallback="Erro ao salvar edição."
            conflict="Esta peça foi publicada por outra pessoa — não pode mais ser editada."
          />
        </form>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (assetFile) replaceAsset.mutate(assetFile);
          }}
        >
          <label>
            Novo asset
            <input
              type="file"
              onChange={(event) => setAssetFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button type="submit" disabled={!canEdit || !assetFile || replaceAsset.isPending}>
            Substituir asset
          </button>
          <ErrorText
            error={replaceAsset.error}
            fallback="Erro ao substituir asset."
            conflict="Esta peça foi publicada por outra pessoa — o asset não pode mais ser substituído."
          />
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
