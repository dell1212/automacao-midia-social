import { cn } from "../ui/cn";

/** Lifecycle of a configuration record.
 *
 * Deliberately separate from `ui/StatusChip`, which is the lifecycle of a
 * content piece (draft → generating → posted). The two vocabularies change
 * for different reasons and merging them would couple two independent
 * evolutions. The look is identical on purpose: the distinction is ours, not
 * the reader's.
 */
export type EntityState = "active" | "inactive" | "archived" | "revoked";

const STYLES: Record<EntityState, { label: string; className: string }> = {
  active: { label: "Ativo", className: "bg-ok/15 text-ok" },
  inactive: { label: "Inativo", className: "bg-[var(--code-bg)] text-[var(--text)]" },
  archived: { label: "Arquivada", className: "bg-[var(--code-bg)] text-[var(--text)]" },
  revoked: { label: "Revogada", className: "bg-bad/15 text-bad" },
};

export function EntityChip({
  state,
  className,
}: {
  state: EntityState;
  className?: string;
}) {
  const style = STYLES[state];
  // `Campaign.status` and `SocialAccount.status` are plain strings on the
  // backend, so an unmapped value can arrive. Show it rather than render an
  // empty chip.
  if (!style) {
    return (
      <span
        className={cn(
          "inline-flex items-center h-5 px-2 rounded-full text-[11px] font-medium",
          "bg-[var(--code-bg)] text-[var(--text)]",
          className,
        )}
      >
        {state}
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center h-5 px-2 rounded-full text-[11px] font-medium whitespace-nowrap",
        style.className,
        className,
      )}
    >
      {style.label}
    </span>
  );
}
