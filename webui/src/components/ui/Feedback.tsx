import type { ReactNode } from "react";
import { cn } from "./cn";

/** Loading placeholder. Replaces the literal "Carregando..." text the legacy
 * screens use, so a list keeps its shape while it loads instead of collapsing
 * and pushing the page around. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-[4px] bg-[var(--code-bg)]", className)}
    />
  );
}

/** Several skeleton rows at a list's natural row height. */
export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-14 px-6 text-center">
      <p className="m-0 text-[15px] font-medium text-[var(--text-h)]">{title}</p>
      {hint ? <p className="m-0 max-w-md text-[13px] text-[var(--text)]">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
