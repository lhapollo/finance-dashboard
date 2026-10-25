const cad = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" });
const cadWhole = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  maximumFractionDigits: 0,
});
const cadCompact = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  notation: "compact",
  maximumFractionDigits: 1,
});

/**
 * Formats whole cents as Canadian dollars, e.g. -450 -> "-$4.50".
 * The API sends money as integer cents; this is the only place they become dollars.
 */
export function formatCurrency(cents: number): string {
  return cad.format(cents / 100);
}

/** Dollars without cents, for big headline numbers: 140216 -> "$1,402". */
export function formatWholeDollars(cents: number): string {
  return cadWhole.format(Math.round(cents / 100));
}

/** Short form for chart axes: 150000 -> "$1.5K". */
export function formatCompactCurrency(cents: number): string {
  return cadCompact.format(cents / 100);
}

/** A "YYYY-MM-DD" date string as a Date at local midnight (not UTC, which shifts the day). */
export function parseDate(isoDate: string): Date {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** "2026-10-01" -> "Oct 2026"; with short=true -> "Oct". */
export function formatMonth(isoDate: string, short = false): string {
  return parseDate(isoDate).toLocaleDateString("en-CA", {
    month: "short",
    ...(short ? {} : { year: "numeric" }),
  });
}

/** "2026-10-15" -> "Oct 15". */
export function formatDay(isoDate: string): string {
  return parseDate(isoDate).toLocaleDateString("en-CA", { month: "short", day: "numeric" });
}

// Months are passed around as "YYYY-MM", the format the API's ?month= takes.

export function currentMonth(today = new Date()): string {
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
}

/** addMonths("2026-01", -1) -> "2025-12". */
export function addMonths(month: string, n: number): string {
  const [y, m] = month.split("-").map(Number);
  const index = y * 12 + (m - 1) + n;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
}

/** The first day of each of the `count` months ending with `last`, oldest first. */
export function monthStarts(last: string, count: number): string[] {
  return Array.from({ length: count }, (_, i) => `${addMonths(last, i - count + 1)}-01`);
}
