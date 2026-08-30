import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Client, SocialAccount, SocialAccountCreatePayload } from "../../lib/types";

export function SocialAccounts() {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState<number | null>(null);
  const [platform, setPlatform] = useState("instagram");
  const [externalAccountId, setExternalAccountId] = useState("");
  const [credentials, setCredentials] = useState("");

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const accounts = useQuery({
    queryKey: ["config", "social-accounts", clientId],
    queryFn: () =>
      apiClient.get<SocialAccount[]>(
        `/content/ui/config/clients/${clientId}/social-accounts`
      ),
    enabled: clientId !== null,
  });

  const create = useMutation({
    mutationFn: (payload: SocialAccountCreatePayload) =>
      apiClient.post<SocialAccount>("/content/ui/config/social-accounts", payload),
    onSuccess: () => {
      setExternalAccountId("");
      setCredentials("");
      queryClient.invalidateQueries({ queryKey: ["config", "social-accounts", clientId] });
    },
  });

  const revoke = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete<SocialAccount>(`/content/ui/config/social-accounts/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "social-accounts", clientId] }),
  });

  return (
    <div>
      <h1>Social Accounts</h1>

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

      {accounts.isLoading && <p>Carregando...</p>}
      {accounts.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {accounts.data?.map((account) => (
          <li key={account.id}>
            {account.platform} — {account.external_account_id} — {account.status}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={account.status !== "active" || revoke.isPending}
                onClick={() => revoke.mutate(account.id)}
              >
                Revogar
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
            create.mutate({
              client_id: clientId,
              platform,
              external_account_id: externalAccountId,
              credentials,
            });
          }}
        >
          <select value={platform} onChange={(event) => setPlatform(event.target.value)}>
            <option value="instagram">Instagram</option>
            <option value="tiktok">TikTok</option>
            <option value="youtube">YouTube</option>
            <option value="x">X</option>
            <option value="facebook">Facebook</option>
            <option value="linkedin">LinkedIn</option>
          </select>
          <input
            value={externalAccountId}
            onChange={(event) => setExternalAccountId(event.target.value)}
            placeholder="ID da conta na plataforma"
            required
          />
          <input
            type="password"
            value={credentials}
            onChange={(event) => setCredentials(event.target.value)}
            placeholder="Credencial de acesso"
            required
          />
          <button type="submit" disabled={create.isPending || clientId === null}>
            Conectar
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
