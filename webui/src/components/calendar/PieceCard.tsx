import { Link } from "react-router-dom";
import { Lock } from "lucide-react";
import type { CalendarItem } from "../../lib/types";
import { parseUtc, timeLabel } from "../../lib/calendarDates";
import { PlatformIcon, type Platform } from "../ui/PlatformIcon";
import { cn } from "../ui/cn";

const STATE_STYLE: Record<CalendarItem["calendar_state"], string> = {
  draft: "border-[var(--border)] bg-[var(--card-bg)]",
  scheduled: "border-[var(--border)] bg-[var(--card-bg)]",
  publishing: "border-warn/50 bg-warn/5",
  // The reference outlines failures in red rather than tinting them, so a
  // failed post is findable while scanning a dense month without changing the
  // card's weight.
  failed: "border-bad bg-bad/5",
  published: "border-[var(--border)] bg-[var(--code-bg)]",
};

export function PieceCard({
  item,
  onDragStart,
  onDragEnd,
  isDragging,
}: {
  item: CalendarItem;
  onDragStart: (item: CalendarItem) => void;
  onDragEnd: () => void;
  isDragging: boolean;
}) {
  const when = item.scheduled_for ?? item.posted_at;
  const time = when ? timeLabel(parseUtc(when)) : null;
  const draggable = !item.is_locked;

  return (
    <Link
      to={`/pieces/${item.id}`}
      draggable={draggable}
      onDragStart={(event) => {
        if (!draggable) {
          event.preventDefault();
          return;
        }
        // Firefox ignores a drag that sets no data.
        event.dataTransfer.setData("text/plain", String(item.id));
        event.dataTransfer.effectAllowed = "move";
        onDragStart(item);
      }}
      onDragEnd={onDragEnd}
      title={item.is_locked ? `${item.title} (já despachada — não pode ser movida)` : item.title}
      className={cn(
        "group flex items-center gap-1.5 px-1.5 py-1 rounded-[3px] border no-underline",
        "text-[11px] leading-tight text-[var(--text-h)] transition-opacity",
        STATE_STYLE[item.calendar_state],
        draggable ? "cursor-grab active:cursor-grabbing" : "cursor-pointer",
        isDragging && "opacity-40",
      )}
    >
      {item.platforms.length > 0 ? (
        <PlatformIcon platform={item.platforms[0].platform as Platform} size={12} />
      ) : (
        <span className="w-3 h-3 shrink-0 rounded-[2px] bg-[var(--border)]" />
      )}
      <span className="flex-1 min-w-0 truncate">{item.title}</span>
      {item.is_locked ? (
        <Lock size={10} className="shrink-0 text-[var(--text)]" />
      ) : null}
      {time ? (
        <span className="shrink-0 font-mono text-[10px] text-[var(--text)]">{time}</span>
      ) : null}
    </Link>
  );
}
