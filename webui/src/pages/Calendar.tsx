import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { apiClient, apiErrorStatus } from "../lib/apiClient";
import { queryKeys } from "../lib/queryKeys";
import { monthGridRange, monthLabel, moveToDay, parseUtc, toUtcParam } from "../lib/calendarDates";
import type { CalendarItem, CalendarResponse, CalendarState } from "../lib/types";
import { MonthGrid } from "../components/calendar/MonthGrid";
import { Button } from "../components/ui/Button";
import { MicroLabel } from "../components/ui/Card";
import { EmptyState, Skeleton } from "../components/ui/Feedback";
import { Pill } from "../components/ui/Pill";

const STATE_FILTERS: Array<{ key: CalendarState | "all"; label: string }> = [
  { key: "all", label: "Todas" },
  { key: "scheduled", label: "Agendadas" },
  { key: "draft", label: "Rascunhos" },
  { key: "published", label: "Publicadas" },
  { key: "failed", label: "Falhas" },
];

export function Calendar() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());
  const [stateFilter, setStateFilter] = useState<CalendarState | "all">("all");
  const [dragging, setDragging] = useState<CalendarItem | null>(null);
  const [hoveredDay, setHoveredDay] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const range = useMemo(() => monthGridRange(year, month), [year, month]);
  const queryKey = queryKeys.calendar(range, { state: stateFilter });

  const { data, isLoading, isError } = useQuery({
    queryKey,
    queryFn: () => {
      const params = new URLSearchParams({ from: range.from, to: range.to });
      if (stateFilter !== "all") params.set("state", stateFilter);
      return apiClient.get<CalendarResponse>(`/content/ui/calendar?${params}`);
    },
  });

  const reschedule = useMutation({
    mutationFn: ({ id, scheduledFor }: { id: number; scheduledFor: string }) =>
      apiClient.patch(`/content/ui/pieces/${id}/schedule`, {
        scheduled_for: scheduledFor,
      }),
    // Optimistic so the card lands under the cursor immediately; a drag that
    // waits for a round trip feels broken.
    onMutate: async ({ id, scheduledFor }) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<CalendarResponse>(queryKey);
      queryClient.setQueryData<CalendarResponse>(queryKey, (current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.id === id ? { ...item, scheduled_for: scheduledFor } : item,
              ),
            }
          : current,
      );
      return { previous };
    },
    onError: (err, _vars, context) => {
      // Roll back, then say why. 409 is the server refusing to move a piece the
      // publish pipeline already owns — the one case the UI cannot predict.
      if (context?.previous) queryClient.setQueryData(queryKey, context.previous);
      setError(
        apiErrorStatus(err) === 409
          ? "Esta peça já foi despachada para publicação e não pode ser movida."
          : "Não foi possível reagendar esta peça.",
      );
    },
    onSuccess: () => setError(null),
    onSettled: () => queryClient.invalidateQueries({ queryKey }),
  });

  function goToMonth(delta: number) {
    const next = new Date(year, month + delta, 1);
    setYear(next.getFullYear());
    setMonth(next.getMonth());
  }

  function handleDrop(day: Date) {
    const item = dragging;
    setDragging(null);
    setHoveredDay(null);
    if (!item) return;
    const original = item.scheduled_for ? parseUtc(item.scheduled_for) : null;
    const target = moveToDay(original, day);
    reschedule.mutate({ id: item.id, scheduledFor: toUtcParam(target) });
  }

  const counts = data?.counts ?? {};

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => goToMonth(-1)} aria-label="Mês anterior">
            <ChevronLeft size={15} />
          </Button>
          <Button size="sm" onClick={() => goToMonth(1)} aria-label="Próximo mês">
            <ChevronRight size={15} />
          </Button>
          <h1 className="m-0 ml-1 text-[20px] font-semibold tracking-tight first-letter:uppercase">
            {monthLabel(year, month)}
          </h1>
          <Button
            size="sm"
            onClick={() => {
              const now = new Date();
              setYear(now.getFullYear());
              setMonth(now.getMonth());
            }}
          >
            Hoje
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {STATE_FILTERS.map((filter) => (
            <Pill
              key={filter.key}
              label={filter.label}
              count={counts[filter.key] ?? 0}
              active={stateFilter === filter.key}
              onClick={() => setStateFilter(filter.key)}
            />
          ))}
        </div>
      </div>

      {error ? (
        <div className="flex items-center justify-between gap-3 px-3 py-2 rounded-[4px] border border-bad bg-bad/5 text-[13px] text-bad">
          {error}
          <button
            type="button"
            onClick={() => setError(null)}
            className="bg-transparent border-0 p-0 h-auto text-bad underline cursor-pointer"
          >
            Fechar
          </button>
        </div>
      ) : null}

      {isLoading ? (
        <Skeleton className="h-[520px] w-full" />
      ) : isError ? (
        <EmptyState
          title="Não foi possível carregar o calendário"
          hint="Verifique a conexão com o servidor e tente novamente."
        />
      ) : (
        // The grid renders even with nothing in it. Swapping it for an empty
        // state would remove the very thing a piece has to be dragged onto,
        // and an empty month is a normal state, not an error.
        <MonthGrid
          year={year}
          month={month}
          items={data?.items ?? []}
          draggingId={dragging?.id ?? null}
          hoveredDay={hoveredDay}
          onDragStart={setDragging}
          onDragEnd={() => {
            setDragging(null);
            setHoveredDay(null);
          }}
          onDropOnDay={handleDrop}
          onHoverDay={setHoveredDay}
        />
      )}

      <div className="flex items-center justify-between gap-3">
        <MicroLabel>
          Arraste uma peça para reagendar · peças já despachadas ficam travadas
        </MicroLabel>
        {data && data.items.length === 0 && !isLoading ? (
          <MicroLabel>Nenhuma peça neste período</MicroLabel>
        ) : null}
      </div>
    </div>
  );
}
