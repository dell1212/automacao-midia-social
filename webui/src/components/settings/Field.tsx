import type { ReactNode } from "react";

/** Label + control + hint + error, in one shape for every settings form.
 *
 * The <label> wraps the control rather than pointing at it by id: the
 * association is implicit, so callers write <Field label="X"><Input /></Field>
 * with no id to thread through and nothing to keep in sync.
 *
 * Several screens used placeholder-as-label, which disappears the moment
 * someone types and leaves a half-filled form unreadable. That is what this
 * replaces.
 *
 * For a GROUP of controls (a set of chips, a radio group) a wrapping label is
 * wrong — one label cannot name several controls. Use <fieldset>/<legend>
 * instead, as the chip groups on the approval rules screen do.
 */
export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      {/* Spans, not <p>: only phrasing content is valid inside a <label>. */}
      <span className="text-[13px] font-medium text-[var(--text-h)]">{label}</span>
      {children}
      {hint ? <span className="text-[12px] text-[var(--text)]">{hint}</span> : null}
      {error ? <span className="text-[12px] text-bad">{error}</span> : null}
    </label>
  );
}
