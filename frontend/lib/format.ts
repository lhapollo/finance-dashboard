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

/** "2026-10-15" -> "Oct 15" this year, "Oct 15, 2024" in any other year. */
export function formatDay(isoDate: string, today = new Date()): string {
  const d = parseDate(isoDate);
  return d.toLocaleDateString("en-CA", {
    month: "short",
    day: "numeric",
    ...(d.getFullYear() === today.getFullYear() ? {} : { year: "numeric" }),
  });
}

/** Whether a full timestamp is more than `ms` milliseconds before `now`. */
export function isOlderThan(timestamp: string, ms: number, now = new Date()): boolean {
  return now.getTime() - new Date(timestamp).getTime() > ms;
}

/** "just now", "5 minutes ago", "3 hours ago", "2 days ago", from a full timestamp. */
export function timeAgo(timestamp: string, now = new Date()): string {
  const minutes = Math.floor((now.getTime() - new Date(timestamp).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  const [n, unit] =
    minutes < 60
      ? [minutes, "minute"]
      : minutes < 60 * 24
        ? [Math.floor(minutes / 60), "hour"]
        : [Math.floor(minutes / (60 * 24)), "day"];
  return `${n} ${unit}${n === 1 ? "" : "s"} ago`;
}

/** Whole days from a "YYYY-MM-DD" date until today: yesterday is 1. */
export function daysSince(isoDate: string, today = new Date()): number {
  const start = parseDate(isoDate);
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((end.getTime() - start.getTime()) / 86_400_000);
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

/** A Date as "YYYY-MM-DD" in local time (toISOString would use UTC and can shift the day). */
export function toIsoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** addDays("2026-10-31", 1) -> "2026-11-01". */
export function addDays(isoDate: string, n: number): string {
  const d = parseDate(isoDate);
  d.setDate(d.getDate() + n);
  return toIsoDate(d);
}

export type DateRange = { start?: string; end?: string }; // end is excluded, like the API's

/** One-click date ranges for the transactions filter, relative to `today`. */
export function datePresets(today = new Date()): { label: string; range: DateRange }[] {
  const month = currentMonth(today);
  const year = today.getFullYear();
  return [
    { label: "This month", range: { start: `${month}-01`, end: `${addMonths(month, 1)}-01` } },
    {
      label: "Last month",
      range: { start: `${addMonths(month, -1)}-01`, end: `${month}-01` },
    },
    {
      label: "Last 3 months",
      range: { start: `${addMonths(month, -2)}-01`, end: `${addMonths(month, 1)}-01` },
    },
    { label: "This year", range: { start: `${year}-01-01`, end: `${year + 1}-01-01` } },
    { label: "All time", range: {} },
  ];
}
