import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "./cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
}

// The stylesheet still styles bare <button> (lime background, fixed height,
// 14px padding) for the not-yet-migrated screens. That rule lives in the
// `base` layer, so every utility here outranks it — but each property it sets
// has to be restated, or the base value shows through.
const BASE =
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap " +
  "border rounded-[4px] font-medium cursor-pointer " +
  "transition-colors disabled:opacity-50 disabled:cursor-not-allowed";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-lime text-ink border-transparent hover:bg-lime-strong",
  secondary:
    "bg-surface text-ink border-line hover:bg-paper dark:bg-transparent dark:text-[var(--text-h)]",
  ghost:
    "bg-transparent text-[var(--text)] border-transparent hover:bg-[var(--code-bg)] hover:text-[var(--text-h)]",
  danger: "bg-bad text-white border-transparent hover:opacity-90",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs",
  md: "h-8 px-3.5 text-[13px]",
};

export function Button({
  variant = "secondary",
  size = "md",
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button className={cn(BASE, VARIANTS[variant], SIZES[size], className)} {...rest}>
      {children}
    </button>
  );
}
