import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { apiClient } from "../lib/apiClient";
import { Button } from "./ui/Button";
import { Card, MicroLabel } from "./ui/Card";
import { PlatformIcon, type Platform } from "./ui/PlatformIcon";
import { cn } from "./ui/cn";

interface ResolvedCaption {
  platform: string;
  body: string;
  source: "override" | "global" | "generation_prompt";
  length: number;
  caption_max: number;
  over_limit: boolean;
}

interface CaptionRow {
  platform: string | null;
  title: string | null;
  body: string | null;
  hashtags: string[];
  link_url: string | null;
  is_override: boolean;
}

/** The copy that gets published with a piece.
 *
 * Until this existed the adapters published `generation_prompt` — the
 * image-generation prompt — as the visible post body, and Instagram and
 * Facebook posted with no text at all. The per-platform rows below come from
 * the same resolution the publish dispatcher uses, so what is shown here is
 * what actually goes out.
 */
export function CaptionEditor({
  pieceId,
  canEdit,
}: {
  pieceId: number;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const [body, setBody] = useState("");
  const [dirty, setDirty] = useState(false);

  const captions = useQuery({
    queryKey: ["piece", String(pieceId), "captions"],
    queryFn: () =>
      apiClient.get<CaptionRow[]>(`/content/ui/pieces/${pieceId}/captions`),
  });

  const resolved = useQuery({
    queryKey: ["piece", String(pieceId), "captions", "resolved"],
    queryFn: () =>
      apiClient.get<ResolvedCaption[]>(
        `/content/ui/pieces/${pieceId}/captions/resolved`,
      ),
  });

  const globalRow = captions.data?.find((row) => row.platform === null);

  // Only seed the textarea from the server while the user has not typed —
  // otherwise a background refetch would discard an in-progress edit.
  useEffect(() => {
    if (!dirty && globalRow) setBody(globalRow.body ?? "");
  }, [globalRow, dirty]);

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["piece", String(pieceId)] });
  }

  const save = useMutation({
    mutationFn: () =>
      apiClient.put(`/content/ui/pieces/${pieceId}/captions`, {
        platform: null,
        body,
        hashtags: globalRow?.hashtags ?? [],
      }),
    onSuccess: () => {
      setDirty(false);
      invalidate();
    },
  });

  const suggest = useMutation({
    mutationFn: () =>
      apiClient.post<CaptionRow>(
        `/content/ui/pieces/${pieceId}/captions/suggest`,
        { platform: null },
      ),
    onSuccess: (suggestion) => {
      // Fills the box without saving: the human still approves.
      setBody(suggestion.body ?? "");
      setDirty(true);
    },
  });

  return (
    <Card className="p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <MicroLabel>Legenda publicada</MicroLabel>
        {canEdit ? (
          <Button
            size="sm"
            onClick={() => suggest.mutate()}
            disabled={suggest.isPending}
          >
            <Sparkles size={13} />
            {suggest.isPending ? "Escrevendo…" : "Escrever com IA"}
          </Button>
        ) : null}
      </div>

      <textarea
        value={body}
        disabled={!canEdit}
        onChange={(event) => {
          setBody(event.target.value);
          setDirty(true);
        }}
        rows={4}
        placeholder="Texto que acompanha a mídia quando ela for publicada."
        className="w-full resize-y rounded-[4px] border border-[var(--border)] bg-[var(--card-bg)] p-2 text-[13px] text-[var(--text-h)]"
      />

      {canEdit ? (
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={() => save.mutate()}
            disabled={!dirty || save.isPending}
          >
            {save.isPending ? "Salvando…" : "Salvar legenda"}
          </Button>
          {save.isError ? (
            <span className="text-[12px] text-bad">Não foi possível salvar.</span>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-1 pt-1 border-t border-[var(--border)]">
        <MicroLabel className="pt-2">Por canal</MicroLabel>
        {resolved.data?.map((row) => (
          <div
            key={row.platform}
            className="flex items-center gap-2 py-1 text-[12px]"
          >
            <PlatformIcon platform={row.platform as Platform} size={13} />
            <span className="w-20 text-[var(--text-h)]">{row.platform}</span>
            <span
              className={cn(
                "font-mono text-[11px]",
                row.over_limit ? "text-bad" : "text-[var(--text)]",
              )}
            >
              {row.length}/{row.caption_max}
            </span>
            {row.source === "generation_prompt" ? (
              // Worth calling out: this is the pre-caption fallback, i.e. the
              // image prompt would be published as the post text.
              <span className="text-warn">usando o prompt de geração</span>
            ) : row.source === "override" ? (
              <span className="text-[var(--text)]">texto próprio</span>
            ) : (
              <span className="text-[var(--text)]">legenda global</span>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
