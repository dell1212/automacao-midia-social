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
    // m-0 text-[13px] font-normal text-[var(--text)]: index.css's base layer
    // sets `label { margin: 0 8px 12px 0; font-size: 11px; font-weight: 500;
    // color: var(--text) }`. margin is neutralised today only because every
    // Field happens to sit inside a <form> (`form label { margin: 0 }`); the
    // other three are never neutralised, so the hint/error spans below —
    // which set their own color but not their own size or weight — render at
    // 11px/semibold until restated here. The label-text span still overrides
    // size, weight and color for itself, so this only changes what the
    // children that don't set their own values inherit.
    <label className="flex flex-col gap-1.5 m-0 text-[13px] font-normal text-[var(--text)]">
      {/* Spans, not <p>: only phrasing content is valid inside a <label>. */}
      <span className="text-[13px] font-medium text-[var(--text-h)]">{label}</span>
      {children}
      {hint ? <span className="text-[12px] text-[var(--text)]">{hint}</span> : null}
      {error ? <span className="text-[12px] text-bad">{error}</span> : null}
    </label>
  );
}
