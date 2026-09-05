import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/Feedback";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ScopeBar } from "../../components/settings/ScopeBar";
import { DataTable, type Column } from "../../components/settings/DataTable";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select, Textarea } from "../../components/settings/Controls";
import { EntityChip } from "../../components/settings/EntityChip";
import type { Avatar, Campaign, GenerationTemplate } from "../../lib/types";

const ASPECT_RATIO_PRESETS = ["9:16", "16:9", "1:1", "4:5"];

const TYPE_LABEL: Record<GenerationTemplate["type"], string> = {
  image: "Imagem",
  video: "Vídeo",
  audio: "Áudio",
};

export function GenerationTemplates() {
  const queryClient = useQueryClient();
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [type, setType] = useState<GenerationTemplate["type"]>("image");
  const [generationPrompt, setGenerationPrompt] = useState("");
  const [narrationScript, setNarrationScript] = useState("");
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
      apiClient.post<GenerationTemplate>(`/content/ui/config/campaigns/${campaignId}/templates`, {
        campaign_id: campaignId,
        type,
        generation_prompt: generationPrompt,
        narration_script: narrationScript || null,
        is_synthetic_media: false,
        aspect_ratio: effectiveAspectRatio,
        avatar_id: avatarId,
        voice_id: voiceId || null,
      }),
    onSuccess: () => {
      setGenerationPrompt("");
      setNarrationScript("");
      setAvatarId(null);
      setVoiceId("");
      setAspectRatio("9:16");
      setCustomAspectRatio("");
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "templates", campaignId] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete<GenerationTemplate>(`/content/ui/config/templates/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "templates", campaignId] }),
  });

  function closeDrawer() {
    setDrawerOpen(false);
    setType("image");
    setGenerationPrompt("");
    setNarrationScript("");
    setAspectRatio("9:16");
    setCustomAspectRatio("");
    setAvatarId(null);
    setVoiceId("");
    create.reset();
  }

  const columns: Array<Column<GenerationTemplate>> = [
    { key: "type", header: "Tipo", width: "8rem", render: (row) => TYPE_LABEL[row.type] },
    {
      key: "prompt",
      header: "Prompt",
      render: (row) => (
        // Prompts run long; one line with an ellipsis keeps rows the same
        // height, and the full text is in the title attribute.
        <span className="block max-w-xl truncate" title={row.generation_prompt ?? undefined}>
          {row.generation_prompt ?? "(sem prompt)"}
        </span>
      ),
    },
    {
      key: "aspect",
      header: "Proporção",
      width: "8rem",
      render: (row) => <span className="font-mono text-[12px]">{row.aspect_ratio}</span>,
    },
    {
      key: "status",
      header: "Status",
      width: "8rem",
      render: (row) => <EntityChip state={row.is_active ? "active" : "inactive"} />,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      width: "5rem",
      render: (row) => (
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={deactivate.isPending}
            actions={[
              {
                label: "Desativar",
                danger: true,
                disabled: !row.is_active,
                onConfirm: () => deactivate.mutate(row.id),
              },
            ]}
          />
        </RequireRole>
      ),
    },
  ];

  return (
    <SettingsPage
      title="Templates de geração"
      description="O molde de cada peça que a automação gera para uma campanha."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button
            variant="primary"
            disabled={campaignId === null}
            onClick={() => setDrawerOpen(true)}
          >
            <Plus size={15} />
            Novo template
          </Button>
        </RequireRole>
      }
    >
      <ScopeBar
        label="Campanha"
        placeholder="Selecione uma campanha"
        options={campaigns.data?.map((campaign) => ({ id: campaign.id, label: campaign.name }))}
        value={campaignId}
        onChange={setCampaignId}
        isLoading={campaigns.isLoading}
      />

      {campaignId === null ? (
        <Card>
          <EmptyState
            title="Escolha uma campanha"
            hint="Cada campanha tem seus próprios templates. Selecione uma acima para ver os dela."
          />
        </Card>
      ) : (
        <DataTable
          columns={columns}
          rows={templates.data}
          rowKey={(row) => row.id}
          isLoading={templates.isLoading}
          isError={templates.isError}
          emptyTitle="Nenhum template nesta campanha"
          emptyHint="Sem template, a automação não sabe o que gerar."
        />
      )}

      <Drawer
        open={drawerOpen}
        onClose={closeDrawer}
        title="Novo template"
        description="Define o que a automação gera para cada peça desta campanha."
      >
        <form
          className="flex flex-col gap-4 items-stretch flex-nowrap m-0"
          onSubmit={(event) => {
            event.preventDefault();
            if (campaignId !== null && generationPrompt.trim() && effectiveAspectRatio.trim()) {
              create.mutate();
            }
          }}
        >
          <Field label="Tipo">
            <Select
              value={type}
              onChange={(event) =>
                setType(event.target.value as GenerationTemplate["type"])
              }
            >
              <option value="image">Imagem</option>
              <option value="video">Vídeo</option>
              <option value="audio">Áudio</option>
            </Select>
          </Field>
          <Field label="Prompt de geração" hint="O que o provedor deve criar.">
            <Textarea
              value={generationPrompt}
              onChange={(event) => setGenerationPrompt(event.target.value)}
              placeholder="Prompt de geração"
              required
            />
          </Field>
          <Field
            label="Roteiro de narração"
            hint="Opcional. Texto para a narração em áudio e vídeo — sem isso, o prompt de geração é usado."
          >
            <Textarea
              value={narrationScript}
              onChange={(event) => setNarrationScript(event.target.value)}
              placeholder="Roteiro de narração"
            />
          </Field>
          <Field label="Proporção">
            <Select value={aspectRatio} onChange={(event) => setAspectRatio(event.target.value)}>
              {ASPECT_RATIO_PRESETS.map((preset) => (
                <option key={preset} value={preset}>
                  {preset}
                </option>
              ))}
              <option value="custom">Outra…</option>
            </Select>
          </Field>
          {aspectRatio === "custom" ? (
            <Field label="Proporção personalizada">
              <Input
                value={customAspectRatio}
                onChange={(event) => setCustomAspectRatio(event.target.value)}
                placeholder="ex: 21:9"
                required
              />
            </Field>
          ) : null}
          <Field label="Avatar">
            <Select
              value={avatarId ?? ""}
              onChange={(event) => setAvatarId(Number(event.target.value) || null)}
            >
              <option value="">Sem avatar</option>
              {avatars.data?.map((avatar) => (
                <option key={avatar.id} value={avatar.id}>
                  {avatar.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Voice ID"
            hint="Opcional. Identificador da voz no provedor — não há lista para escolher, é o código que o provedor fornece."
          >
            <Input
              value={voiceId}
              onChange={(event) => setVoiceId(event.target.value)}
              placeholder="ID da voz no provedor"
            />
          </Field>
          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button
              type="submit"
              variant="primary"
              disabled={
                create.isPending ||
                campaignId === null ||
                !generationPrompt.trim() ||
                !effectiveAspectRatio.trim()
              }
            >
              {create.isPending ? "Criando…" : "Criar template"}
            </Button>
            <Button type="button" variant="ghost" onClick={closeDrawer}>
              Cancelar
            </Button>
          </div>
        </form>
      </Drawer>
    </SettingsPage>
  );
}
