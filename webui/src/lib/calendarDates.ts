/** Date handling for the calendar.
 *
 * The backend stores every datetime as a naive `datetime.utcnow()` on a column
 * without `timezone=True`, so FastAPI serialises them with no offset at all —
 * "2026-09-04T15:00:00". `new Date(...)` reads a string in that shape as LOCAL
 * time, which silently shifts every card by the viewer's UTC offset and, near
 * midnight, drops it into the wrong day. Parsing goes through `parseUtc` so
 * that assumption is stated once instead of being made accidentally in each
 * component.
 */

/** Parses a backend datetime as UTC, whether or not it carries an offset. */
export function parseUtc(value: string): Date {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

/** Serialises for the API in the same naive-UTC shape the backend expects. */
export function toUtcParam(date: Date): string {
  return date.toISOString().slice(0, 19);
}

/** Local calendar day key (YYYY-MM-DD) for a UTC instant.
 *
 * Deliberately local: a post scheduled at 23:30 UTC belongs on the day the
 * viewer would call it, not on the UTC day.
 */
export function localDayKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function dayKeyOf(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** The six-week grid a month view draws, Monday-first.
 *
 * Always 42 cells so the grid never changes height between months — a month
 * that reflows from five rows to six makes the whole page jump when paging.
 */
export function monthGridDays(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  // getDay() is Sunday-based; shift so Monday is column 0.
  const leading = (first.getDay() + 6) % 7;
  const start = new Date(year, month, 1 - leading);
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
}

/** Half-open [from, to) covering the whole grid, as naive-UTC API params. */
export function monthGridRange(year: number, month: number): { from: string; to: string } {
  const days = monthGridDays(year, month);
  const first = days[0];
  const last = days[days.length - 1];
  return {
    from: toUtcParam(new Date(first.getFullYear(), first.getMonth(), first.getDate())),
    to: toUtcParam(
      new Date(last.getFullYear(), last.getMonth(), last.getDate() + 1),
    ),
  };
}

export function isSameLocalDay(a: Date, b: Date): boolean {
  return localDayKey(a) === localDayKey(b);
}

export function isBeforeToday(date: Date): boolean {
  const today = new Date();
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return date.getTime() < startOfToday.getTime();
}

const MONTHS = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

export function monthLabel(year: number, month: number): string {
  return `${MONTHS[month]} de ${year}`;
}

export const WEEKDAY_LABELS = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"];

export function timeLabel(date: Date): string {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/** Keeps the clock time of an existing schedule while moving it to another
 * day — dragging a card across the grid should not silently reset it to
 * midnight. Falls back to 09:00 for a piece that had no schedule at all. */
export function moveToDay(original: Date | null, target: Date): Date {
  const hours = original ? original.getHours() : 9;
  const minutes = original ? original.getMinutes() : 0;
  return new Date(
    target.getFullYear(),
    target.getMonth(),
    target.getDate(),
    hours,
    minutes,
    0,
    0,
  );
}
