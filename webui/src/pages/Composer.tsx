import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { AlertCircle, Check, Clock, Send, Sparkles } from "lucide-react";
import { apiClient, apiErrorStatus } from "../lib/apiClient";
import { parseUtc, toUtcParam } from "../lib/calendarDates";
import type { PieceDetail } from "../lib/types";
import { Button } from "../components/ui/Button";
import { Card, MicroLabel } from "../components/ui/Card";
import { EmptyState, Skeleton } from "../components/ui/Feedback";
import { PlatformIcon, PLATFORM_LABEL, type Platform } from "../components/ui/PlatformIcon";
import { ChannelPreview } from "../components/composer/ChannelPreview";
import { cn } from "../components/ui/cn";

interface TargetOption {
  social_account_id: number;
  platform: string;
  label: string;
  selected: boolean;
}
interface TargetsRead {
  is_targeted: boolean;
  options: TargetOption[];
}
interface ChannelValidation {
  platform: string;
  social_account_id: number | null;
  label: string;
  ready: boolean;
  issues: Array<{ code: string; message: string }>;
  caption_length: number;
  caption_max: number;
}
interface CaptionRow {
  platform: string | null;
  title: string | null;
  body: string | null;
  hashtags: string[];
  link_url: string | null;
  is_override: boolean;
}

const GLOBAL = "__global__";

