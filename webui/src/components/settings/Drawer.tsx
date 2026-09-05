import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "../ui/Button";

/** Side panel for creating a record.
 *
 * Native <dialog> with showModal(), not a div with a backdrop: it gives focus
 * trapping, Esc to close, inerting the page behind, and returning focus to the
 * trigger — all of which we would otherwise have to write and get wrong.
 */
export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // Esc closes the dialog natively; this keeps React's state in step with
    // what the DOM already did.
    function onCancel(event: Event) {
      event.preventDefault();
      onClose();
    }
    dialog.addEventListener("cancel", onCancel);
    return () => dialog.removeEventListener("cancel", onCancel);
  }, [onClose]);

  return (
    <dialog
      ref={ref}
      aria-label={title}
      onClick={(event) => {
        // The backdrop is the dialog element itself: a click whose target is
        // the dialog (not a child) landed outside the panel.
        if (event.target === ref.current) onClose();
      }}
      className={
        "settings-drawer m-0 ml-auto h-svh max-h-svh w-full max-w-[min(26rem,100vw)] " +
        "p-0 border-0 bg-transparent"
      }
    >
      {/* text-[var(--text)]: <dialog> keeps the UA default `color: CanvasText`
          (measured rgb(0,0,0), not the theme's --text) since nothing here
          sets it. Harmless while every child restates its own color, but the
          next form field added here would silently render in black-on-dark. */}
      <div className="flex h-full flex-col border-l border-[var(--border)] bg-[var(--card-bg)] text-[var(--text)]">
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
          <div className="min-w-0">
            <h2 className="m-0 text-[15px] font-semibold tracking-tight text-[var(--text-h)]">
              {title}
            </h2>
            {description ? (
              <p className="m-0 mt-1 text-[12px] text-[var(--text)]">{description}</p>
            ) : null}
          </div>
          <Button
            size="sm"
            variant="ghost"
            aria-label="Fechar"
            onClick={onClose}
            // [&]:px-1.5: Button's SIZES.sm sets `px-2.5`, which sorts after
            // `px-1.5` in the generated stylesheet regardless of join order —
            // see the note on the same trick in Providers.tsx's PriorityCell.
            className="[&]:px-1.5 shrink-0"
          >
            <X size={15} />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </dialog>
  );
}
