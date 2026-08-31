import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, apiErrorStatus } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Provider, ProviderCreatePayload } from "../../lib/types";

export function Providers() {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<"image" | "video" | "voice">("image");
  const [providerName, setProviderName] = useState<
    "wavespeed" | "falai" | "gemini" | "elevenlabs"
  >("falai");
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
      queryClient.invalidateQueries({ queryKey: ["config", "providers"] });
    },
  });

  const updatePriority = useMutation({
    mutationFn: ({ id, priority }: { id: number; priority: number }) =>
      apiClient.put<Provider>(`/content/ui/config/providers/${id}`, { priority }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "providers"] }),
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Provider>(`/content/ui/config/providers/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "providers"] }),
  });

  const invalidCredentials = apiErrorStatus(create.error) === 422;

  return (
    <div>
      <h1>Providers</h1>

      {providers.isLoading && <p>Carregando...</p>}
      {providers.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {providers.data?.map((provider) => (
          <li key={provider.id}>
            {provider.kind} — {provider.provider} — prioridade
            <input
              type="number"
              defaultValue={provider.priority}
              disabled={!provider.is_active}
              title="Prioridade entre providers do mesmo tipo — número menor é tentado primeiro"
              onBlur={(event) =>
                updatePriority.mutate({ id: provider.id, priority: Number(event.target.value) })
              }
            />
            {!provider.is_active && "(inativo)"}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={!provider.is_active || deactivate.isPending}
                onClick={() => deactivate.mutate(provider.id)}
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
            create.mutate({ kind, provider: providerName, credentials, config: {}, priority });
          }}
        >
          <label>
            Tipo
            <select value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>
              <option value="image">Imagem</option>
              <option value="video">Vídeo</option>
              <option value="voice">Voz</option>
            </select>
          </label>
          <label>
            Provider
            <select
              value={providerName}
              onChange={(event) => setProviderName(event.target.value as typeof providerName)}
            >
              <option value="wavespeed">Wavespeed</option>
              <option value="falai">fal.ai</option>
              <option value="gemini">Gemini</option>
              <option value="elevenlabs">ElevenLabs</option>
            </select>
          </label>
          <label>
            API key
            <input
              type="password"
              value={credentials}
              onChange={(event) => setCredentials(event.target.value)}
              placeholder="API key"
              required
            />
          </label>
          <label>
            Prioridade
            <input
              type="number"
              value={priority}
              onChange={(event) => setPriority(Number(event.target.value))}
              title="Número menor é tentado primeiro entre providers do mesmo tipo"
            />
          </label>
          <button type="submit" disabled={create.isPending}>
            Adicionar
          </button>
          {invalidCredentials && <p>Credencial inválida para este provider.</p>}
        </form>
      </RequireRole>
    </div>
  );
}
