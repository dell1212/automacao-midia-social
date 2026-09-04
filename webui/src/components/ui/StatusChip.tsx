import { cn } from "./cn";

/** Every status this app can show, in one place: the seven ContentPiece
 * statuses the backend stores, plus the derived calendar states the read
 * layer computes (`scheduled`, `publishing`, `published`). Both vocabularies
 * land here so a chip renders the same wherever it appears. */
export type ChipStatus =
  | "draft"
  | "generating"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "posted"
  | "failed"
  | "scheduled"
  | "publishing"
  | "published";

const STYLES: Record<ChipStatus, { label: string; className: string }> = {
  draft: { label: "Rascunho", className: "bg-[var(--code-bg)] text-[var(--text)]" },
  generating: { label: "Gerando", className: "bg-warn/15 text-warn" },
  pending_approval: { label: "Aguardando revisão", className: "bg-warn/15 text-warn" },
  approved: { label: "Aprovada", className: "bg-ink text-white" },
  rejected: { label: "Rejeitada", className: "bg-[var(--code-bg)] text-[var(--text)]" },
  posted: { label: "Publicada", className: "bg-ok/15 text-ok" },
  failed: { label: "Falha", className: "bg-bad/15 text-bad" },
  scheduled: { label: "Agendada", className: "bg-ink text-white" },
  publishing: { label: "Publicando", className: "bg-warn/15 text-warn" },
  published: { label: "Publicada", className: "bg-ok/15 text-ok" },
};

export function StatusChip({
  status,
  className,
}: {
  status: ChipStatus;
  className?: string;
}) {
  const style = STYLES[status];
  // An unknown status must not render an invisible chip: the backend stores
  // some of these as free-form strings, so a value can arrive that this map
  // has never seen.
  if (!style) {
    return (
      <span className={cn("inline-flex items-center h-5 px-2 rounded-full text-[11px] bg-[var(--code-bg)] text-[var(--text)]", className)}>
        {status}
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
