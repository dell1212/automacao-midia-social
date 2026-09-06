import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { toUtcParam } from "../lib/calendarDates";
import { Card, MicroLabel } from "../components/ui/Card";
import { EmptyState, Skeleton } from "../components/ui/Feedback";
import { PlatformIcon, type Platform } from "../components/ui/PlatformIcon";
import {
  CadenceChart,
  Legend,
  PlatformBars,
  SERIES,
  StatTile,
  ThroughputChart,
} from "../components/charts/Charts";
import { cn } from "../components/ui/cn";

interface Overview {
  tiles: {
    published: number;
    scheduled: number;
    failed: number;
    success_rate: number | null;
    link_clicks: number | null;
    engagement: number | null;
  };
  throughput: Array<{ day: string; published: number; failed: number }>;
  platform_mix: Array<{ platform: string; published: number; failed: number }>;
  cadence_by_hour: Array<{ hour: number; published: number }>;
  account_performance: Array<{
    social_account_id: number;
    platform: string;
    label: string;
    published: number;
    failed: number;
    success_rate: number | null;
  }>;
  window: {
    best_hour: number | null;
    active_accounts: number;
    total_pieces: number;
    generation_cost: number | null;
    generation_currency: string | null;
    autoapproved_pct: number | null;
  };
}

const RANGES = [
  { key: "7", label: "7D" },
  { key: "30", label: "30D" },
  { key: "90", label: "90D" },
];

// The account table is the accessible fallback for the charts above, so it
// gets the same header/cell treatment as `settings/DataTable` — micro-label
// headers, hairline row separators — rather than inheriting a bare-tag rule.
// Alignment is never baked in: `cn` joins classes but the winner between two
// same-specificity utilities is stylesheet order, not argument order, so a
// TH carrying `text-left` could not be overridden to `text-right` by a caller.
// Each cell states its own alignment instead. The UA sheet centres <th>, and
// Preflight does not reset that, so "left" has to be spelled out too.
const TH =
  "px-3 py-2 font-mono text-[10px] font-medium uppercase tracking-[0.12em] " +
  "text-[var(--text)] whitespace-nowrap";
const TD = "px-3 py-2 align-middle text-[var(--text-h)]";

