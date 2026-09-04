import { cn } from "./cn";

/** Filter pill with a trailing count, as used by the calendar toolbar.
 *
 * The count is deliberately a required prop rather than optional: a filter
 * that shows how many rows it would leave is the whole point of the control,
 * and an undefined count would silently render a pill that looks broken.
 */
export function Pill({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 h-7 pl-3 pr-1.5 rounded-full border",
        "text-[13px] font-medium cursor-pointer transition-colors",
        active
          ? "bg-ink text-white border-transparent"
          : "bg-[var(--card-bg)] text-[var(--text-h)] border-[var(--border)] hover:bg-[var(--code-bg)]",
      )}
    >
      {label}
      <span
        className={cn(
          "inline-flex items-center justify-center min-w-5 h-5 px-1 rounded-full",
          "font-mono text-[10px] leading-none",
          active ? "bg-white/15 text-white" : "bg-[var(--code-bg)] text-[var(--text)]",
        )}
      >
        {count}
      </span>
    </button>
  );
}
