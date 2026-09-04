import type { CalendarItem } from "../../lib/types";
import { WEEKDAY_LABELS, localDayKey, monthGridDays, parseUtc } from "../../lib/calendarDates";
import { DayCell } from "./DayCell";

/** Buckets items by the viewer's local day. Anything whose instant falls
 * outside the rendered grid is dropped rather than clamped into an edge cell,
 * so a card never appears on a day it does not belong to. */
function bucketByDay(items: CalendarItem[]): Map<string, CalendarItem[]> {
  const buckets = new Map<string, CalendarItem[]>();
  for (const item of items) {
    const when = item.scheduled_for ?? item.posted_at;
    if (!when) continue;
    const key = localDayKey(parseUtc(when));
    const bucket = buckets.get(key);
    if (bucket) bucket.push(item);
    else buckets.set(key, [item]);
  }
  for (const bucket of buckets.values()) {
    bucket.sort((a, b) => {
      const at = a.scheduled_for ?? a.posted_at ?? "";
      const bt = b.scheduled_for ?? b.posted_at ?? "";
      return at.localeCompare(bt);
    });
  }
  return buckets;
}

export function MonthGrid({
  year,
  month,
  items,
  draggingId,
  hoveredDay,
  onDragStart,
  onDragEnd,
  onDropOnDay,
  onHoverDay,
}: {
  year: number;
  month: number;
  items: CalendarItem[];
  draggingId: number | null;
  hoveredDay: Date | null;
  onDragStart: (item: CalendarItem) => void;
  onDragEnd: () => void;
  onDropOnDay: (day: Date) => void;
  onHoverDay: (day: Date | null) => void;
}) {
  const days = monthGridDays(year, month);
  const buckets = bucketByDay(items);
  const hoveredKey = hoveredDay ? localDayKey(hoveredDay) : null;

  return (
    <div className="border-t border-l border-[var(--border)] rounded-[4px] overflow-hidden">
      <div className="grid grid-cols-7">
        {WEEKDAY_LABELS.map((label) => (
          <div
            key={label}
            className="px-2 py-1.5 border-r border-b border-[var(--border)] bg-[var(--bg)] font-mono text-[10px] tracking-[0.12em] text-[var(--text)]"
          >
            {label}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {days.map((day) => {
          const key = localDayKey(day);
          return (
            <DayCell
              key={key}
              day={day}
              items={buckets.get(key) ?? []}
              inMonth={day.getMonth() === month}
              isDropTarget={hoveredKey === key}
              draggingId={draggingId}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
              onDropOnDay={onDropOnDay}
              onHoverDay={onHoverDay}
            />
          );
        })}
      </div>
    </div>
  );
}
