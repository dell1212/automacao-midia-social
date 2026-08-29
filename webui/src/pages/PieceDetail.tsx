import { useParams } from "react-router-dom";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { apiClient, ApiError } from "../lib/apiClient";
import { useSession } from "../context/SessionProvider";
import type { PieceDetail as PieceDetailType } from "../lib/types";

export function PieceDetail() {
  const { id } = useParams<{ id: string }>();
  const { canApprove } = useSession();
  const queryClient = useQueryClient();

  const detail = useQuery({
    queryKey: ["piece", id],
    queryFn: () => apiClient.get<PieceDetailType>(`/content/ui/pieces/${id}`),
  });

  const decide = useMutation({
    mutationFn: (action: "approve" | "reject") =>
      apiClient.post(`/content/ui/pieces/${id}/${action}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["piece", id] });
      queryClient.invalidateQueries({ queryKey: ["pieces"] });
    },
  });

  if (detail.isLoading) return <p>Carregando...</p>;
  if (detail.isError) return <p>Erro ao carregar esta peça.</p>;
  if (!detail.data) return null;

  const piece = detail.data;
  const canDecide = canApprove() && piece.status === "pending_approval";
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

      <h2>Publicações</h2>
      <ul>
        {piece.publications.map((publication) => (
          <li key={publication.id}>
            {publication.platform}: {publication.status}
            {publication.error_message ? ` — ${publication.error_message}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
