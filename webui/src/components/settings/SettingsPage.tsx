import type { ReactNode } from "react";

/** Outer frame every settings screen shares: title, one line saying what the
 * screen controls, and the slot for the primary action. */
export function SettingsPage({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="m-0 text-[20px] font-semibold tracking-tight text-[var(--text-h)]">
            {title}
          </h1>
          {description ? (
            <p className="m-0 mt-1 max-w-2xl text-[13px] text-[var(--text)]">{description}</p>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </div>
  );
}
