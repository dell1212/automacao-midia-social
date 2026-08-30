import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { ApprovalRule, Campaign } from "../../lib/types";

export function ApprovalRules() {
  const queryClient = useQueryClient();
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [action, setAction] = useState<"auto_approve" | "require_review">("require_review");
  const [priority, setPriority] = useState(0);
  const [conditionJson, setConditionJson] = useState("{}");
  const [conditionError, setConditionError] = useState<string | null>(null);

  const campaigns = useQuery({
    queryKey: ["config", "campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const rules = useQuery({
    queryKey: ["config", "approval-rules", campaignId],
    queryFn: () =>
      apiClient.get<ApprovalRule[]>(
        `/content/ui/config/campaigns/${campaignId}/approval-rules`
      ),
    enabled: campaignId !== null,
  });

  const create = useMutation({
    mutationFn: (condition: Record<string, unknown>) =>
      apiClient.post<ApprovalRule>("/content/ui/config/approval-rules", {
        campaign_id: campaignId,
        condition,
        action,
        priority,
      }),
    onSuccess: () => {
      setConditionJson("{}");
      queryClient.invalidateQueries({ queryKey: ["config", "approval-rules", campaignId] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => apiClient.delete(`/content/ui/config/approval-rules/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "approval-rules", campaignId] }),
  });

  return (
    <div>
      <h1>Approval Rules</h1>

      <select
        value={campaignId ?? ""}
        onChange={(event) => setCampaignId(Number(event.target.value) || null)}
      >
        <option value="">Selecione uma campanha</option>
        {campaigns.data?.map((campaign) => (
          <option key={campaign.id} value={campaign.id}>
            {campaign.name}
          </option>
        ))}
      </select>

      {rules.isLoading && <p>Carregando...</p>}
      {rules.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {rules.data?.map((rule) => (
          <li key={rule.id}>
            prioridade {rule.priority} — {rule.action} — {JSON.stringify(rule.condition)}
            <RequireRole role="admin" fallback={null}>
              <button disabled={remove.isPending} onClick={() => remove.mutate(rule.id)}>
                Excluir
              </button>
            </RequireRole>
          </li>
        ))}
      </ul>

      <RequireRole role="admin">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (campaignId === null) return;
            try {
              const condition = JSON.parse(conditionJson);
              setConditionError(null);
              create.mutate(condition);
            } catch {
              setConditionError("JSON inválido");
            }
          }}
        >
          <select
            value={action}
            onChange={(event) => setAction(event.target.value as "auto_approve" | "require_review")}
          >
            <option value="require_review">Requer revisão</option>
            <option value="auto_approve">Aprovação automática</option>
          </select>
          <input
            type="number"
            value={priority}
            onChange={(event) => setPriority(Number(event.target.value))}
          />
          <textarea
            value={conditionJson}
            onChange={(event) => setConditionJson(event.target.value)}
            placeholder='Condição em JSON, ex: {"content_category": "medical"}'
          />
          {conditionError && <p>{conditionError}</p>}
          <button type="submit" disabled={create.isPending || campaignId === null}>
            Criar regra
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
