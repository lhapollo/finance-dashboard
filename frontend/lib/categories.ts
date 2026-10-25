/**
 * Which color each spending category gets in charts.
 *
 * A chart can only keep about 7 colors apart (including for colorblind readers), so the 7
 * biggest categories get a fixed slot and everything else shares a gray "Other". The slot
 * belongs to the category, not to its rank: dining stays blue in every month, even a month
 * where shopping is bigger. Slots are defined as CSS variables in app/globals.css.
 */
export const CATEGORY_SLOTS = [
  "dining",
  "shopping",
  "groceries",
  "entertainment",
  "games",
  "transport",
  "subscriptions",
] as const;

export const OTHER = "other";

/** Every category the rules in category_rules.yaml use, for the category picker. */
export const ALL_CATEGORIES = [
  ...CATEGORY_SLOTS,
  "travel",
  "education",
  "health",
  "home",
  "fees",
  "rewards",
  "uncategorized",
] as const;

/** The chart series a category is drawn in: its own slot, or "other". */
export function seriesFor(category: string): string {
  return (CATEGORY_SLOTS as readonly string[]).includes(category) ? category : OTHER;
}

/** The CSS color for a category's swatch or chart mark. */
export function categoryColor(category: string): string {
  const slot = (CATEGORY_SLOTS as readonly string[]).indexOf(category);
  return slot === -1 ? "var(--cat-other)" : `var(--cat-${slot + 1})`;
}

/** "uncategorized" -> "Uncategorized". */
export function categoryLabel(category: string): string {
  return category.charAt(0).toUpperCase() + category.slice(1);
}

/** All series in drawing order: the fixed slots, then Other on top. */
export const SERIES = [...CATEGORY_SLOTS, OTHER] as const;

export type ChartRow = { period: string } & Record<string, number | string>;

/**
 * Turns the API's one-row-per-(period, category) list into one row per period with a
 * column per series, which is the shape a stacked bar chart needs. Every period in
 * `periods` gets a row, even one with no spending, so the time axis has no gaps.
 */
export function toChartRows(
  totals: { period: string; category: string; total_cents: number }[],
  periods: string[],
): ChartRow[] {
  const rows = new Map<string, ChartRow>();
  for (const period of periods) {
    const row: ChartRow = { period };
    for (const series of SERIES) row[series] = 0;
    rows.set(period, row);
  }
  for (const t of totals) {
    const row = rows.get(t.period);
    if (row) row[seriesFor(t.category)] = (row[seriesFor(t.category)] as number) + t.total_cents;
  }
  return [...rows.values()];
}
