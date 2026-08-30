import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Avatar, AvatarPayload, Client } from "../../lib/types";

export function Avatars() {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [referenceImageUrl, setReferenceImageUrl] = useState("");

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const avatars = useQuery({
    queryKey: ["config", "avatars", clientId],
    queryFn: () => apiClient.get<Avatar[]>(`/content/ui/config/clients/${clientId}/avatars`),
    enabled: clientId !== null,
  });

  const create = useMutation({
    mutationFn: (payload: AvatarPayload) =>
      apiClient.post<Avatar>("/content/ui/config/avatars", payload),
    onSuccess: () => {
      setName("");
      setReferenceImageUrl("");
      queryClient.invalidateQueries({ queryKey: ["config", "avatars", clientId] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Avatar>(`/content/ui/config/avatars/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "avatars", clientId] }),
  });

  return (
    <div>
      <h1>Avatars</h1>

      <select
        value={clientId ?? ""}
        onChange={(event) => setClientId(Number(event.target.value) || null)}
      >
        <option value="">Selecione um client</option>
        {clients.data?.map((client) => (
          <option key={client.id} value={client.id}>
            {client.name}
          </option>
        ))}
      </select>

      {avatars.isLoading && <p>Carregando...</p>}
      {avatars.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {avatars.data?.map((avatar) => (
          <li key={avatar.id}>
            {avatar.name} {!avatar.is_active && "(inativo)"}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={!avatar.is_active || deactivate.isPending}
                onClick={() => deactivate.mutate(avatar.id)}
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
            if (clientId === null) return;
            create.mutate({ client_id: clientId, name, reference_image_url: referenceImageUrl });
          }}
        >
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Nome do avatar"
            required
          />
          <input
            value={referenceImageUrl}
            onChange={(event) => setReferenceImageUrl(event.target.value)}
            placeholder="URL da imagem de referência"
            required
          />
          <button type="submit" disabled={create.isPending || clientId === null}>
            Criar
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
