import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageOff, Plus } from "lucide-react";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState, Skeleton } from "../../components/ui/Feedback";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ScopeBar } from "../../components/settings/ScopeBar";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select } from "../../components/settings/Controls";
import { EntityChip } from "../../components/settings/EntityChip";
import type { Avatar, Client } from "../../lib/types";

const VOICE_PROVIDERS = [
  { value: "elevenlabs", label: "ElevenLabs" },
  { value: "gemini", label: "Gemini" },
];

function AvatarCard({
  avatar,
  onDeactivate,
  pending,
}: {
  avatar: Avatar;
  onDeactivate: () => void;
  pending: boolean;
}) {
  const [broken, setBroken] = useState(false);

  return (
    <Card className="overflow-hidden flex flex-col">
      <div className="aspect-[4/5] bg-[var(--code-bg)] flex items-center justify-center">
        {broken || !avatar.reference_image_url ? (
          <ImageOff size={20} className="text-[var(--text)]" aria-hidden />
        ) : (
          <img
            src={avatar.reference_image_url}
            alt={`Imagem de referência de ${avatar.name}`}
            loading="lazy"
            onError={() => setBroken(true)}
            className="w-full h-full object-cover"
          />
        )}
      </div>
      <div className="flex items-start justify-between gap-2 px-3 py-2.5">
        <div className="min-w-0">
          <p className="m-0 truncate text-[13px] font-medium text-[var(--text-h)]">
            {avatar.name}
          </p>
          <EntityChip
            state={avatar.is_active ? "active" : "inactive"}
            className="mt-1.5"
          />
        </div>
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={pending}
            actions={[
              {
                label: "Desativar",
                danger: true,
                disabled: !avatar.is_active,
                onConfirm: onDeactivate,
              },
            ]}
          />
        </RequireRole>
      </div>
    </Card>
  );
}

