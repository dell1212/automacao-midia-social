import { useEffect, useRef, useState } from "react";
import { MoreHorizontal } from "lucide-react";
import { Button } from "../ui/Button";
import { cn } from "../ui/cn";

export interface RowAction {
  label: string;
  onConfirm: () => void;
  disabled?: boolean;
  danger?: boolean;
  /** Defaults to the action's own label. */
  confirmLabel?: string;
}

/** Trailing action menu for a table row.
 *
 * Destructive actions used to fire on the first click — "Desativar"
 * deactivated, no question asked. Confirmation is inline, in the row itself,
 * rather than a modal: every action here is a logical deactivation, not a
 * DELETE of data, and a full-screen interruption would outweigh it.
 */
export function RowActions({
  actions,
  pending,
}: {
  actions: RowAction[];
  pending?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const wasConfirmingRef = useRef<string | null>(null);

  // Confirmation replaces the whole subtree (menu <-> confirm row), so the
  // element that had focus is always unmounted on the way in and out of it.
  // Left alone, focus falls back to <body> and a keyboard user has to blind-
  // Tab to find their way back. Move it explicitly: into the confirm button
  // when the row appears, back to the ⋯ trigger when it goes away — but only
  // on that transition, not on mount, or every row would steal focus once.
  useEffect(() => {
    const container = rootRef.current;
    if (container) {
      if (confirming) {
        container.querySelector<HTMLButtonElement>("button")?.focus();
      } else if (wasConfirmingRef.current) {
        container.querySelector<HTMLButtonElement>("button")?.focus();
      }
    }
    wasConfirmingRef.current = confirming;
  }, [confirming]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setConfirming(null);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        setConfirming(null);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const enabled = actions.filter((action) => !action.disabled);
  if (enabled.length === 0) return null;

  const active = confirming
    ? enabled.find((action) => action.label === confirming)
    : undefined;

  if (active) {
    return (
      // ref={rootRef}: without it, this branch's own div is never the node
      // the outside-pointerdown listener below checks against — the ref only
      // followed the OTHER branch's div, so it went stale (null) the instant
      // this branch mounted. `!rootRef.current?.contains(...)` then reads as
      // "click landed outside" for every click, including the one on
      // Confirmar itself, and the listener tears the confirmation down
      // before the click handler below ever runs. Keyboard Enter never hits
      // this path (no pointerdown), which is why it kept working throughout.
      //
      // [&>button+button]:ml-0 undoes `button + button { margin-left: 8px }`
      // from index.css's base layer, same as the menu items below and the
      // chip groups elsewhere — this row is a flex-gap layout, and left
      // unscoped the base rule stacks its own margin on top of the gap.
      <div ref={rootRef} className="inline-flex items-center gap-1.5 justify-end [&>button+button]:ml-0">
        <span className="text-[12px] text-[var(--text)]">Confirmar?</span>
        <Button
          size="sm"
          variant={active.danger ? "danger" : "primary"}
          disabled={pending}
          onClick={() => {
            active.onConfirm();
            setConfirming(null);
            setOpen(false);
          }}
        >
          {active.confirmLabel ?? active.label}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
          Cancelar
        </Button>
      </div>
    );
  }

  return (
    <div ref={rootRef} className="relative inline-flex justify-end">
      <Button
        size="sm"
        variant="ghost"
        aria-label="Ações"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={pending}
        onClick={() => setOpen((value) => !value)}
        // [&]:px-1.5: Button's SIZES.sm sets `px-2.5`, which sorts after
        // `px-1.5` in the generated stylesheet regardless of the order these
        // classes are joined in — see the longer note on the same trick in
        // Providers.tsx's PriorityCell.
        className="[&]:px-1.5"
      >
        <MoreHorizontal size={15} />
      </Button>
      {open ? (
        <div
          role="menu"
          className={cn(
            "absolute right-0 top-full z-20 mt-1 min-w-40 py-1",
            "bg-[var(--card-bg)] border border-[var(--border)] rounded-[4px]",
            "shadow-[0_4px_16px_rgba(0,0,0,0.12)]",
          )}
        >
          {enabled.map((action) => (
            <button
              key={action.label}
              type="button"
              role="menuitem"
              onClick={() => setConfirming(action.label)}
              className={cn(
                "block w-full h-8 px-3 text-left text-[13px] font-medium ml-0 rounded-none",
                "bg-transparent border-0 cursor-pointer transition-colors",
                "hover:bg-[var(--code-bg)]",
                action.danger ? "text-bad" : "text-[var(--text-h)]",
              )}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
