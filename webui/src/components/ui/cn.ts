/** Joins class names, dropping falsy entries.
 *
 * Deliberately not `clsx`/`tailwind-merge`: nothing here composes classes
 * deeply enough to need conflict resolution.
 *
 * This used to claim a caller's `className` "always lands last and wins"
 * because it is joined in last. That is false: with two same-specificity
 * utilities on one element, the one that wins is whichever comes later in
 * Tailwind's generated stylesheet — a fixed order that has nothing to do with
 * the order the class names appear in the `class` attribute (join order here
 * included). `w-full` happens to sort after `w-20`, so a caller passing
 * `w-20` to override a primitive's `w-full` silently loses no matter which
 * argument comes last in this call. When a caller's override needs to win,
 * either raise it out of the tie with an arbitrary variant like `[&]:w-20`
 * (which Tailwind emits into a later block of the stylesheet) or restructure
 * things so the shared primitive does not set the property the caller needs
 * to change.
 */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
