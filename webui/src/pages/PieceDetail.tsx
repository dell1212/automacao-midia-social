import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { ArrowUpRight, FileWarning } from "lucide-react";
import { apiClient, apiErrorStatus } from "../lib/apiClient";
import { useSession } from "../context/SessionProvider";
import { RequireRole } from "../components/RequireRole";
import { AuditLogList } from "../components/AuditLogList";
import { CaptionEditor } from "../components/CaptionEditor";
import { ErrorText } from "../components/ErrorText";
import { SettingsPage } from "../components/settings/SettingsPage";
import { Field } from "../components/settings/Field";
import { Input, Select } from "../components/settings/Controls";
import { Button } from "../components/ui/Button";
import { Card, MicroLabel } from "../components/ui/Card";
import { EmptyState, SkeletonRows } from "../components/ui/Feedback";
import { StatusChip } from "../components/ui/StatusChip";
import { PlatformIcon, type Platform } from "../components/ui/PlatformIcon";
import { cn } from "../components/ui/cn";
import { PIECE_TYPE_LABELS } from "../lib/types";
import type {
  Avatar,
  AuditLogEntry,
  Campaign,
  PieceDetail as PieceDetailType,
  Publication,
  PieceUpdatePayload,
} from "../lib/types";

const RISK_LABELS: Record<string, string> = {
  none: "Nenhum",
  low: "Baixo",
  medium: "Médio",
  high: "Alto",
};

const CATEGORY_OPTIONS = [
  { value: "medical", label: "Médico" },
  { value: "pharmaceutical", label: "Farmacêutico" },
  { value: "financial", label: "Financeiro" },
  { value: "insurance", label: "Seguros" },
  { value: "legal", label: "Jurídico" },
  { value: "alcohol", label: "Álcool" },
  { value: "gambling", label: "Apostas" },
  { value: "political", label: "Político" },
  { value: "regulated_product", label: "Produto regulado" },
];

/** The publication lifecycle, which is its own vocabulary: a dispatch job's
 * states, not a piece's. Deliberately not folded into `ui/StatusChip` — that
 * one maps the content-piece and calendar statuses, and merging a third
 * vocabulary into it would couple three independent evolutions. */
const PUBLICATION_STYLES: Record<Publication["status"], { label: string; className: string }> = {
  queued: { label: "Na fila", className: "bg-[var(--code-bg)] text-[var(--text)]" },
  running: { label: "Publicando", className: "bg-warn/15 text-warn" },
  retrying: { label: "Repetindo", className: "bg-warn/15 text-warn" },
  succeeded: { label: "Publicada", className: "bg-ok/15 text-ok" },
  failed: { label: "Falha", className: "bg-bad/15 text-bad" },
};

