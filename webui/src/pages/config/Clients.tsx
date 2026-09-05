import { useState } from "react";
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
import { Input } from "../../components/settings/Controls";
import { EntityChip } from "../../components/settings/EntityChip";
import type { Client, ClientPayload } from "../../lib/types";

export function Clients() {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [name, setName] = useState("");

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const create = useMutation({
    mutationFn: (payload: ClientPayload) =>
      apiClient.post<Client>("/content/ui/config/clients", payload),
    onSuccess: () => {
      setName("");
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "clients"] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Client>(`/content/ui/config/clients/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "clients"] }),
  });

  const forbidden = apiErrorStatus(create.error) === 403;

  const columns: Array<Column<Client>> = [
    {
      key: "name",
      header: "Nome",
      render: (client) => <span className="font-medium">{client.name}</span>,
    },
    {
      key: "status",
      header: "Status",
      width: "8rem",
      render: (client) => <EntityChip state={client.is_active ? "active" : "inactive"} />,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      width: "5rem",
      render: (client) => (
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={deactivate.isPending}
            actions={[
              {
                label: "Desativar",
                danger: true,
                disabled: !client.is_active,
                onConfirm: () => deactivate.mutate(client.id),
              },
            ]}
          />
        </RequireRole>
      ),
    },
  ];

  return (
    <SettingsPage
      title="Clientes"
      description="Cada cliente agrupa suas próprias campanhas, contas sociais e avatares."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button variant="primary" onClick={() => setDrawerOpen(true)}>
            <Plus size={15} />
            Novo cliente
          </Button>
        </RequireRole>
      }
    >
      <DataTable
        columns={columns}
        rows={clients.data}
        rowKey={(client) => client.id}
        isLoading={clients.isLoading}
        isError={clients.isError}
        emptyTitle="Nenhum cliente cadastrado"
        emptyHint="Crie o primeiro cliente para começar a montar campanhas."
      />

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="Novo cliente"
        description="O nome pode ser alterado depois pelo suporte."
      >
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({ name });
          }}
        >
          <Field
            label="Nome"
            error={forbidden ? "Você não tem permissão para criar clientes." : null}
          >
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Nome do cliente"
              required
            />
          </Field>
          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button type="submit" variant="primary" disabled={create.isPending || !name.trim()}>
              {create.isPending ? "Criando…" : "Criar cliente"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setDrawerOpen(false)}>
              Cancelar
            </Button>
          </div>
        </form>
      </Drawer>
    </SettingsPage>
  );
}
