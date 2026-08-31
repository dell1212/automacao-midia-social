import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Campaign, Client } from "../../lib/types";

export function Campaigns() {
  const queryClient = useQueryClient();
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
      queryClient.invalidateQueries({ queryKey: ["config", "campaigns"] });
    },
  });

  const archive = useMutation({
    mutationFn: (id: number) => apiClient.delete<Campaign>(`/content/ui/config/campaigns/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "campaigns"] }),
  });

  return (
    <div>
      <h1>Campaigns</h1>

      {campaigns.isLoading && <p>Carregando...</p>}
      {campaigns.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {campaigns.data?.map((campaign) => (
          <li key={campaign.id}>
            {campaign.name} — {campaign.status}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={campaign.status !== "active" || archive.isPending}
                onClick={() => archive.mutate(campaign.id)}
              >
                Arquivar
              </button>
            </RequireRole>
          </li>
        ))}
      </ul>

      <RequireRole role="admin">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (clientId !== null) create.mutate();
          }}
        >
          <label>
            Client
            <select
              value={clientId ?? ""}
              onChange={(event) => setClientId(Number(event.target.value))}
              required
            >
              <option value="" disabled>
                Selecione um client
              </option>
              {clients.data?.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Nome da campanha
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Nome da campanha"
              required
            />
          </label>
          <label>
            Horizonte de geração (dias)
            <input
              type="number"
              value={horizonDays}
              onChange={(event) => setHorizonDays(Number(event.target.value))}
              min={1}
              title="Quantos dias à frente a automação gera conteúdo para esta campanha"
            />
          </label>
          <button type="submit" disabled={create.isPending}>
            Criar
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
