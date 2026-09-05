import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/Feedback";
import {
  PLATFORMS,
  PLATFORM_LABEL,
  PlatformIcon,
  type Platform,
} from "../../components/ui/PlatformIcon";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ScopeBar } from "../../components/settings/ScopeBar";
import { DataTable, type Column } from "../../components/settings/DataTable";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select } from "../../components/settings/Controls";
import { EntityChip, type EntityState } from "../../components/settings/EntityChip";
import type { Client, SocialAccount, SocialAccountCreatePayload } from "../../lib/types";

export function SocialAccounts() {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [platform, setPlatform] = useState<Platform>("instagram");
  const [externalAccountId, setExternalAccountId] = useState("");
  const [credentials, setCredentials] = useState("");

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const accounts = useQuery({
    queryKey: ["config", "social-accounts", clientId],
    queryFn: () =>
      apiClient.get<SocialAccount[]>(`/content/ui/config/clients/${clientId}/social-accounts`),
    enabled: clientId !== null,
  });

  const create = useMutation({
    mutationFn: (payload: SocialAccountCreatePayload) =>
      apiClient.post<SocialAccount>("/content/ui/config/social-accounts", payload),
    onSuccess: () => {
      setExternalAccountId("");
      setCredentials("");
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "social-accounts", clientId] });
    },
  });

  const revoke = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete<SocialAccount>(`/content/ui/config/social-accounts/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "social-accounts", clientId] }),
  });

  // Mirrors the convention in ApprovalRules.tsx/Clients.tsx/Providers.tsx:
  // without this, a failed create just reverts the button with no
  // explanation and the drawer sits there looking like nothing happened.
  const createErrorMessage = create.isError
    ? "Não foi possível conectar a conta. Tente novamente."
    : null;

  function closeDrawer() {
    setDrawerOpen(false);
    setPlatform("instagram");
    setExternalAccountId("");
    setCredentials("");
    create.reset();
  }

  const columns: Array<Column<SocialAccount>> = [
    {
      key: "platform",
      header: "Plataforma",
      width: "12rem",
      render: (account) => (
        <span className="inline-flex items-center gap-2">
          <PlatformIcon platform={account.platform as Platform} size={14} />
          {PLATFORM_LABEL[account.platform as Platform] ?? account.platform}
        </span>
      ),
    },
    {
      key: "account",
      header: "Conta",
      render: (account) => (
        <span className="font-mono text-[12px]">{account.external_account_id}</span>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "8rem",
      render: (account) => <EntityChip state={account.status as EntityState} />,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      width: "5rem",
      render: (account) => (
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={revoke.isPending}
            actions={[
              {
                label: "Revogar",
                danger: true,
                disabled: account.status !== "active",
                onConfirm: () => revoke.mutate(account.id),
              },
            ]}
          />
        </RequireRole>
      ),
    },
  ];

  return (
    <SettingsPage
      title="Contas sociais"
      description="As contas onde as peças aprovadas são publicadas, por cliente."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button
            variant="primary"
            disabled={clientId === null}
            onClick={() => setDrawerOpen(true)}
          >
            <Plus size={15} />
            Conectar conta
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
            hint="As contas sociais são organizadas por cliente. Selecione um acima para ver as dele."
          />
        </Card>
      ) : (
        <DataTable
          columns={columns}
          rows={accounts.data}
          rowKey={(account) => account.id}
          isLoading={accounts.isLoading}
          isError={accounts.isError}
          error={accounts.error}
          emptyTitle="Nenhuma conta conectada"
          emptyHint="Conecte uma conta para que este cliente possa publicar."
        />
      )}

      <Drawer
        open={drawerOpen}
        onClose={closeDrawer}
        title="Conectar conta"
        description="A credencial é enviada ao servidor e não volta para esta tela."
      >
        <form
          className="flex flex-col gap-4 items-stretch flex-nowrap m-0"
          onSubmit={(event) => {
            event.preventDefault();
            if (clientId === null) return;
            create.mutate({
              client_id: clientId,
              platform,
              external_account_id: externalAccountId,
              credentials,
            });
          }}
        >
          <Field label="Plataforma">
            <Select
              value={platform}
              onChange={(event) => setPlatform(event.target.value as Platform)}
            >
              {PLATFORMS.map((option) => (
                <option key={option} value={option}>
                  {PLATFORM_LABEL[option]}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Identificador da conta"
            hint="O id que a plataforma usa para esta conta, não o @ de exibição."
          >
            <Input
              value={externalAccountId}
              onChange={(event) => setExternalAccountId(event.target.value)}
              placeholder="ID da conta na plataforma"
              required
            />
          </Field>
          <Field label="Credencial de acesso">
            <Input
              type="password"
              value={credentials}
              onChange={(event) => setCredentials(event.target.value)}
              placeholder="Token ou chave de acesso"
              required
            />
          </Field>

          {createErrorMessage ? (
            <p className="m-0 text-[12px] text-bad">{createErrorMessage}</p>
          ) : null}

          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending || !externalAccountId.trim() || !credentials.trim()}
            >
              {create.isPending ? "Conectando…" : "Conectar"}
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
