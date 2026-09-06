import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { apiClient, apiErrorStatus } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { DataTable, type Column } from "../../components/settings/DataTable";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select } from "../../components/settings/Controls";
import { EntityChip } from "../../components/settings/EntityChip";
import type { Provider, ProviderCreatePayload } from "../../lib/types";

const KIND_LABEL: Record<Provider["kind"], string> = {
  image: "Imagem",
  video: "Vídeo",
  voice: "Voz",
};

const PROVIDER_LABEL: Record<Provider["provider"], string> = {
  wavespeed: "Wavespeed",
  falai: "fal.ai",
  gemini: "Gemini",
  elevenlabs: "ElevenLabs",
};

/** Priority cell: editable in place, but saying what it did.
 *
 * The old cell fired the mutation on blur and showed nothing at all, so a
 * failed save was indistinguishable from a successful one.
 */
function PriorityCell({ provider }: { provider: Provider }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(String(provider.priority));
  const [saved, setSaved] = useState(false);
  const savedTimeoutRef = useRef<number | undefined>(undefined);

  // Adjusting state during render (not in an effect): `value` seeded once
  // from `provider.priority` never picked up a value the server normalised —
  // a refetch after this row's own save, or after ANY other provider's save
  // invalidates the same shared query, passes down a new `provider` prop
  // that this local edit buffer needs to track. `syncedPriority` is what
  // makes this a one-time reset per actual server value instead of clobbering
  // an in-progress edit on every unrelated re-render.
  const [syncedPriority, setSyncedPriority] = useState(provider.priority);
  if (provider.priority !== syncedPriority) {
    setSyncedPriority(provider.priority);
    setValue(String(provider.priority));
  }

  const update = useMutation({
    mutationFn: (priority: number) =>
      apiClient.put<Provider>(`/content/ui/config/providers/${provider.id}`, { priority }),
    onSuccess: () => {
      setSaved(true);
      // Clear any still-pending "salvo" reset from a previous save on this
      // same cell before scheduling a new one — otherwise two saves in quick
      // succession race and the earlier timeout can turn "salvo" back off
      // right after the second save just turned it on.
      window.clearTimeout(savedTimeoutRef.current);
      savedTimeoutRef.current = window.setTimeout(() => setSaved(false), 1600);
      queryClient.invalidateQueries({ queryKey: ["config", "providers"] });
    },
    onError: () => setValue(String(provider.priority)),
  });

  useEffect(() => {
    return () => window.clearTimeout(savedTimeoutRef.current);
  }, []);

  return (
    <span className="inline-flex items-center gap-2 justify-end">
      <Input
        type="number"
        value={value}
        disabled={!provider.is_active || update.isPending}
        aria-label={`Prioridade de ${PROVIDER_LABEL[provider.provider]}`}
        title="Número menor é tentado primeiro entre provedores do mesmo tipo"
        // [&]:w-20, not plain w-20: Controls.tsx's CONTROL sets `w-full`, and
        // cn() puts this className last in the string, but that decides
        // nothing — Tailwind emits both as plain utilities and w-full sorts
        // after w-20 in the generated stylesheet, so w-full wins regardless
        // of argument order (see cn.ts). The arbitrary-variant form compiles
        // into a separate, later block of the utilities layer, so it wins on
        // CSS source order instead of relying on one that doesn't apply here.
        className="[&]:w-20 text-right font-mono"
        onChange={(event) => setValue(event.target.value)}
        onBlur={() => {
          // An empty/whitespace field is Number("") === 0, not NaN — left
          // unguarded, clearing the input and tabbing away would silently
          // save priority 0 and jump this provider to the front of the
          // queue. Treat it as "no change" and restore the server value
          // instead of coercing it to zero.
          if (value.trim() === "") {
            setValue(String(provider.priority));
            return;
          }
          const next = Number(value);
          if (!Number.isNaN(next) && next !== provider.priority) update.mutate(next);
        }}
      />
      <span className="w-14 text-[11px] text-[var(--text)]" aria-live="polite">
        {update.isPending ? "salvando…" : saved ? "salvo" : update.isError ? "falhou" : ""}
      </span>
    </span>
  );
}

