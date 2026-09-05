import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { DataTable, type Column } from "../../components/settings/DataTable";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select } from "../../components/settings/Controls";
import { EntityChip, type EntityState } from "../../components/settings/EntityChip";
import type { Campaign, Client } from "../../lib/types";

export function Campaigns() {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [clientId, setClientId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [horizonDays, setHorizonDays] = useState(7);

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const campaigns = useQuery({
    queryKey: ["config", "campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const create = useMutation({
    mutationFn: () =>
      apiClient.post<Campaign>("/content/ui/config/campaigns", {
        client_id: clientId,
        name,
        horizon_days: horizonDays,
      }),
    onSuccess: () => {
      setName("");
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "campaigns"] });
    },
  });

  const archive = useMutation({
    mutationFn: (id: number) => apiClient.delete<Campaign>(`/content/ui/config/campaigns/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "campaigns"] }),
  });

  function closeDrawer() {
    setDrawerOpen(false);
    setClientId(null);
    setName("");
    setHorizonDays(7);
    create.reset();
  }

  // Name by id, so the new column does not cost a request per row.
  const clientName = useMemo(() => {
    const map = new Map<number, string>();
    clients.data?.forEach((client) => map.set(client.id, client.name));
    return map;
  }, [clients.data]);

  const columns: Array<Column<Campaign>> = [
    {
      key: "name",
      header: "Nome",
      render: (campaign) => <span className="font-medium">{campaign.name}</span>,
    },
    {
      key: "client",
      header: "Cliente",
      render: (campaign) => clientName.get(campaign.client_id) ?? "—",
    },
    {
      key: "horizon",
      header: "Horizonte",
      align: "right",
      width: "9rem",
      render: (campaign) => (
        <span className="font-mono text-[12px]">{campaign.horizon_days} dias</span>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "8rem",
      render: (campaign) => <EntityChip state={campaign.status as EntityState} />,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      width: "5rem",
      render: (campaign) => (
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={archive.isPending}
            actions={[
              {
                label: "Arquivar",
                danger: true,
                disabled: campaign.status !== "active",
                onConfirm: () => archive.mutate(campaign.id),
              },
            ]}
          />
        </RequireRole>
      ),
    },
  ];

  return (
    <SettingsPage
      title="Campanhas"
      description="Uma campanha define o que é gerado, com que antecedência e sob quais regras de aprovação."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button variant="primary" onClick={() => setDrawerOpen(true)}>
            <Plus size={15} />
            Nova campanha
          </Button>
        </RequireRole>
      }
    >
      <DataTable
        columns={columns}
        rows={campaigns.data}
        rowKey={(campaign) => campaign.id}
        isLoading={campaigns.isLoading}
        isError={campaigns.isError}
        emptyTitle="Nenhuma campanha cadastrada"
        emptyHint="Crie uma campanha para que a automação comece a gerar conteúdo."
      />

      <Drawer
        open={drawerOpen}
        onClose={closeDrawer}
        title="Nova campanha"
        description="O horizonte define quantos dias à frente a automação gera conteúdo."
      >
        <form
          className="flex flex-col gap-4 items-stretch flex-nowrap m-0"
          onSubmit={(event) => {
            event.preventDefault();
            if (clientId !== null) create.mutate();
          }}
        >
          <Field label="Cliente">
            <Select
              value={clientId ?? ""}
              onChange={(event) => setClientId(Number(event.target.value) || null)}
              required
            >
              <option value="">Selecione um cliente</option>
              {clients.data?.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Nome da campanha">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Nome da campanha"
              required
            />
          </Field>
          <Field
            label="Horizonte de geração"
            hint="Quantos dias à frente a automação gera conteúdo para esta campanha."
          >
            <Input
              type="number"
              min={1}
              value={horizonDays}
              onChange={(event) => setHorizonDays(Number(event.target.value))}
            />
          </Field>
          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending || clientId === null || !name.trim()}
            >
              {create.isPending ? "Criando…" : "Criar campanha"}
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