export function Avatars() {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [name, setName] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [voiceProvider, setVoiceProvider] = useState("");
  const [voiceId, setVoiceId] = useState("");

  // Mirrors previewUrl after every commit so the unmount-only effect below
  // can read the latest object URL without listing previewUrl as its own
  // dependency — doing that would re-run the cleanup (and revoke) on every
  // change, doubly revoking the URL that the file-input's own onChange (or
  // resetForm) already revoked.
  const previewUrlRef = useRef<string | null>(null);
  useEffect(() => {
    previewUrlRef.current = previewUrl;
  }, [previewUrl]);

  useEffect(() => {
    return () => {
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, []);

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const avatars = useQuery({
    queryKey: ["config", "avatars", clientId],
    queryFn: () => apiClient.get<Avatar[]>(`/content/ui/config/clients/${clientId}/avatars`),
    enabled: clientId !== null,
  });

  function resetForm() {
    setName("");
    setImageFile(null);
    // Object URLs are leaked memory until revoked, and the form can be filled
    // and cancelled repeatedly without ever submitting.
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setVoiceProvider("");
    setVoiceId("");
  }

  const create = useMutation({
    // uploadFile, not post: the avatar carries a file, and the client has a
    // separate method that sends FormData without forcing a JSON content type.
    mutationFn: (formData: FormData) =>
      apiClient.uploadFile<Avatar>("/content/ui/config/avatars", formData),
    onSuccess: () => {
      resetForm();
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "avatars", clientId] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Avatar>(`/content/ui/config/avatars/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "avatars", clientId] }),
  });

  // Shared by the Drawer's onClose (Esc + backdrop) and the Cancelar button
  // so every exit path clears the form, revokes the preview URL, and drops
  // any stale mutation error the same way — modeled on closeDrawer() in
  // Clients.tsx.
  function closeDrawer() {
    setDrawerOpen(false);
    resetForm();
    create.reset();
  }

  return (
    <SettingsPage
      title="Avatares"
      description="As pessoas sintéticas que aparecem nas peças de vídeo, por cliente."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button
            variant="primary"
            disabled={clientId === null}
            onClick={() => setDrawerOpen(true)}
          >
            <Plus size={15} />
            Novo avatar
          </Button>
        </RequireRole>
      }
    >
      <ScopeBar
        label="Cliente"
        placeholder="Selecione um cliente"
        options={clients.data?.map((client) => ({ id: client.id, label: client.name }))}
        value={clientId}
        onChange={setClientId}
        isLoading={clients.isLoading}
      />

      {clientId === null ? (
        <Card>
          <EmptyState
            title="Escolha um cliente"
            hint="Os avatares são organizados por cliente. Selecione um acima para ver os dele."
          />
        </Card>
      ) : avatars.isLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="aspect-[4/5] w-full" />
          ))}
        </div>
      ) : avatars.isError ? (
        <Card>
          <EmptyState
            title="Não foi possível carregar"
            hint="Verifique a conexão com o servidor e tente novamente."
          />
        </Card>
      ) : !avatars.data || avatars.data.length === 0 ? (
        <Card>
          <EmptyState
            title="Nenhum avatar cadastrado"
            hint="Crie um avatar para poder usá-lo nos templates de vídeo deste cliente."
          />
        </Card>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {avatars.data.map((avatar) => (
            <AvatarCard
              key={avatar.id}
              avatar={avatar}
              pending={deactivate.isPending}
              onDeactivate={() => deactivate.mutate(avatar.id)}
            />
          ))}
        </div>
      )}

      <Drawer
        open={drawerOpen}
        onClose={closeDrawer}
        title="Novo avatar"
        description="A imagem de referência define a aparência usada na geração."
      >
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (clientId === null || !imageFile) return;
            const formData = new FormData();
            formData.append("client_id", String(clientId));
            formData.append("name", name);
            if (voiceProvider) formData.append("voice_provider", voiceProvider);
            if (voiceId) formData.append("voice_id", voiceId);
            formData.append("file", imageFile);
            create.mutate(formData);
          }}
        >
          <Field label="Nome">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Nome do avatar"
              required
            />
          </Field>

          {/* Spans rather than divs: this sits inside Field's <label>, which
              only accepts phrasing content. `flex` on a span behaves the same. */}
          <Field label="Imagem de referência" hint="JPG ou PNG. É a aparência que a geração vai reproduzir.">
            <span className="flex items-center gap-3">
              <span className="w-20 h-24 shrink-0 rounded-[4px] border border-[var(--border)] bg-[var(--code-bg)] flex items-center justify-center overflow-hidden">
                {previewUrl ? (
                  <img
                    src={previewUrl}
                    alt="Prévia"
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <ImageOff size={18} className="text-[var(--text)]" aria-hidden />
                )}
              </span>
              <input
                type="file"
                accept="image/*"
                required
                onChange={(event) => {
                  const file = event.target.files?.[0] ?? null;
                  if (previewUrl) URL.revokeObjectURL(previewUrl);
                  setImageFile(file);
                  setPreviewUrl(file ? URL.createObjectURL(file) : null);
                }}
                className={
                  // Deliberately NOT the shared `Input`: a file input is a
                  // label plus a browser-drawn button, not a text box, and
                  // giving it the control's border and padding would frame
                  // the button inside a second box. Only the file: button
                  // itself is styled to match the other controls.
                  "flex-1 min-w-0 h-8 " +
                  "text-[12px] text-[var(--text)] " +
                  "file:mr-3 file:h-8 file:px-3 file:rounded-[4px] file:border file:border-[var(--border)] " +
                  "file:bg-[var(--card-bg)] file:text-[13px] file:font-medium file:text-[var(--text-h)] " +
                  "file:cursor-pointer"
                }
              />
            </span>
          </Field>

          <Field label="Provedor de voz" hint="Opcional. Necessário apenas para peças com narração.">
            <Select
              value={voiceProvider}
              onChange={(event) => setVoiceProvider(event.target.value)}
            >
              <option value="">Nenhum</option>
              {VOICE_PROVIDERS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Voice ID" hint="Opcional. O código da voz no provedor escolhido.">
            <Input
              value={voiceId}
              onChange={(event) => setVoiceId(event.target.value)}
              placeholder="ID da voz no provedor"
            />
          </Field>

          <div className="flex items-center gap-2">
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending || clientId === null || !imageFile || !name.trim()}
            >
              {create.isPending ? "Criando…" : "Criar avatar"}
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
