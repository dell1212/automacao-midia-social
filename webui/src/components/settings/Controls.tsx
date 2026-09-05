import type {
  InputHTMLAttributes,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { cn } from "../ui/cn";

// Preflight is off, so the `base` layer still styles bare input/select/
// textarea for the not-yet-migrated screens. Utilities outrank it by layer
// order, but only for properties they actually set — every property the base
// rule defines has to be restated here or the old value shows through. Same
// trap `Button.tsx` documents.
const CONTROL =
  "w-full h-8 px-2.5 text-[13px] font-normal font-sans " +
  "text-[var(--text-h)] bg-[var(--card-bg)] " +
  "border border-[var(--border)] rounded-[4px] " +
  "outline-none transition-colors " +
  "focus:border-[var(--accent-border)] focus:ring-2 focus:ring-[var(--ring)] " +
  "disabled:opacity-50 disabled:cursor-not-allowed " +
  "placeholder:text-[var(--text)]";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(CONTROL, className)} {...rest} />;
}

export function Select({ className, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  // `appearance-none` plus an explicit chevron: the native arrow ignores the
  // dark theme in Chromium and renders on a light plate.
  //
  // The wrapper is a <span class="block">, not a <div>: this renders inside
  // Field's <label>, which only accepts phrasing content.
  return (
    <span className="relative block">
      <select
        className={cn(CONTROL, "appearance-none pr-8 cursor-pointer", className)}
        {...rest}
      />
      <svg
        aria-hidden
        viewBox="0 0 12 12"
        className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-[var(--text)]"
      >
        <path d="M2 4.5 6 8.5 10 4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </span>
  );
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(CONTROL, "h-auto min-h-20 py-2 leading-relaxed", className)} {...rest} />;
}