export function Composer() {
  const { id } = useParams<{ id: string }>();
  const pieceId = Number(id);
  const queryClient = useQueryClient();

  const [tab, setTab] = useState<string>(GLOBAL);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);

  const piece = useQuery({
    queryKey: ["piece", String(pieceId)],
    queryFn: () => apiClient.get<PieceDetail>(`/content/ui/pieces/${pieceId}`),
  });
  const captions = useQuery({
    queryKey: ["piece", String(pieceId), "captions"],
    queryFn: () => apiClient.get<CaptionRow[]>(`/content/ui/pieces/${pieceId}/captions`),
  });
  const targets = useQuery({
    queryKey: ["piece", String(pieceId), "targets"],
    queryFn: () => apiClient.get<TargetsRead>(`/content/ui/pieces/${pieceId}/targets`),
  });
  const validation = useQuery({
    queryKey: ["piece", String(pieceId), "validation"],
    queryFn: () =>
      apiClient.get<ChannelValidation[]>(`/content/ui/pieces/${pieceId}/validation`),
  });

  // Seed each tab's textarea from the server only while untouched, so a
  // background refetch never eats an in-progress edit.
  useEffect(() => {
    if (!captions.data) return;
    setDraft((current) => {
      const next = { ...current };
      for (const row of captions.data) {
        const key = row.platform ?? GLOBAL;
        if (next[key] === undefined) next[key] = row.body ?? "";
      }
      if (next[GLOBAL] === undefined) next[GLOBAL] = "";
      return next;
    });
  }, [captions.data]);

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["piece", String(pieceId)] });
  }

  const saveCaption = useMutation({
    mutationFn: (platform: string) =>
      apiClient.put(`/content/ui/pieces/${pieceId}/captions`, {
        platform: platform === GLOBAL ? null : platform,
        body: draft[platform] ?? "",
      }),
    onSuccess: invalidate,
  });

  const useGlobal = useMutation({
    mutationFn: (platform: string) =>
      apiClient.delete(`/content/ui/pieces/${pieceId}/captions/${platform}`),
    onSuccess: (_data, platform) => {
      setDraft((current) => {
        const next = { ...current };
        delete next[platform];
        return next;
      });
      invalidate();
    },
  });

  const suggest = useMutation({
    mutationFn: (platform: string) =>
      apiClient.post<CaptionRow>(`/content/ui/pieces/${pieceId}/captions/suggest`, {
        platform: platform === GLOBAL ? null : platform,
      }),
    onSuccess: (row, platform) =>
      setDraft((current) => ({ ...current, [platform]: row.body ?? "" })),
  });

  const setTargets = useMutation({
    mutationFn: (ids: number[]) =>
      apiClient.put(`/content/ui/pieces/${pieceId}/targets`, {
        social_account_ids: ids,
      }),
    onSuccess: invalidate,
  });

  const nextSlot = useMutation({
    mutationFn: async () => {
      const slot = await apiClient.get<{ scheduled_for: string }>(
        `/content/ui/pieces/${pieceId}/next-slot`,
      );
      await apiClient.patch(`/content/ui/pieces/${pieceId}/schedule`, {
        scheduled_for: toUtcParam(parseUtc(slot.scheduled_for)),
      });
      return slot;
    },
    onSuccess: (slot) => {
      setNotice(
        `Agendado para ${parseUtc(slot.scheduled_for).toLocaleString("pt-BR")}.`,
      );
      invalidate();
    },
  });

  const publish = useMutation({
    mutationFn: (ids: number[]) =>
      apiClient.post(`/content/ui/pieces/${pieceId}/publish`, {
        social_account_ids: ids,
      }),
    onSuccess: () => {
      setNotice("Publicação enfileirada.");
      invalidate();
    },
    onError: (error) => {
      setNotice(
        apiErrorStatus(error) === 422
          ? "Há canais com problemas — corrija antes de publicar."
          : "Não foi possível publicar.",
      );
    },
  });

  const selectedIds = useMemo(
    () =>
      (targets.data?.options ?? [])
        .filter((option) => option.selected)
        .map((option) => option.social_account_id),
    [targets.data],
  );

  const byPlatform = useMemo(() => {
    const map = new Map<string, ChannelValidation>();
    for (const row of validation.data ?? []) map.set(row.platform, row);
    return map;
  }, [validation.data]);

  const readyCount = (validation.data ?? []).filter((row) => row.ready).length;
  const issueCount = (validation.data ?? []).reduce(
    (total, row) => total + row.issues.length,
    0,
  );

  if (piece.isLoading) return <Skeleton className="h-[500px] w-full" />;
  if (piece.isError || !piece.data)
    return <EmptyState title="Não foi possível carregar a peça" />;

  const isPosted = piece.data.status === "posted";
  const tabs = [
    { key: GLOBAL, label: "Global", platform: null as Platform | null },
    ...(validation.data ?? []).map((row) => ({
      key: row.platform,
      label: PLATFORM_LABEL[row.platform as Platform] ?? row.platform,
      platform: row.platform as Platform,
    })),
  ];
  const activeValidation = tab === GLOBAL ? null : byPlatform.get(tab);
  const thumbnail = piece.data.assets.find((asset) => asset.signed_url)?.signed_url;
  const overrideRow = captions.data?.find((row) => row.platform === tab);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h1 className="m-0 text-[20px] font-semibold tracking-tight">
            Compor peça #{pieceId}
          </h1>
          <Link
            to={`/pieces/${pieceId}`}
            className="text-[12px] text-[var(--text)] hover:text-[var(--text-h)]"
          >
            ver detalhes
          </Link>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => nextSlot.mutate()} disabled={isPosted}>
            <Clock size={13} />
            Próximo horário livre
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => publish.mutate(selectedIds)}
            disabled={isPosted || publish.isPending || selectedIds.length === 0}
          >
            <Send size={13} />
            {publish.isPending ? "Publicando…" : "Publicar agora"}
          </Button>
        </div>
      </div>

      {notice ? (
        <div className="flex items-center justify-between gap-3 rounded-[4px] border border-[var(--border)] bg-[var(--card-bg)] px-3 py-2 text-[13px]">
          {notice}
          <button
            type="button"
            onClick={() => setNotice(null)}
            className="bg-transparent border-0 p-0 h-auto text-[var(--text)] underline cursor-pointer"
          >
            fechar
          </button>
        </div>
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-4">
        <div className="flex flex-col gap-3">
          <Card className="p-0 overflow-hidden">
            <div className="flex flex-wrap gap-1 border-b border-[var(--border)] p-2">
              {tabs.map((entry) => {
                const state = entry.key === GLOBAL ? null : byPlatform.get(entry.key);
                return (
                  <button
                    key={entry.key}
                    type="button"
                    onClick={() => setTab(entry.key)}
                    className={cn(
                      "inline-flex items-center gap-1.5 h-7 px-2.5 rounded-[4px] text-[12px] font-medium cursor-pointer border",
                      tab === entry.key
                        ? "bg-ink text-white border-transparent"
                        : "bg-transparent text-[var(--text)] border-transparent hover:bg-[var(--code-bg)]",
                    )}
                  >
                    {entry.platform ? (
                      <PlatformIcon
                        platform={entry.platform}
                        size={12}
                        brandColor={tab !== entry.key}
                      />
                    ) : null}
                    {entry.label}
                    {state ? (
                      state.ready ? (
                        <Check size={11} className="text-ok" />
                      ) : (
                        <AlertCircle size={11} className="text-warn" />
                      )
                    ) : null}
                  </button>
                );
              })}
            </div>

            <div className="flex flex-col gap-2 p-3">
              <div className="flex items-center justify-between gap-2">
                <MicroLabel>
                  {tab === GLOBAL ? "Legenda global" : `Texto para ${tab}`}
                </MicroLabel>
                <Button
                  size="sm"
                  onClick={() => suggest.mutate(tab)}
                  disabled={isPosted || suggest.isPending}
                >
                  <Sparkles size={12} />
                  {suggest.isPending ? "Escrevendo…" : "Escrever com IA"}
                </Button>
              </div>

              <textarea
                value={draft[tab] ?? ""}
                disabled={isPosted}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, [tab]: event.target.value }))
                }
                rows={6}
                placeholder={
                  tab === GLOBAL
                    ? "Texto usado por todos os canais que não tiverem o próprio."
                    : "Deixe em branco e salve a global para este canal usar o texto compartilhado."
                }
                className="w-full resize-y rounded-[4px] border border-[var(--border)] bg-[var(--card-bg)] p-2 text-[13px] text-[var(--text-h)]"
              />

              <div className="flex flex-wrap items-center justify-between gap-2">
                <span
                  className={cn(
                    "font-mono text-[11px]",
                    activeValidation && activeValidation.caption_length > activeValidation.caption_max
                      ? "text-bad"
                      : "text-[var(--text)]",
                  )}
                >
                  {activeValidation
                    ? `${activeValidation.caption_length}/${activeValidation.caption_max}`
                    : `${(draft[tab] ?? "").length} caracteres`}
                </span>
                <div className="flex items-center gap-2">
                  {tab !== GLOBAL && overrideRow?.is_override ? (
                    <Button
                      size="sm"
                      onClick={() => useGlobal.mutate(tab)}
                      disabled={isPosted}
                    >
                      Usar texto global
                    </Button>
                  ) : null}
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => saveCaption.mutate(tab)}
                    disabled={isPosted || saveCaption.isPending}
                  >
                    {saveCaption.isPending ? "Salvando…" : "Salvar"}
                  </Button>
                </div>
              </div>

              {activeValidation && activeValidation.issues.length > 0 ? (
                <ul className="m-0 flex flex-col gap-1 list-none p-0 max-w-none">
                  {activeValidation.issues.map((issue) => (
                    <li
                      key={issue.code}
                      className="flex items-start gap-1.5 text-[12px] text-warn"
                    >
                      <AlertCircle size={12} className="mt-0.5 shrink-0" />
                      {issue.message}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </Card>

          <Card className="p-3 flex flex-col gap-2">
            <MicroLabel>Canais</MicroLabel>
            {targets.data?.options.length === 0 ? (
              <p className="m-0 text-[12px] text-[var(--text)]">
                Este cliente não tem contas sociais conectadas.
              </p>
            ) : (
              <>
                <div className="flex flex-wrap gap-1.5">
                  {targets.data?.options.map((option) => (
                    <button
                      key={option.social_account_id}
                      type="button"
                      disabled={isPosted}
                      onClick={() => {
                        const next = option.selected
                          ? selectedIds.filter((x) => x !== option.social_account_id)
                          : [...selectedIds, option.social_account_id];
                        setTargets.mutate(next);
                      }}
                      className={cn(
                        "inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full border text-[12px] cursor-pointer",
                        option.selected
                          ? "bg-[var(--code-bg)] text-[var(--text-h)] border-[var(--border)]"
                          : "bg-transparent text-[var(--text)] border-[var(--border)] opacity-60",
                      )}
                    >
                      <PlatformIcon platform={option.platform as Platform} size={12} />
                      {option.label}
                      {option.selected ? <Check size={11} className="text-ok" /> : null}
                    </button>
                  ))}
                </div>
                <p className="m-0 text-[11px] text-[var(--text)]">
                  {targets.data?.is_targeted
                    ? "Só os canais marcados recebem esta peça."
                    : "Sem seleção específica: a peça vai para todas as contas ativas."}
                </p>
              </>
            )}
          </Card>
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-2">
            <MicroLabel>Prévia</MicroLabel>
            <span
              className={cn(
                "font-mono text-[10px]",
                issueCount > 0 ? "text-warn" : "text-ok",
              )}
            >
              {issueCount > 0
                ? `${issueCount} PROBLEMA${issueCount > 1 ? "S" : ""}`
                : `${readyCount} CANAIS PRONTOS`}
            </span>
          </div>
          {(validation.data ?? []).map((row) => (
            <ChannelPreview
              key={row.platform}
              platform={row.platform as Platform}
              accountLabel={row.label}
              body={
                draft[row.platform] !== undefined && draft[row.platform] !== ""
                  ? draft[row.platform]
                  : draft[GLOBAL] ?? ""
              }
              thumbnailUrl={thumbnail}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
