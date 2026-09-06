import { cn } from "./cn";

/** The six platforms with a publisher adapter registered in the backend
 * (app/services/content/publishers/). Kept as a literal union so a typo in a
 * caller is a type error rather than a blank square. */
export type Platform =
  | "instagram"
  | "tiktok"
  | "youtube"
  | "x"
  | "facebook"
  | "linkedin";

export const PLATFORMS: Platform[] = [
  "instagram",
  "tiktok",
  "youtube",
  "x",
  "facebook",
  "linkedin",
];

export const PLATFORM_LABEL: Record<Platform, string> = {
  instagram: "Instagram",
  tiktok: "TikTok",
  youtube: "YouTube",
  x: "X",
  facebook: "Facebook",
  linkedin: "LinkedIn",
};

// Brand marks as single paths so they inherit currentColor and stay crisp at
// the 12-14px the calendar chips use. Brand colours are applied separately by
// PLATFORM_COLOR, so the same mark works on a coloured or neutral chip.
const PATHS: Record<Platform, string> = {
  instagram:
    "M12 2.2c3.2 0 3.6 0 4.9.07 1.2.05 1.8.25 2.2.42.6.2 1 .5 1.4 1 .5.4.8.8 1 1.4.2.4.4 1 .4 2.2.1 1.3.1 1.7.1 4.9s0 3.6-.1 4.9c0 1.2-.2 1.8-.4 2.2-.2.6-.5 1-1 1.4-.4.5-.8.8-1.4 1-.4.2-1 .4-2.2.4-1.3.1-1.7.1-4.9.1s-3.6 0-4.9-.1c-1.2 0-1.8-.2-2.2-.4-.6-.2-1-.5-1.4-1-.5-.4-.8-.8-1-1.4-.2-.4-.4-1-.4-2.2C2.2 15.6 2.2 15.2 2.2 12s0-3.6.1-4.9c0-1.2.2-1.8.4-2.2.2-.6.5-1 1-1.4.4-.5.8-.8 1.4-1 .4-.2 1-.4 2.2-.4C8.4 2.2 8.8 2.2 12 2.2Zm0 3.2a6.6 6.6 0 1 0 0 13.2 6.6 6.6 0 0 0 0-13.2Zm0 10.9a4.3 4.3 0 1 1 0-8.6 4.3 4.3 0 0 1 0 8.6Zm6.9-11.1a1.55 1.55 0 1 1-3.1 0 1.55 1.55 0 0 1 3.1 0Z",
  tiktok:
    "M16.6 5.8c-.9-1-1.4-2.3-1.4-3.8h-3.1v12.6a2.6 2.6 0 1 1-2.6-2.6c.3 0 .5 0 .8.1V8.9a5.9 5.9 0 0 0-.8-.1 5.7 5.7 0 1 0 5.7 5.7V8.3c1.1.8 2.5 1.3 4 1.3V6.5c-1 0-2-.3-2.6-.7Z",
  youtube:
    "M21.6 7.2s-.2-1.4-.8-2c-.7-.8-1.6-.8-2-.9C15.9 4.1 12 4.1 12 4.1s-3.9 0-6.8.2c-.4.1-1.3.1-2 .9-.6.6-.8 2-.8 2S2.2 8.8 2.2 10.5v1.6c0 1.6.2 3.3.2 3.3s.2 1.4.8 2c.7.8 1.7.8 2.2.9 1.6.1 6.6.2 6.6.2s3.9 0 6.8-.2c.4-.1 1.3-.1 2-.9.6-.6.8-2 .8-2s.2-1.6.2-3.3v-1.6c0-1.7-.2-3.3-.2-3.3ZM9.9 14.6V8.9l5.1 2.9-5.1 2.8Z",
  x: "M17.5 3h3.1l-6.8 7.8L21.8 21h-6.2l-4.9-6.4L5.1 21H2l7.2-8.3L2.4 3h6.3l4.4 5.8L17.5 3Zm-1.1 16.1h1.7L7.7 4.8H5.9l10.5 14.3Z",
  facebook:
    "M22 12a10 10 0 1 0-11.6 9.9v-7H7.9V12h2.5V9.8c0-2.5 1.5-3.9 3.8-3.9 1.1 0 2.2.2 2.2.2v2.5h-1.3c-1.2 0-1.6.8-1.6 1.6V12h2.8l-.4 2.9h-2.4v7A10 10 0 0 0 22 12Z",
  linkedin:
    "M20.4 3H3.6C2.7 3 2 3.7 2 4.6v14.8c0 .9.7 1.6 1.6 1.6h16.8c.9 0 1.6-.7 1.6-1.6V4.6c0-.9-.7-1.6-1.6-1.6ZM8.1 18.3H5.5V9.7h2.6v8.6ZM6.8 8.6a1.5 1.5 0 1 1 0-3.1 1.5 1.5 0 0 1 0 3.1Zm11.7 9.7h-2.6v-4.2c0-1 0-2.3-1.4-2.3s-1.6 1.1-1.6 2.2v4.3H10.3V9.7h2.5V11h.1c.3-.7 1.2-1.4 2.5-1.4 2.7 0 3.2 1.8 3.2 4.1v4.6Z",
};

/** The literal values live in index.css, next to every other token that
 * changes with the theme: TikTok's and X's marks are black, which is
 * invisible on the dark surface, so those two invert there. */
export const PLATFORM_COLOR: Record<Platform, string> = {
  instagram: "var(--platform-instagram)",
  tiktok: "var(--platform-tiktok)",
  youtube: "var(--platform-youtube)",
  x: "var(--platform-x)",
  facebook: "var(--platform-facebook)",
  linkedin: "var(--platform-linkedin)",
};

export function PlatformIcon({
  platform,
  size = 14,
  brandColor = true,
  className,
}: {
  platform: Platform;
  size?: number;
  /** Off renders in currentColor, for chips that already carry a tone. */
  brandColor?: boolean;
  className?: string;
}) {
  const path = PATHS[platform];
  if (!path) return null;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role="img"
      aria-label={PLATFORM_LABEL[platform] ?? platform}
      className={cn("shrink-0", className)}
      style={brandColor ? { color: PLATFORM_COLOR[platform] } : undefined}
    >
      <path d={path} fill="currentColor" />
    </svg>
  );
}
