import { useState } from "react";
import type { CalendarItem } from "../../lib/types";
import { isBeforeToday, isSameLocalDay } from "../../lib/calendarDates";
import { PieceCard } from "./PieceCard";
import { cn } from "../ui/cn";

const VISIBLE = 3;

export function DayCell({
  day,
  items,
  inMonth,
  isDropTarget,
  draggingId,
  onDragStart,
  onDragEnd,
  onDropOnDay,
  onHoverDay,
}: {
  day: Date;
  items: CalendarItem[];
  inMonth: boolean;
  isDropTarget: boolean;
  draggingId: number | null;
  onDragStart: (item: CalendarItem) => void;
  onDragEnd: () => void;
  onDropOnDay: (day: Date) => void;
  onHoverDay: (day: Date | null) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const today = isSameLocalDay(day, new Date());
  // The reference refuses past days as drop targets; a schedule moved into the
  // past would either fire on the next tick or be rejected by the server, so
  // the grid says no before the drag completes.
  const past = isBeforeToday(day);
  const shown = expanded ? items : items.slice(0, VISIBLE);
  const hidden = items.length - shown.length;

  return (
    <div
      onDragOver={(event) => {
        if (past || draggingId === null) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        onHoverDay(day);
      }}
      onDragLeave={() => onHoverDay(null)}
      onDrop={(event) => {
        if (past || draggingId === null) return;
        event.preventDefault();
        onDropOnDay(day);
      }}
      className={cn(
        "flex flex-col gap-1 min-h-28 p-1.5 border-r border-b border-[var(--border)]",
        inMonth ? "bg-[var(--card-bg)]" : "bg-[var(--bg)]",
        isDropTarget && !past && "outline outline-2 -outline-offset-2 outline-lime",
        past && draggingId !== null && "opacity-60",
      )}
    >
      <div className="flex items-center justify-between">
        <span
          className={cn(
            "inline-flex items-center justify-center min-w-5 h-5 px-1 rounded-full text-[11px] font-medium",
            today
              ? "bg-lime text-ink"
              : inMonth
                ? "text-[var(--text-h)]"
                : "text-[var(--text)]",
          )}
        >
          {day.getDate()}
        </span>
        {items.length > 0 ? (
          <span className="font-mono text-[10px] text-[var(--text)]">{items.length}</span>
        ) : null}
      </div>

      {shown.map((item) => (
        <PieceCard
          key={item.id}
          item={item}
          isDragging={draggingId === item.id}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
        />
      ))}

      {hidden > 0 ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="self-start bg-transparent border-0 p-0 h-auto text-[10px] text-[var(--text)] hover:text-[var(--text-h)] cursor-pointer"
        >
          +{hidden} mais
        </button>
      ) : null}
    </div>
  );
}
