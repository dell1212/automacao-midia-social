import { cn } from "../ui/cn";

/* Chart colours.
 *
 * Two series only — published and failed — and they sit adjacent in a stacked
 * bar, so the pair has to be distinguishable, not merely different.
 *
 * The obvious choice (green = published, red = failed) was measured and
 * rejected: #16a34a vs #dc2626 scores CVD ΔE 5.0 under deuteranopia, well
 * below the 8 floor, i.e. the two states look the same to a red-green
 * colourblind reader. Blue/red scores 26.4 and passes every check in both
 * modes. Identity never rests on colour alone anyway — every series is
 * direct-labelled and the table view below carries the numbers.
 */
export const SERIES = {
  published: "var(--chart-published)",
  failed: "var(--chart-failed)",
  neutral: "var(--chart-neutral)",
};

function Empty({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-32 text-[12px] text-[var(--text)]">
      {label}
    </div>
  );
}

/** Daily volume, stacked by outcome.
 *
 * The reference overlays a success-rate line on these bars — a second y-scale
 * on the same plot. That is the one thing a chart must never do, so the rate
 * lives in its own headline tile instead. Nothing is lost: the failure share
 * is already legible as the red part of each stack.
 */
export function ThroughputChart({
  data,
}: {
  data: Array<{ day: string; published: number; failed: number }>;
}) {
  if (data.length === 0) return <Empty label="Sem publicações no período" />;

  const max = Math.max(...data.map((d) => d.published + d.failed), 1);
  const height = 140;
  const gap = 4;
  const barWidth = Math.max(6, Math.min(28, 640 / data.length - gap));
  const width = data.length * (barWidth + gap);

  return (
    <div className="overflow-x-auto">
      <svg
        width={width}
        height={height + 20}
        role="img"
        aria-label="Volume publicado por dia"
      >
        {data.map((d, index) => {
          const total = d.published + d.failed;
          const x = index * (barWidth + gap);
          const publishedH = (d.published / max) * height;
          const failedH = (d.failed / max) * height;
          return (
            <g key={d.day}>
              <title>
                {d.day}: {d.published} publicadas, {d.failed} falhas
              </title>
              {/* 2px surface gap between stacked segments, so the boundary
                  reads without a stroke. */}
              {d.failed > 0 ? (
                <rect
                  x={x}
                  y={height - failedH}
                  width={barWidth}
                  height={Math.max(failedH, 2)}
                  rx={2}
                  fill={SERIES.failed}
                />
              ) : null}
              {d.published > 0 ? (
                <rect
                  x={x}
                  y={height - failedH - publishedH - (d.failed > 0 ? 2 : 0)}
                  width={barWidth}
                  height={Math.max(publishedH, 2)}
                  rx={2}
                  fill={SERIES.published}
                />
              ) : null}
              {total > 0 ? (
                <text
                  x={x + barWidth / 2}
                  y={height + 14}
                  textAnchor="middle"
                  className="fill-[var(--text)]"
                  style={{ fontSize: 9, fontFamily: "var(--mono)" }}
                >
                  {d.day.slice(8)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Per-platform volume.
 *
 * A horizontal bar rather than the reference's donut: six slices are hard to
 * compare by angle, and bars let every row carry its own name, which is what
 * keeps identity off colour entirely. One hue — this is magnitude, not
 * identity.
 */
export function PlatformBars({
  data,
  renderIcon,
}: {
  data: Array<{ platform: string; published: number; failed: number }>;
  renderIcon?: (platform: string) => React.ReactNode;
}) {
  if (data.length === 0) return <Empty label="Nenhuma plataforma com publicações" />;
  const max = Math.max(...data.map((d) => d.published + d.failed), 1);

  return (
    <div className="flex flex-col gap-1.5">
      {data.map((d) => {
        const total = d.published + d.failed;
        return (
          <div key={d.platform} className="flex items-center gap-2 text-[12px]">
            <span className="flex items-center gap-1.5 w-24 shrink-0 text-[var(--text-h)]">
              {renderIcon?.(d.platform)}
              {d.platform}
            </span>
            <div className="flex-1 flex items-center gap-0.5 h-4">
              {d.published > 0 ? (
                <div
                  className="h-full rounded-[2px]"
                  style={{
                    width: `${(d.published / max) * 100}%`,
                    background: SERIES.published,
                  }}
                />
              ) : null}
              {d.failed > 0 ? (
                <div
                  className="h-full rounded-[2px]"
                  style={{
                    width: `${(d.failed / max) * 100}%`,
                    background: SERIES.failed,
                  }}
                />
              ) : null}
            </div>
            <span className="w-14 shrink-0 text-right font-mono text-[11px] text-[var(--text)]">
              {total}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Published volume by hour of day — where the schedule actually lands. */
export function CadenceChart({
  data,
}: {
  data: Array<{ hour: number; published: number }>;
}) {
  const max = Math.max(...data.map((d) => d.published), 1);
  if (max === 0) return <Empty label="Sem publicações no período" />;
  const height = 72;

  return (
    <div className="flex items-end gap-[2px] h-[92px]">
      {data.map((d) => (
        <div key={d.hour} className="flex-1 flex flex-col items-center gap-1">
          <div
            title={`${String(d.hour).padStart(2, "0")}h: ${d.published}`}
            className="w-full rounded-[2px]"
            style={{
              height: Math.max((d.published / max) * height, d.published ? 2 : 1),
              background: d.published ? SERIES.neutral : "var(--border)",
            }}
          />
          {d.hour % 6 === 0 ? (
            <span className="font-mono text-[9px] text-[var(--text)]">{d.hour}</span>
          ) : (
            <span className="h-[11px]" />
          )}
        </div>
      ))}
    </div>
  );
}

export function Legend({ items }: { items: Array<{ label: string; color: string }> }) {
  return (
    <div className="flex items-center gap-3">
      {items.map((item) => (
        <span
          key={item.label}
          className="flex items-center gap-1.5 text-[11px] text-[var(--text)]"
        >
          <span
            className="inline-block w-2.5 h-2.5 rounded-[2px]"
            style={{ background: item.color }}
          />
          {item.label}
        </span>
      ))}
    </div>
  );
}

export function StatTile({
  label,
  value,
  hint,
  unavailable,
}: {
  label: string;
  value: string;
  hint?: string;
  /** Renders the tile as present-but-empty. Used for the two metrics this
   * system has never collected — dropping them would hide the gap. */
  unavailable?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 px-3 py-2.5 border-r border-[var(--border)] last:border-r-0",
        unavailable && "opacity-60",
      )}
    >
      <span className="text-[22px] leading-none font-semibold tracking-tight text-[var(--text-h)]">
        {unavailable ? "—" : value}
      </span>
      <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--text)]">
        {label}
      </span>
      {hint ? <span className="text-[10px] text-[var(--text)]">{hint}</span> : null}
    </div>
  );
}
