import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { apiClient, apiErrorStatus } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/Feedback";
import { cn } from "../../components/ui/cn";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ScopeBar } from "../../components/settings/ScopeBar";
import { DataTable, type Column } from "../../components/settings/DataTable";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select } from "../../components/settings/Controls";
import {
  CONTENT_CATEGORIES,
  RISK_LEVELS,
  buildCondition,
  describeCondition,
  readCondition,
} from "../../lib/approvalCondition";
import type { ApprovalRule, ApprovalRulePayload, Campaign } from "../../lib/types";

const ACTION_LABEL: Record<ApprovalRule["action"], string> = {
  auto_approve: "Aprovar sozinho",
  require_review: "Requer revisão",
};

function ChipGroup({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: ReadonlyArray<{ value: string; label: string }>;
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <fieldset className="m-0 p-0 border-0">
      <legend className="mb-1.5 p-0 text-[13px] font-medium text-[var(--text-h)]">
        {label}
      </legend>
      {/* [&>button+button]:ml-0 undoes `button + button { margin-left: 8px }`
          from index.css's base layer (Preflight is off, so that bare-tag
          rule still applies to these chips). Left alone, it would stack on
          top of the flex gap below instead of being replaced by it, and it
          would still land on the first chip of a wrapped row, throwing off
          alignment there too. */}
      <div className="flex flex-wrap gap-1.5 [&>button+button]:ml-0">
        {options.map((option) => {
          const active = selected.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={active}
              onClick={() => onToggle(option.value)}
              className={cn(
                "h-7 px-3 rounded-full border text-[12px] font-medium cursor-pointer transition-colors",
                active
                  ? "bg-ink text-white border-transparent"
                  : "bg-[var(--card-bg)] text-[var(--text-h)] border-[var(--border)] hover:bg-[var(--code-bg)]",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export function ApprovalRules() {
  const queryClient = useQueryClient();
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [action, setAction] = useState<ApprovalRule["action"]>("require_review");
  const [priority, setPriority] = useState(10);
  const [categories, setCategories] = useState<string[]>([]);
  const [risks, setRisks] = useState<string[]>([]);

  const campaigns = useQuery({
    queryKey: ["config", "campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const rules = useQuery({
    queryKey: ["config", "approval-rules", campaignId],
    queryFn: () =>
      apiClient.get<ApprovalRule[]>(
        `/content/ui/config/campaigns/${campaignId}/approval-rules`,
      ),
    enabled: campaignId !== null,
  });

  const create = useMutation({
    // Reading is nested under the campaign, but creating is not: the POST goes
    // to the flat collection with campaign_id in the body. Do not "fix" this
    // into a nested path — that route does not exist on the backend.
    mutationFn: (payload: ApprovalRulePayload) =>
      apiClient.post<ApprovalRule>("/content/ui/config/approval-rules", payload),
    onSuccess: () => {
      closeDrawer();
      queryClient.invalidateQueries({ queryKey: ["config", "approval-rules", campaignId] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete<ApprovalRule>(`/content/ui/config/approval-rules/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "approval-rules", campaignId] }),
  });

  function toggle(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
  }

  // Mirrors the convention in Clients.tsx/Providers.tsx: without this, a
  // failed create just reverts the button with no explanation and the
  // drawer sits there looking like nothing happened.
  const createErrorStatus = apiErrorStatus(create.error);
  const createErrorMessage =
    createErrorStatus === 403
      ? "Você não tem permissão para criar regras."
      : createErrorStatus === 404
        ? "Campanha não encontrada — ela pode ter sido removida."
        : create.isError
          ? "Não foi possível criar a regra. Tente novamente."
          : null;

  // One handler for every way out of the drawer (Esc, backdrop, Cancelar) so
  // the chip selections and any create.error from a previous attempt never
  // leak into the next time it opens.
  function closeDrawer() {
    setDrawerOpen(false);
    setCategories([]);
    setRisks([]);
    create.reset();
  }

  // Lowest priority first — the order the scheduler evaluates them in. The
  // backend does not promise an order, so the client establishes one.
  const sortedRules = rules.data
    ? [...rules.data].sort((a, b) => a.priority - b.priority)
    : undefined;

  const columns: Array<Column<ApprovalRule>> = [
    {
      key: "priority",
      header: "Prioridade",
      width: "8rem",
      render: (rule) => <span className="font-mono text-[12px]">{rule.priority}</span>,
    },
    {
      key: "action",
      header: "Ação",
      width: "12rem",
      render: (rule) => <span className="font-medium">{ACTION_LABEL[rule.action]}</span>,
    },
    {
      key: "condition",
      header: "Condição",
      render: (rule) => {
        // When the chips can't represent this condition, showing only the
        // sentence leaves the operator with "something is wrong" and no way
        // to tell what. The old textarea screen always showed the raw JSON
        // (git show 73acf55, ApprovalRules.tsx:81); with no edit path here
        // either, dropping it would be a straight regression, so both the
        // warning and the raw shape are shown together.
        const parsed = readCondition(rule.condition);
        if (!parsed) {
          return (
            <div className="flex flex-col gap-0.5">
              <span className="text-[12px] text-bad">{describeCondition(rule.condition)}</span>
              <span className="font-mono text-[11px] text-[var(--text)] break-all">
                {JSON.stringify(rule.condition)}
              </span>
            </div>
          );
        }
        return (
          <span className="text-[var(--text)]">{describeCondition(rule.condition)}</span>
        );
      },
    },
    {
      key: "actions",
      header: "",
      align: "right",
      width: "5rem",
      render: (rule) => (
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={remove.isPending}
            actions={[
              { label: "Excluir", danger: true, onConfirm: () => remove.mutate(rule.id) },
            ]}
          />
        </RequireRole>
      ),
    },
  ];

  return (
    <SettingsPage
      title="Regras de aprovação"
      description="Cada peça gerada é checada contra estas regras, da menor prioridade para a maior. A primeira que bater decide se a peça é aprovada sozinha ou vai para revisão humana."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button
            variant="primary"
            disabled={campaignId === null}
            onClick={() => setDrawerOpen(true)}
          >
            <Plus size={15} />
            Nova regra
          </Button>
        </RequireRole>
      }
    >
      <ScopeBar
        label="Campanha"
        placeholder="Selecione uma campanha"
        options={campaigns.data?.map((campaign) => ({ id: campaign.id, label: campaign.name }))}
        value={campaignId}
        onChange={setCampaignId}
        isLoading={campaigns.isLoading}
      />

      {campaignId === null ? (
        <Card>
          <EmptyState
            title="Escolha uma campanha"
            hint="Cada campanha tem suas próprias regras. Selecione uma acima para ver as dela."
          />
        </Card>
      ) : (
        <DataTable
          columns={columns}
          rows={sortedRules}
          rowKey={(rule) => rule.id}
          isLoading={rules.isLoading}
          isError={rules.isError}
          emptyTitle="Nenhuma regra nesta campanha"
          emptyHint="Sem regra que bata, a peça vai para revisão humana."
        />
      )}

      <Drawer
        open={drawerOpen}
        onClose={closeDrawer}
        title="Nova regra"
        description="Sem nenhuma condição marcada, a regra vale para qualquer peça — útil como regra final, com a prioridade mais alta."
      >
        <form
          className="flex flex-col gap-4 items-stretch flex-nowrap m-0"
          onSubmit={(event) => {
            event.preventDefault();
            if (campaignId === null) return;
            create.mutate({
              campaign_id: campaignId,
              condition: buildCondition(categories, risks),
              action,
              priority,
            });
          }}
        >
          <Field label="Ação">
            <Select
              value={action}
              onChange={(event) =>
                setAction(event.target.value as ApprovalRule["action"])
              }
            >
              <option value="require_review">Requer revisão</option>
              <option value="auto_approve">Aprovar sozinho</option>
            </Select>
          </Field>

          <Field label="Prioridade" hint="Número menor é checado primeiro.">
            <Input
              type="number"
              value={priority}
              onChange={(event) => setPriority(Number(event.target.value))}
            />
          </Field>

          <ChipGroup
            label="Nível de risco"
            options={RISK_LEVELS}
            selected={risks}
            onToggle={(value) => setRisks((list) => toggle(list, value))}
          />

          <ChipGroup
            label="Categoria de conteúdo"
            options={CONTENT_CATEGORIES}
            selected={categories}
            onToggle={(value) => setCategories((list) => toggle(list, value))}
          />

          {/* The sentence updates as the chips change, so the operator reads
              the rule they are building instead of inferring it. */}
          <Card className="px-3 py-2.5">
            <p className="m-0 text-[12px] text-[var(--text)]">
              <span className="font-medium text-[var(--text-h)]">
                {ACTION_LABEL[action]}
              </span>{" "}
              {describeCondition(buildCondition(categories, risks))}
            </p>
          </Card>

          {createErrorMessage ? (
            <p className="m-0 text-[12px] text-bad">{createErrorMessage}</p>
          ) : null}

          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending || campaignId === null}
            >
              {create.isPending ? "Criando…" : "Criar regra"}
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
