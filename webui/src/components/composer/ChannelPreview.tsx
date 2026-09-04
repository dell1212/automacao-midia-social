import { PlatformIcon, PLATFORM_LABEL, type Platform } from "../ui/PlatformIcon";

/** Approximation of how the post reads on each network.
 *
 * Deliberately a sketch, not a pixel-accurate mock: the job is to show line
 * breaks, truncation and where the media sits, so someone can catch copy that
 * reads badly before it ships. Pretending to be the real thing would invite
 * trust it has not earned.
 */
export function ChannelPreview({
  platform,
  body,
  accountLabel,
  thumbnailUrl,
}: {
  platform: Platform;
  body: string;
  accountLabel: string;
  thumbnailUrl?: string | null;
}) {
  const text = body.trim() || "Sem legenda.";

  return (
    <div className="rounded-[6px] border border-[var(--border)] bg-[var(--card-bg)] p-3">
      <div className="flex items-center gap-2 pb-2">
        <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-[var(--code-bg)] text-[var(--text)]">
          <PlatformIcon platform={platform} size={13} />
        </span>
        <div className="flex flex-col leading-tight">
          <span className="text-[12px] font-medium text-[var(--text-h)]">
            {accountLabel}
          </span>
          <span className="font-mono text-[10px] text-[var(--text)]">
            {PLATFORM_LABEL[platform]} · agora
          </span>
        </div>
      </div>

      <p className="m-0 whitespace-pre-wrap text-[12px] leading-relaxed text-[var(--text-h)]">
        {text}
      </p>

      {thumbnailUrl ? (
        <img
          src={thumbnailUrl}
          alt=""
          className="mt-2 w-full max-h-48 object-cover rounded-[4px] border border-[var(--border)]"
        />
      ) : (
        <div className="mt-2 flex items-center justify-center h-24 rounded-[4px] border border-dashed border-[var(--border)] text-[11px] text-[var(--text)]">
          mídia da peça
        </div>
      )}
    </div>
  );
}