function pct(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function Analytics() {
  const [days, setDays] = useState("30");

  const range = useMemo(() => {
    const to = new Date();
    const from = new Date();
    from.setDate(to.getDate() - Number(days));
    return { from: toUtcParam(from), to: toUtcParam(to) };
  }, [days]);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["analytics", range.from, range.to],
    queryFn: () =>
      apiClient.get<Overview>(
        `/content/ui/analytics/overview?from=${range.from}&to=${range.to}`,
      ),
  });

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="m-0 text-[20px] font-semibold tracking-tight">Analytics</h1>
        <div className="flex items-center gap-1">
          {RANGES.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => setDays(option.key)}
              className={cn(
                "h-7 px-3 rounded-full border text-[12px] font-medium cursor-pointer",
                days === option.key
                  ? "bg-ink text-white border-transparent"
                  : "bg-[var(--card-bg)] text-[var(--text-h)] border-[var(--border)] hover:bg-[var(--code-bg)]",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-[420px] w-full" />
      ) : isError || !data ? (
        <EmptyState
          title="Não foi possível carregar as métricas"
          hint="Verifique a conexão com o servidor e tente novamente."
        />
      ) : (
        <>
          <Card className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 divide-y md:divide-y-0 divide-[var(--border)]">
            <StatTile label="Publicadas" value={String(data.tiles.published)} />
            <StatTile label="Agendadas" value={String(data.tiles.scheduled)} />
            <StatTile label="Falhas" value={String(data.tiles.failed)} />
            <StatTile label="Taxa de sucesso" value={pct(data.tiles.success_rate)} />
            {/* Present but empty, not omitted: keeping the six-tile grid says
                these exist and are not collected yet, where dropping them
                would just look like they were never part of the product. */}
            <StatTile
              label="Cliques em links"
              value="—"
              hint="ainda não coletado"
              unavailable
            />
            <StatTile
              label="Engajamento"
              value="—"
              hint="ainda não coletado"
              unavailable
            />
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card className="lg:col-span-2 p-4 flex flex-col gap-3">
              <div className="flex items-center justify-between gap-3">
                <MicroLabel>Volume por dia</MicroLabel>
                <Legend
                  items={[
                    { label: "Publicadas", color: SERIES.published },
                    { label: "Falhas", color: SERIES.failed },
                  ]}
                />
              </div>
              <ThroughputChart data={data.throughput} />
            </Card>

            <Card className="p-4 flex flex-col gap-3">
              <MicroLabel>Janela do período</MicroLabel>
              <dl className="m-0 grid grid-cols-2 gap-3">
                <div>
                  <dd className="m-0 text-[18px] font-semibold text-[var(--text-h)]">
                    {data.window.best_hour === null
                      ? "—"
                      : `${String(data.window.best_hour).padStart(2, "0")}h`}
                  </dd>
                  <dt className="font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--text)]">
                    Melhor horário
                  </dt>
                </div>
                <div>
                  <dd className="m-0 text-[18px] font-semibold text-[var(--text-h)]">
                    {data.window.active_accounts}
                  </dd>
                  <dt className="font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--text)]">
                    Contas ativas
                  </dt>
                </div>
                <div>
                  <dd className="m-0 text-[18px] font-semibold text-[var(--text-h)]">
                    {data.window.generation_cost === null
                      ? "—"
                      : `${data.window.generation_currency ?? ""} ${data.window.generation_cost.toFixed(2)}`}
                  </dd>
                  <dt className="font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--text)]">
                    Custo de geração
                  </dt>
                </div>
                <div>
                  <dd className="m-0 text-[18px] font-semibold text-[var(--text-h)]">
                    {pct(data.window.autoapproved_pct)}
                  </dd>
                  <dt className="font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--text)]">
                    Aprovado sem humano
                  </dt>
                </div>
              </dl>
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card className="p-4 flex flex-col gap-3">
              <MicroLabel>Por plataforma</MicroLabel>
              <PlatformBars
                data={data.platform_mix}
                renderIcon={(platform) => (
                  <PlatformIcon platform={platform as Platform} size={13} />
                )}
              />
            </Card>

            <Card className="p-4 flex flex-col gap-3">
              <MicroLabel>Cadência por hora</MicroLabel>
              <CadenceChart data={data.cadence_by_hour} />
            </Card>
          </div>

          <Card className="p-4 flex flex-col gap-3">
            <MicroLabel>Desempenho por conta</MicroLabel>
            {data.account_performance.length === 0 ? (
              <p className="m-0 text-[12px] text-[var(--text)]">
                Nenhuma conta publicou no período.
              </p>
            ) : (
              /* The table is also the accessible fallback for the charts
                 above — every number they encode is readable here. */
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    <th className={cn(TH, "text-left")}>Conta</th>
                    <th className={cn(TH, "text-right")}>Publicadas</th>
                    <th className={cn(TH, "text-right")}>Falhas</th>
                    <th className={cn(TH, "text-right")}>Taxa</th>
                  </tr>
                </thead>
                <tbody>
                  {data.account_performance.map((row) => (
                    <tr
                      key={row.social_account_id}
                      className="border-b border-[var(--border)] last:border-b-0"
                    >
                      <td className={cn(TD, "text-left")}>
                        <span className="flex items-center gap-1.5">
                          <PlatformIcon platform={row.platform as Platform} size={13} />
                          {row.label}
                        </span>
                      </td>
                      <td className={cn(TD, "text-right font-mono")}>{row.published}</td>
                      <td className={cn(TD, "text-right font-mono")}>{row.failed}</td>
                      <td className={cn(TD, "text-right font-mono")}>{pct(row.success_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
