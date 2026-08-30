import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, apiErrorStatus } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Client, ClientPayload } from "../../lib/types";

export function Clients() {
  const queryClient = useQueryClient();
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
      queryClient.invalidateQueries({ queryKey: ["config", "clients"] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Client>(`/content/ui/config/clients/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "clients"] }),
  });

  const forbidden = apiErrorStatus(create.error) === 403;

  return (
    <div>
      <h1>Clients</h1>

      {clients.isLoading && <p>Carregando...</p>}
      {clients.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {clients.data?.map((client) => (
          <li key={client.id}>
            {client.name} {!client.is_active && "(inativo)"}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={!client.is_active || deactivate.isPending}
                onClick={() => deactivate.mutate(client.id)}
              >
                Desativar
              </button>
            </RequireRole>
          </li>
        ))}
      </ul>

      <RequireRole role="admin">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({ name });
          }}
        >
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Nome do client"
            required
          />
          <button type="submit" disabled={create.isPending}>
            Criar
          </button>
          {forbidden && <p>Você não tem permissão para criar clients.</p>}
        </form>
      </RequireRole>
    </div>
  );
}
