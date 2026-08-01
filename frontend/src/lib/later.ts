/**
 * Pushing something out to a later day, worded the same wherever it is offered:
 * in the task sheet and on the row itself.
 *
 * A due date is a calendar day, so it is built from the local one. Going through
 * `toISOString()` reads the date in UTC, which lands on the wrong day for anyone
 * west of it: pressed at six in the evening in Tucson, "tomorrow" came out as the
 * day after.
 */

export function inDays(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${month}-${day}`;
}

/** The three everyone reaches for. Same words in both places on purpose. */
export const LATER_OPTIONS: ReadonlyArray<readonly [label: string, days: number]> = [
  ['tomorrow', 1],
  ['in 3 days', 3],
  ['next week', 7],
] as const;