export function Providers() {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [kind, setKind] = useState<Provider["kind"]>("image");
  const [providerName, setProviderName] = useState<Provider["provider"]>("falai");
  const [credentials, setCredentials] = useState("");
  const [priority, setPriority] = useState(0);

  const providers = useQuery({
    queryKey: ["config", "providers"],
    queryFn: () => apiClient.get<Provider[]>("/content/ui/config/providers"),
  });

  const create = useMutation({
    mutationFn: (payload: ProviderCreatePayload) =>
      apiClient.post<Provider>("/content/ui/config/providers", payload),
    onSuccess: () => {
      setCredentials("");
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "providers"] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Provider>(`/content/ui/config/providers/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "providers"] }),
  });

  const invalidCredentials = apiErrorStatus(create.error) === 422;
  // Any OTHER failure used to be silent — the button reverted and the drawer
  // just sat there. 422 keeps its own message (shown on the Field itself,
  // below); everything else gets this generic fallback.
  const createErrorMessage =
    create.isError && !invalidCredentials
      ? "Não foi possível adicionar o provedor. Tente novamente."
      : null;

  function closeDrawer() {
    setDrawerOpen(false);
    setKind("image");
    setProviderName("falai");
    setCredentials("");
    setPriority(0);
    create.reset();
  }

  const columns: Array<Column<Provider>> = [
    { key: "kind", header: "Tipo", width: "8rem", render: (row) => KIND_LABEL[row.kind] },
    {
      key: "provider",
      header: "Provedor",
      render: (row) => <span className="font-medium">{PROVIDER_LABEL[row.provider]}</span>,
    },
    {
      key: "priority",
      header: "Prioridade",
      align: "right",
      width: "13rem",
      render: (row) => <PriorityCell provider={row} />,
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
      title="Provedores"
      description="Serviços de geração de imagem, vídeo e voz. Dentro de um mesmo tipo, o de menor prioridade é tentado primeiro."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button variant="primary" onClick={() => setDrawerOpen(true)}>
            <Plus size={15} />
            Adicionar provedor
          </Button>
        </RequireRole>
      }
    >
      <DataTable
        columns={columns}
        rows={providers.data}
        rowKey={(row) => row.id}
        isLoading={providers.isLoading}
        isError={providers.isError}
        error={providers.error}
        emptyTitle="Nenhum provedor configurado"
        emptyHint="Sem provedor, a automação não consegue gerar conteúdo."
      />

      <Drawer
        open={drawerOpen}
        onClose={closeDrawer}
        title="Adicionar provedor"
        description="A credencial é enviada ao servidor e não volta para esta tela."
      >
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({
              kind,
              provider: providerName,
              credentials,
              config: {},
              priority,
            });
          }}
        >
          <Field label="Tipo">
            <Select
              value={kind}
              onChange={(event) => setKind(event.target.value as Provider["kind"])}
            >
              <option value="image">Imagem</option>
              <option value="video">Vídeo</option>
              <option value="voice">Voz</option>
            </Select>
          </Field>
          <Field label="Provedor">
            <Select
              value={providerName}
              onChange={(event) => setProviderName(event.target.value as Provider["provider"])}
            >
              <option value="wavespeed">Wavespeed</option>
              <option value="falai">fal.ai</option>
              <option value="gemini">Gemini</option>
              <option value="elevenlabs">ElevenLabs</option>
            </Select>
          </Field>
          <Field
            label="Chave de API"
            error={invalidCredentials ? "Credencial inválida para este provedor." : null}
          >
            <Input
              type="password"
              // A provider API key, not the operator's own password — see
              // the note on the same field in SocialAccounts.tsx for why
              // this is "new-password" and not "off".
              autoComplete="new-password"
              value={credentials}
              onChange={(event) => setCredentials(event.target.value)}
              placeholder="Chave de API"
              required
            />
          </Field>
          <Field
            label="Prioridade"
            hint="Número menor é tentado primeiro entre provedores do mesmo tipo."
          >
            <Input
              type="number"
              value={priority}
              onChange={(event) => setPriority(Number(event.target.value))}
            />
          </Field>

          {createErrorMessage ? (
            <p className="m-0 text-[12px] text-bad">{createErrorMessage}</p>
          ) : null}

          <div className="flex items-center gap-2">
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending || !credentials.trim()}
            >
              {create.isPending ? "Adicionando…" : "Adicionar"}
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
