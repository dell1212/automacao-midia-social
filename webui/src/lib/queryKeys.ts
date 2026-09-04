/** Query key factory.
 *
 * Every page before the calendar built its keys inline as ad-hoc arrays, so
 * invalidating something from another screen meant guessing the exact shape.
 * New code goes through here; the older screens can move over as they are
 * migrated.
 */
export const queryKeys = {
  calendar: (range: { from: string; to: string }, filters: Record<string, unknown>) =>
    ["calendar", range.from, range.to, filters] as const,
  calendarFilters: () => ["calendar", "filters"] as const,
  piece: (id: number | string) => ["piece", String(id)] as const,
};