function PublicationChip({ status }: { status: Publication["status"] }) {
  const style = PUBLICATION_STYLES[status];
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center whitespace-nowrap rounded-full px-2 text-[11px] font-medium",
        style?.className ?? "bg-[var(--code-bg)] text-[var(--text)]",
      )}
    >
      {style?.label ?? status}
    </span>
  );
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <MicroLabel>{label}</MicroLabel>
      <span className="text-[13px] text-[var(--text-h)]">{children}</span>
    </div>
  );
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <MicroLabel>{label}</MicroLabel>
      {children}
    </div>
  );
}

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

  if (detail.isLoading) {
    return (
      <SettingsPage title="Peça">
        <Card className="p-4">
          <SkeletonRows rows={6} />
        </Card>
      </SettingsPage>
    );
  }
  if (detail.isError || !detail.data) {
    return (
      <SettingsPage title="Peça">
        <Card>
          <EmptyState
            title="Não foi possível carregar esta peça"
            hint={
              apiErrorStatus(detail.error) === 404
                ? "A peça não existe ou foi removida."
                : "Verifique a conexão com o servidor e tente novamente."
            }
            action={
              <Link
                to="/"
                className="inline-flex h-8 items-center rounded-[4px] bg-lime px-3.5 text-[13px] font-medium text-ink no-underline hover:bg-lime-strong"
              >
                Voltar para a fila
              </Link>
            }
          />
        </Card>
      </SettingsPage>
    );
  }

  const piece = detail.data;
  const canDecide = canApprove() && piece.status === "pending_approval";
  const canEdit = canApprove() && piece.status !== "posted";
  const decideTitle = !canDecide
    ? "Você não tem permissão para decidir esta peça"
    : undefined;

  return (
    <SettingsPage
      title={`Peça #${piece.id}`}
      description={campaign.data ? `Campanha ${campaign.data.name}` : undefined}
      action={
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-2">
            <StatusChip status={piece.status} />
            <Button
              variant="primary"
              disabled={!canDecide || decide.isPending}
              title={decideTitle}
              onClick={() => decide.mutate("approve")}
            >
              Aprovar
            </Button>
            <Button
              variant="danger"
              disabled={!canDecide || decide.isPending}
              title={decideTitle}
              onClick={() => decide.mutate("reject")}
            >
              Rejeitar
            </Button>
          </div>
          <ErrorText
            error={decide.error}
            fallback="Erro ao decidir esta peça."
            conflict="Esta peça já foi decidida por outra pessoa."
          />
        </div>
      }
    >
      <Card className="flex flex-col gap-3 p-4">
        <MicroLabel>Mídia</MicroLabel>
        {piece.assets.length === 0 ? (
          <p className="m-0 text-[13px] text-[var(--text)]">
            Esta peça ainda não tem nenhum asset gerado.
          </p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {piece.assets.map((asset, index) => {
              // Keyed by position, not by signed_url: an unsigned asset has
              // none, and two of them would collide on a null key.
              const key = `${asset.type}-${index}`;
              if (asset.signed_url === null) {
                return (
                  <p
                    key={key}
                    className="m-0 flex items-center gap-2 rounded-[4px] border border-warn/40 bg-warn/5 px-3 py-2 text-[12px] text-warn"
                  >
                    <FileWarning size={14} aria-hidden />
                    Asset ({asset.type}) não pôde ser carregado — decida somente após
                    visualizá-lo.
                  </p>
                );
              }
              if (asset.type === "video") {
                return (
                  <video
                    key={key}
                    src={asset.signed_url}
                    controls
                    className="max-h-96 rounded-[4px] border border-[var(--border)]"
                  />
                );
              }
              if (asset.type === "audio") {
                return <audio key={key} src={asset.signed_url} controls className="w-full" />;
              }
              return (
                <img
                  key={key}
                  src={asset.signed_url}
                  alt={`asset-${piece.id}`}
                  className="max-h-96 rounded-[4px] border border-[var(--border)]"
                />
              );
            })}
          </div>
        )}
      </Card>

      <Card className="grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
        <Detail label="Tipo">{PIECE_TYPE_LABELS[piece.type] ?? piece.type}</Detail>
        <Detail label="Categoria">{piece.content_category ?? "—"}</Detail>
        <Detail label="Risco">{RISK_LABELS[piece.risk_level] ?? piece.risk_level}</Detail>
        <Detail label="Mídia sintética">{piece.is_synthetic_media ? "Sim" : "Não"}</Detail>
        <Detail label="Prompt de geração">
          {piece.generation_prompt ?? "(sem prompt)"}
        </Detail>
        <Detail label="Roteiro de narração">
          {piece.narration_script ?? "(usa o prompt de geração)"}
        </Detail>
      </Card>

      <RequireRole role="admin" fallback={null}>
        <Card className="flex flex-col gap-4 p-4">
          <MicroLabel>Editar</MicroLabel>
          {piece.status === "posted" ? (
            <p className="m-0 text-[13px] text-[var(--text)]">
              Peça publicada — não pode mais ser editada.
            </p>
          ) : null}
          <form
            className="flex flex-col gap-4"
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
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Prompt de geração"
                hint="Em branco mantém o prompt atual."
              >
                <Input
                  value={generationPrompt}
                  disabled={!canEdit}
                  onChange={(event) => setGenerationPrompt(event.target.value)}
                  placeholder="Novo prompt de geração"
                />
              </Field>
              <Field
                label="Roteiro de narração"
                hint="Sem isso, a narração usa o prompt de geração."
              >
                <Input
                  value={narrationScript}
                  disabled={!canEdit}
                  onChange={(event) => setNarrationScript(event.target.value)}
                  placeholder="Novo roteiro de narração"
                />
              </Field>
              <Field label="Nível de risco">
                <Select
                  value={riskLevel}
                  disabled={!canEdit}
                  onChange={(event) => setRiskLevel(event.target.value)}
                >
                  <option value="">Manter risco atual</option>
                  <option value="none">Nenhum</option>
                  <option value="low">Baixo</option>
                  <option value="medium">Médio</option>
                  <option value="high">Alto</option>
                </Select>
              </Field>
              <Field label="Categoria de conteúdo">
                <Select
                  value={contentCategory}
                  disabled={!canEdit}
                  onChange={(event) => setContentCategory(event.target.value)}
                >
                  <option value="">Manter categoria atual</option>
                  {CATEGORY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Avatar">
                <Select
                  value={avatarId}
                  disabled={!canEdit}
                  onChange={(event) => setAvatarId(event.target.value)}
                >
                  <option value="">Manter avatar atual</option>
                  {avatars.data?.map((avatar) => (
                    <option key={avatar.id} value={avatar.id}>
                      {avatar.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Voice ID" hint="Opcional.">
                <Input
                  value={voiceId}
                  disabled={!canEdit}
                  onChange={(event) => setVoiceId(event.target.value)}
                  placeholder="Novo voice_id"
                />
              </Field>
              <Field label="Agendar para">
                <Input
                  type="datetime-local"
                  value={scheduledFor}
                  disabled={!canEdit}
                  onChange={(event) => setScheduledFor(event.target.value)}
                />
              </Field>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" variant="primary" disabled={!canEdit || edit.isPending}>
                {edit.isPending ? "Salvando…" : "Salvar edição"}
              </Button>
              <ErrorText
                error={edit.error}
                fallback="Erro ao salvar edição."
                conflict="Esta peça foi publicada por outra pessoa — não pode mais ser editada."
              />
            </div>
          </form>
        </Card>

        <Card className="flex flex-col gap-4 p-4">
          <MicroLabel>Substituir asset</MicroLabel>
          {/* Stacked, not a row: the Field carries a hint under its control,
              so an `items-end` row aligns the button with the hint instead of
              with the file input it belongs to. Same shape as the edit form
              above, whose submit also sits below its fields. */}
          <form
            className="flex flex-col items-start gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (assetFile) replaceAsset.mutate(assetFile);
            }}
          >
            <div className="w-full max-w-80">
              <Field label="Novo asset" hint={`Substitui o asset de ${(PIECE_TYPE_LABELS[piece.type] ?? piece.type).toLowerCase()} desta peça.`}>
                <input
                  type="file"
                  disabled={!canEdit}
                  onChange={(event) => setAssetFile(event.target.files?.[0] ?? null)}
                  className={
                    "h-8 w-full min-w-0 text-[12px] text-[var(--text)] " +
                    "file:mr-3 file:h-8 file:rounded-[4px] file:border file:border-[var(--border)] " +
                    "file:bg-[var(--card-bg)] file:px-3 file:text-[13px] file:font-medium " +
                    "file:text-[var(--text-h)] file:cursor-pointer"
                  }
                />
              </Field>
            </div>
            <Button
              type="submit"
              disabled={!canEdit || !assetFile || replaceAsset.isPending}
            >
              {replaceAsset.isPending ? "Enviando…" : "Substituir"}
            </Button>
            <ErrorText
              error={replaceAsset.error}
              fallback="Erro ao substituir asset."
              conflict="Esta peça foi publicada por outra pessoa — o asset não pode mais ser substituído."
            />
          </form>
        </Card>
      </RequireRole>

      <Section label="Legenda">
        <CaptionEditor
          pieceId={Number(id)}
          canEdit={canApprove() && piece.status !== "posted"}
        />
        <Link
          to={`/pieces/${id}/compose`}
          className="inline-flex items-center gap-1 self-start text-[12px] text-[var(--text)] no-underline hover:text-[var(--text-h)] hover:underline"
        >
          Abrir no composer para escrever por canal e ver a prévia
          <ArrowUpRight size={13} aria-hidden />
        </Link>
      </Section>

      <Section label="Publicações">
        <Card className="p-4">
          {piece.publications.length === 0 ? (
            <p className="m-0 text-[13px] text-[var(--text)]">
              Nenhuma publicação disparada para esta peça.
            </p>
          ) : (
            <div className="flex flex-col gap-2">
              {piece.publications.map((publication) => (
                <div
                  key={publication.id}
                  className="flex flex-wrap items-center gap-2 text-[13px]"
                >
                  <PlatformIcon platform={publication.platform as Platform} size={14} />
                  <span className="w-24 text-[var(--text-h)]">{publication.platform}</span>
                  <PublicationChip status={publication.status} />
                  {publication.error_message ? (
                    <span className="text-[12px] text-bad">{publication.error_message}</span>
                  ) : null}
                  {publication.platform_post_url ? (
                    <a
                      href={publication.platform_post_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-[12px] text-[var(--text)] no-underline hover:text-[var(--text-h)] hover:underline"
                    >
                      Ver publicação
                      <ArrowUpRight size={13} aria-hidden />
                    </a>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </Card>
      </Section>

      <Section label="Histórico">
        <AuditLogList
          entries={history.data}
          isLoading={history.isLoading}
          isError={history.isError}
          error={history.error}
          emptyHint="Nada foi registrado para esta peça ainda."
        />
      </Section>
    </SettingsPage>
  );
}
