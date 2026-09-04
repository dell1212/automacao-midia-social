import type { ReactNode } from "react";
import { cn } from "./cn";

/** White surface on the paper background, separated by a hairline rather than
 * a shadow — the target design uses almost no elevation. */
export function Card({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "bg-[var(--card-bg)] border border-[var(--border)] rounded-[4px]",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Small uppercase letter-spaced monospace caption — the signature label of
 * the reference design. Pairs with Card as a section header. */
export function MicroLabel({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--text)]",
        className,
      )}
    >
      {children}
    </span>
  );
}
