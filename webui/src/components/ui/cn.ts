/** Joins class names, dropping falsy entries.
 *
 * Deliberately not `clsx`/`tailwind-merge`: nothing here composes classes
 * deeply enough to need conflict resolution, and the primitives put their
 * own classes first so a caller's `className` always lands last and wins.
 */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
