import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Avatar, Client } from "../../lib/types";

export function Avatars() {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [voiceProvider, setVoiceProvider] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);

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
    mutationFn: (formData: FormData) => apiClient.uploadFile<Avatar>("/content/ui/config/avatars", formData),
    onSuccess: () => {
      setName("");
      setVoiceProvider("");
      setVoiceId("");
      setImageFile(null);
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
          <label>
            Nome
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Nome do avatar"
              required
            />
          </label>
          <label>
            Imagem de referência
            <input
              type="file"
              accept="image/*"
              onChange={(event) => setImageFile(event.target.files?.[0] ?? null)}
              required
            />
          </label>
          <label>
            Provider de voz (opcional)
            <input
              value={voiceProvider}
              onChange={(event) => setVoiceProvider(event.target.value)}
              placeholder="ex: elevenlabs"
            />
          </label>
          <label>
            Voice ID (opcional)
            <input
              value={voiceId}
              onChange={(event) => setVoiceId(event.target.value)}
              placeholder="ID da voz no provider"
            />
          </label>
          <button type="submit" disabled={create.isPending || clientId === null || !imageFile}>
            Criar
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
